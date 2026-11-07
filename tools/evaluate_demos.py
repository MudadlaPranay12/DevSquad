"""Acceptance harness for the two DEV-SQUAD demo scenarios.

Runs the real LocalRunner investigation through a running bridge and asserts the
two behaviours the MVP must guarantee:

  1. auth-failure (DS-001): a determined, evidence-cited authentication failure
     with Medium confidence.
  2. stuck-spinner (DS-002): honestly reports "Not determined" / Low because the
     captured evidence does not identify a cause.

Usage:
    python -m bridge                     # in one terminal
    python tools/evaluate_demos.py       # in another

The token is read from $DEV_SQUAD_TOKEN, bridge/.devsquad_token, or --token.
No findings are mocked: the script only reads what the bridge and agents store.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLES = {
    "DS-001": ROOT / "bundles" / "DS-001-v2.json",
    "DS-002": ROOT / "bundles" / "DS-002-v2.json",
}


def resolve_token(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    env = os.environ.get("DEV_SQUAD_TOKEN")
    if env:
        return env
    token_file = ROOT / "bridge" / ".devsquad_token"
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    raise SystemExit(
        "No pairing token found. Start the bridge with `python -m bridge --token` "
        "or pass --token."
    )


class Bridge:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def call(self, path: str, method: str = "GET", body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "X-DevSquad-Token": self.token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc

    def wait_for_completion(self, case_id: str, timeout: int) -> Dict[str, Any]:
        deadline = time.time() + timeout
        last_stage = None
        while time.time() < deadline:
            status = self.call(f"/cases/{case_id}/status")
            stage = (status.get("status"), status.get("stage"))
            if stage != last_stage:
                print(f"  [{case_id}] {stage[0]} / {stage[1]}")
                last_stage = stage
            if status.get("status") in {"completed", "failed", "timed_out"}:
                return status
            time.sleep(3)
        raise RuntimeError(f"{case_id} did not finish within {timeout} seconds.")


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def validate_auth_case(bridge: Bridge, case_id: str) -> None:
    detail = bridge.call(f"/cases/{case_id}/detail")
    verdict_response = bridge.call(f"/cases/{case_id}/verdict")
    verdict = verdict_response.get("verdict") or {}
    evidence_ids = {item["id"] for item in detail.get("evidence", [])}

    print(f"  root cause: {verdict.get('root_cause')}")
    print(f"  confidence: {verdict.get('confidence')} ({verdict.get('confidence_method')})")
    print(f"  sources: {verdict.get('confidence_factors', {}).get('independent_sources')}")

    if verdict.get("root_cause_determined") is not True:
        fail(f"{case_id} did not determine the auth root cause.")
    if verdict.get("confidence") != "Medium":
        fail(
            f"{case_id} confidence was {verdict.get('confidence')!r}, expected 'Medium'."
        )
    supporting = set(verdict.get("supporting_evidence") or [])
    console_cited = any(eid.startswith("CON-") for eid in supporting)
    network_cited = any(eid.startswith("NET-") for eid in supporting)
    if not console_cited:
        fail(f"{case_id} cites no console evidence (expected a CON- ID).")
    if not network_cited:
        fail(f"{case_id} cites no network evidence (expected a NET- ID).")
    unknown = supporting - evidence_ids
    if unknown:
        fail(f"{case_id} cites evidence that does not exist: {sorted(unknown)}")
    if len(verdict.get("confidence_factors", {}).get("independent_sources", [])) < 2:
        fail(f"{case_id} relies on fewer than two independent sources.")
    if not verdict.get("failure_chain"):
        fail(f"{case_id} has no cited failure chain.")
    print(f"  PASS: {case_id} determined, cited, Medium confidence")


def validate_spinner_case(bridge: Bridge, case_id: str) -> None:
    verdict = (bridge.call(f"/cases/{case_id}/verdict").get("verdict") or {})
    print(f"  root cause: {verdict.get('root_cause')}")
    print(f"  confidence: {verdict.get('confidence')}")
    print(f"  override: {verdict.get('insufficient_evidence_override')}")

    if verdict.get("root_cause_determined") is not False:
        fail(f"{case_id} invented a root cause without direct failure evidence.")
    if verdict.get("root_cause") != "Not determined":
        fail(f"{case_id} root cause was {verdict.get('root_cause')!r}.")
    if verdict.get("confidence") != "Low":
        fail(f"{case_id} confidence was {verdict.get('confidence')!r}, expected 'Low'.")
    if verdict.get("insufficient_evidence_override") is not True:
        fail(f"{case_id} did not record the insufficient-evidence override.")
    if not verdict.get("missing_evidence"):
        fail(f"{case_id} did not explain what evidence is missing.")
    print(f"  PASS: {case_id} honestly reports Not determined / Low")


def run_case(bridge: Bridge, case_id: str, bundle_path: Path, timeout: int) -> None:
    print(f"\n=== {case_id}: {bundle_path.name} ===")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    acceptance = bridge.call("/cases", method="POST", body=bundle)
    print(
        f"  ingested {acceptance.get('evidence_count')} evidence items "
        f"(schema v{acceptance.get('schema_version')}, migrated={acceptance.get('migrated')})"
    )
    bridge.call(f"/cases/{case_id}/investigate", method="POST")
    status = bridge.wait_for_completion(case_id, timeout)
    if status.get("status") != "completed":
        fail(f"{case_id} ended with status {status.get('status')}: {status.get('error')}")
    if not status.get("verdict_available"):
        fail(f"{case_id} completed without a verdict.")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=None)
    parser.add_argument("--timeout", type=int, default=900, help="Per-case timeout in seconds.")
    parser.add_argument(
        "--bundle",
        action="append",
        default=None,
        metavar="CASE_ID=PATH",
        help="Override a bundle path, e.g. DS-001=bundles/custom.json",
    )
    args = parser.parse_args(argv)

    bridge = Bridge(args.bridge, resolve_token(args.token))

    try:
        health = bridge.call("/health")
    except Exception as exc:  # noqa: BLE001 - harness should explain connectivity
        raise SystemExit(f"Bridge is not reachable at {args.bridge}: {exc}") from exc
    print(
        f"Bridge {health.get('version')} | transport={health.get('transport')} "
        f"| model={health.get('model')}"
    )

    bundles = dict(DEFAULT_BUNDLES)
    for override in args.bundle or []:
        if "=" not in override:
            raise SystemExit(f"Invalid --bundle value: {override}")
        case_id, path = override.split("=", 1)
        bundles[case_id] = Path(path)

    for case_id in ("DS-001", "DS-002"):
        run_case(bridge, case_id, bundles[case_id], args.timeout)

    print("\n=== Verdict checks ===")
    validate_auth_case(bridge, "DS-001")
    validate_spinner_case(bridge, "DS-002")
    print("\nAll demo acceptance checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
