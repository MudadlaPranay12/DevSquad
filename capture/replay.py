"""
DEV-SQUAD — Evidence bundle replay (replay.py)

Loads an existing JSON evidence bundle and prints a readable incident report.

Usage (PowerShell, run from E:\DevSquad):
    python capture\replay.py bundles\DS-001.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def load_bundle(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def format_evidence(item: Dict[str, Any]) -> str:
    eid = item.get("id", "?")
    etype = item.get("type", "?")
    ts = item.get("timestamp", "?")
    lines = [f"  [{eid}] {etype} @ {ts}"]

    if item.get("message"):
        lines.append(f"      message: {item['message']}")
    if item.get("level"):
        lines.append(f"      level: {item['level']}")
    if item.get("url"):
        lines.append(f"      url: {item['url']}")
    if item.get("method"):
        lines.append(f"      method: {item['method']}")
    if "status" in item:
        lines.append(f"      status: {item['status']}")
    if item.get("selector"):
        lines.append(f"      selector: {item['selector']}")
    if item.get("observation"):
        lines.append(f"      observation: {item['observation']}")
    if item.get("cookie_name"):
        lines.append(
            f"      cookie: {item['cookie_name']} "
            f"(domain={item.get('cookie_domain')}, secure={item.get('cookie_secure')}, "
            f"httpOnly={item.get('cookie_http_only')}, sameSite={item.get('cookie_same_site')})"
        )
    return "\n".join(lines)


def print_report(bundle: Dict[str, Any]) -> None:
    print("=" * 60)
    print("DEV-SQUAD — Incident Evidence Report")
    print("=" * 60)
    print(f"Case ID:     {bundle.get('case_id')}")
    print(f"Timestamp:   {bundle.get('timestamp')}")
    print(f"Source:      {bundle.get('source')}")
    print(f"Page URL:    {bundle.get('page_url')}")
    print(f"Redacted:    {bundle.get('redaction_applied')}")
    print()

    evidence: List[Dict[str, Any]] = bundle.get("evidence", [])
    print(f"Evidence items: {len(evidence)}")
    print("-" * 60)
    for item in evidence:
        print(format_evidence(item))
        print()

    warnings: List[str] = bundle.get("warnings", [])
    if warnings:
        print("Warnings:")
        print("-" * 60)
        for w in warnings:
            print(f"  - {w}")
        print()
    else:
        print("Warnings: none")
        print()

    # Summary guidance
    print("Assessment:")
    print("-" * 60)
    has_errors = any(i["type"] in ("console_error", "page_error") for i in evidence)
    has_failures = any(
        i["type"] == "network_response" and isinstance(i.get("status"), int) and i["status"] >= 400
        for i in evidence
    )
    if has_errors or has_failures:
        print("  Sufficient evidence to investigate further. Do not invent a root cause.")
    else:
        print("  INSUFFICIENT EVIDENCE: no console errors, no failed network responses.")
        print("  Report 'insufficient evidence' — do not invent a root cause.")
    print("=" * 60)


def main(argv: List[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if len(argv) != 1:
        print("Usage: python capture\\replay.py <bundle.json>", file=sys.stderr)
        return 2

    bundle_path = Path(argv[0])
    if not bundle_path.exists():
        print(f"ERROR: bundle not found: {bundle_path}", file=sys.stderr)
        return 1

    bundle = load_bundle(bundle_path)
    print_report(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
