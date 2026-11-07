"""
DEV-SQUAD — Playwright evidence collector (capture.py)

Captures browser debugging evidence from a supplied local demo URL and writes a
sanitized JSON evidence bundle under E:\DevSquad\bundles.

Usage (PowerShell, run from E:\DevSquad):
    # Legacy v1 output (unchanged)
    python capture\capture.py --url http://localhost:3001/ --case-id DS-001 --out bundles\DS-001.json

    # v2 output with source-prefixed IDs, plus a click to reproduce the 401
    python capture\capture.py --url http://localhost:3001/ --case-id DS-001 --schema-version 2 --click "#loginBtn" --out bundles\DS-001-v2.json

What it captures (sanitized):
  - console.error / console.warn messages
  - uncaught page errors and unhandled rejections
  - network requests and responses (URL, method, status — headers/bodies never stored)
  - selected DOM observations (button disabled state, visibility, page title, ready state)
  - cookie metadata only — names and flags, NEVER cookie values
  - storage key names only, NEVER values (schema v2)

What it NEVER collects (security rules):
  - cookie values
  - Authorization headers or authentication tokens
  - passwords / form input values
  - complete localStorage or IndexedDB contents
  - request or response bodies

Schema v1 keeps E001, E002, ... IDs. Schema v2 uses CON-, NET-, APP- prefixes.
This module is independent of Switch.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.sync_api import Page, Response, sync_playwright

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUNDLES_DIR = Path(__file__).resolve().parent.parent / "bundles"
COLLECTOR_VERSION = "0.3.0"
EVIDENCE_ID_PATTERN = re.compile(r"^E\d{3}$")

TYPE_TO_SOURCE = {
    "console_error": "console",
    "console_warning": "console",
    "console_message": "console",
    "page_error": "console",
    "unhandled_rejection": "console",
    "runtime_error": "console",
    "network_request": "network",
    "network_response": "network",
    "network_failure": "network",
    "dom_observation": "application",
    "app_observation": "application",
    "cookie_metadata": "application",
    "storage_observation": "application",
}
SOURCE_TO_PREFIX = {
    "console": "CON",
    "network": "NET",
    "application": "APP",
    "performance": "PERF",
    "security": "SEC",
    "recorder": "REC",
    "lighthouse": "LH",
}

# Types that schema v1 understands. Anything else is down-mapped in v1 mode so
# legacy bundles stay valid against bridge/schema.json.
V1_TYPES = {
    "console_error",
    "page_error",
    "network_request",
    "network_response",
    "dom_observation",
    "cookie_metadata",
}
V1_TYPE_FALLBACK = {
    "console_warning": "console_error",
    "console_message": "console_error",
    "unhandled_rejection": "page_error",
    "runtime_error": "page_error",
    "network_failure": "network_request",
    "app_observation": "dom_observation",
}

# Headers that must never be recorded or forwarded.
REDACTED_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "proxy-authorization",
}

# A missing favicon is a known, non-actionable browser request. It is recorded
# as evidence (so it can be dismissed explicitly) but it must not make an
# otherwise evidence-free capture look like a real failure.
IGNORED_FAILURE_PATHS = {"/favicon.ico"}

# ---------------------------------------------------------------------------
# Evidence ID generator
# ---------------------------------------------------------------------------

class EvidenceIdGenerator:
    """Produces v1 E### IDs or v2 source-prefixed IDs."""

    def __init__(self, schema_version: int = 1) -> None:
        self.schema_version = schema_version
        self._counters: Dict[str, int] = {}

    def next(self, source: Optional[str] = None) -> str:
        if self.schema_version == 2:
            if source is None:
                raise ValueError("v2 evidence IDs require a source")
            self._counters[source] = self._counters.get(source, 0) + 1
            return f"{SOURCE_TO_PREFIX[source]}-{self._counters[source]:03d}"
        self._counters["legacy"] = self._counters.get("legacy", 0) + 1
        return f"E{self._counters['legacy']:03d}"


# ---------------------------------------------------------------------------
# Sanitization helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Current UTC timestamp as ISO-8601 (second precision)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso_precise() -> str:
    """Current UTC timestamp with microsecond precision.

    Playwright fires request/response/console callbacks in quick succession.
    Millisecond truncation can collapse causally ordered events into the same
    timestamp, which would make the correlation engine report unverified
    ordering. Microseconds preserve the callback order without inventing data.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def is_redacted_header(name: str) -> bool:
    """Return True if a header name must be redacted."""
    return name.lower() in REDACTED_HEADERS


def sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Return a copy of headers with sensitive headers redacted."""
    sanitized: Dict[str, str] = {}
    for key, value in headers.items():
        if is_redacted_header(key):
            sanitized[key] = "[REDACTED]"
        else:
            sanitized[key] = value
    return sanitized


def is_ignored_failure_url(url: str) -> bool:
    """Return True for browser noise such as favicon.ico."""
    try:
        path = urlparse(url).path or "/"
    except ValueError:
        return False
    return path in IGNORED_FAILURE_PATHS


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class EvidenceCollector:
    """Captures browser evidence from a single page using Playwright."""

    def __init__(
        self,
        case_id: str,
        page_url: str,
        schema_version: int = 1,
        click_selector: Optional[str] = None,
        click_wait_seconds: float = 2.0,
        incident_description: Optional[str] = None,
    ) -> None:
        if schema_version not in (1, 2):
            raise ValueError("schema_version must be 1 or 2")
        self.case_id = case_id
        self.page_url = page_url
        self.schema_version = schema_version
        self.click_selector = click_selector
        self.click_wait_seconds = click_wait_seconds
        self.incident_description = incident_description
        self.id_gen = EvidenceIdGenerator(schema_version=schema_version)
        self.evidence: List[Dict[str, Any]] = []
        self.warnings: List[str] = []

    # -- evidence recording -------------------------------------------------

    def add(
        self,
        evidence_type: str,
        timestamp: Optional[str] = None,
        source: Optional[str] = None,
        **fields: Any,
    ) -> Optional[str]:
        """Add an evidence item and return its ID.

        In v1 mode the item is down-mapped to a v1 type and the v2-only
        ``source`` field is omitted so the bundle remains valid against the
        original schema. In v2 mode source-prefixed IDs are used.
        """
        resolved_source = source or TYPE_TO_SOURCE.get(evidence_type, "application")

        if self.schema_version == 1:
            if evidence_type == "storage_observation":
                # v1 has no storage evidence type; key names are a v2 addition.
                return None
            evidence_type = V1_TYPE_FALLBACK.get(evidence_type, evidence_type)
            if evidence_type not in V1_TYPES:
                evidence_type = "dom_observation"

        eid = self.id_gen.next(source=resolved_source)
        item: Dict[str, Any] = {
            "id": eid,
            "type": evidence_type,
            "timestamp": timestamp or (
                now_iso_precise() if self.schema_version == 2 else now_iso()
            ),
        }
        if self.schema_version == 2:
            item["source"] = resolved_source
        item.update(fields)
        self.evidence.append(item)
        return eid

    # -- Playwright event handlers ------------------------------------------

    def on_console(self, msg) -> None:
        """Handle console messages from the page."""
        if msg.type not in ("error", "warning"):
            return
        evidence_type = "console_warning" if msg.type == "warning" else "console_error"
        self.add(
            evidence_type,
            level=msg.type,
            message=msg.text,
            location=msg.location,
            source="console",
        )

    def on_page_error(self, exception) -> None:
        """Handle uncaught page errors."""
        self.add(
            "page_error",
            message=str(exception),
            source="console",
        )

    def on_request(self, request) -> None:
        """Handle network requests (captured lightly — no body, no secrets)."""
        fields: Dict[str, Any] = {
            "url": request.url,
            "method": request.method,
            "headers": sanitize_headers(request.headers),
            "source": "network",
        }
        if self.schema_version == 2:
            fields["resource_type"] = request.resource_type
        self.add("network_request", **fields)

    def on_response(self, response: Response) -> None:
        """Handle network responses (status, URL — body not stored)."""
        fields: Dict[str, Any] = {
            "url": response.url,
            "method": response.request.method,
            "status": response.status,
            "headers": sanitize_headers(response.headers),
            "source": "network",
        }
        if self.schema_version == 2:
            fields["resource_type"] = response.request.resource_type
        self.add("network_response", **fields)

    def on_request_failed(self, request) -> None:
        """Handle failed requests (v2 only; v1 has no network_failure type)."""
        if self.schema_version != 2:
            return
        failure = request.failure or ""
        self.add(
            "network_failure",
            url=request.url,
            method=request.method,
            resource_type=request.resource_type,
            message=str(failure),
            source="network",
        )

    # -- DOM observations ----------------------------------------------------

    def capture_dom_observations(self, page: Page, phase: str = "initial") -> None:
        """Capture a small set of safe, selected DOM observations."""
        title = page.title()
        ready_state = page.evaluate("document.readyState")

        self.add(
            "dom_observation",
            selector="html",
            observation=f"phase={phase}; page title: {title!r}; readyState: {ready_state}",
            source="application",
        )

        # Observe the login button state on the auth-failure demo.
        btn_state = page.evaluate(
            "() => { const b = document.querySelector('#loginBtn'); if (!b) return null; return { disabled: !!b.disabled, visible: !!b.offsetParent || b.getClientRects().length > 0 }; }"
        )
        if btn_state is not None:
            self.add(
                "app_observation",
                selector="#loginBtn",
                observation=(
                    f"phase={phase}; button disabled: {str(bool(btn_state.get('disabled'))).lower()}; "
                    f"visible: {str(bool(btn_state.get('visible'))).lower()}"
                ),
                source="application",
            )

        # Observe whether a loading indicator is present and visible.
        loading_state = page.evaluate(
            "() => { const el = document.querySelector('#loading'); if (!el) return null; return { visible: !!el.offsetParent || el.getClientRects().length > 0, className: el.className }; }"
        )
        if loading_state is not None:
            self.add(
                "app_observation",
                selector="#loading",
                observation=(
                    f"phase={phase}; loading indicator visible: "
                    f"{str(bool(loading_state.get('visible'))).lower()}; "
                    f"class: {loading_state.get('className')}"
                ),
                source="application",
            )

        # Observe spinners / loading class state as app state (no values).
        spinner_state = page.evaluate(
            "() => { const el = document.querySelector('.spinner'); if (!el) return null; return { visible: !!el.offsetParent || el.getClientRects().length > 0 }; }"
        )
        if spinner_state is not None:
            self.add(
                "app_observation",
                selector=".spinner",
                observation=(
                    f"phase={phase}; spinner visible: "
                    f"{str(bool(spinner_state.get('visible'))).lower()}"
                ),
                source="application",
            )

    def capture_storage_observation_names(self, page: Page) -> None:
        """Capture localStorage/sessionStorage key names only, NEVER values."""
        if self.schema_version != 2:
            return
        try:
            keys = page.evaluate(
                "() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) })"
            )
        except Exception:
            return
        if not isinstance(keys, dict):
            return
        for scope, names in keys.items():
            if isinstance(names, list) and names:
                self.add(
                    "storage_observation",
                    selector=f"{scope}Storage",
                    observation=(
                        f"{scope} storage key names: "
                        + ", ".join(str(n) for n in names[:20])
                    ),
                    source="application",
                )

    def capture_cookie_metadata(self, page: Page) -> None:
        """Capture cookie metadata — names and flags, NEVER values."""
        try:
            cookies = page.context.cookies()
        except Exception:
            cookies = []

        for cookie in cookies:
            self.add(
                "cookie_metadata",
                cookie_name=cookie.get("name"),
                cookie_domain=cookie.get("domain"),
                cookie_secure=bool(cookie.get("secure", False)),
                cookie_http_only=bool(cookie.get("httpOnly", False)),
                cookie_same_site=cookie.get("sameSite"),
                source="application",
            )
            # NOTE: cookie.get("value") is intentionally NOT recorded.

    def _maybe_click(self, page: Page) -> None:
        """Reproduce an interaction step if requested (e.g. login button click)."""
        if not self.click_selector:
            return
        try:
            page.click(self.click_selector, timeout=5000)
        except Exception:
            self.warnings.append(
                f"Click action on {self.click_selector} was not possible; "
                "the capture shows only the initial page load."
            )
            return
        try:
            page.wait_for_timeout(int(self.click_wait_seconds * 1000))
        except Exception:
            pass
        # Re-capture DOM state after the interaction so a stuck state is visible.
        self.capture_dom_observations(page, phase="after_interaction")

    # -- Evidence assessment ------------------------------------------------

    def _assess_evidence(self) -> None:
        """Add an explicit warning when the capture cannot support a cause."""
        has_console_error = any(
            e.get("type") in ("console_error", "page_error") for e in self.evidence
        )
        has_actionable_network_failure = any(
            (
                e.get("type") == "network_response"
                and isinstance(e.get("status"), int)
                and e["status"] >= 400
                and not is_ignored_failure_url(str(e.get("url", "")))
            )
            or e.get("type") == "network_failure"
            for e in self.evidence
        )
        has_dom_anomaly = any(
            "disabled: true" in str(e.get("observation", "")).lower()
            for e in self.evidence
        )

        if not has_console_error and not has_actionable_network_failure and not has_dom_anomaly:
            self.warnings.append(
                "Insufficient evidence: no console errors, no actionable failed "
                "network responses, and no DOM anomalies observed. Cannot reach a "
                "confident root-cause conclusion without inventing one."
            )

    # -- Main run -----------------------------------------------------------

    def run(self, headless: bool = True) -> Dict[str, Any]:
        """Launch browser, navigate to page_url, capture evidence, return bundle."""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context()
            page = context.new_page()

            # Wire up event listeners before navigating.
            page.on("console", self.on_console)
            page.on("pageerror", self.on_page_error)
            page.on("request", self.on_request)
            page.on("response", self.on_response)
            page.on("requestfailed", self.on_request_failed)

            try:
                page.goto(self.page_url, wait_until="networkidle", timeout=30000)
                # Small pause to let late-arriving console / network events surface.
                page.wait_for_timeout(1500)

                # Selected DOM observations (pre-interaction).
                self.capture_dom_observations(page, phase="initial")

                # Optional interaction to reproduce the incident (e.g. login click).
                self._maybe_click(page)

                # Cookie/storage metadata captured once, after interaction.
                self.capture_storage_observation_names(page)
                self.capture_cookie_metadata(page)

            finally:
                context.close()
                browser.close()

        self._assess_evidence()
        return self._build_bundle(headless=headless)

    def _build_bundle(self, headless: bool = True) -> Dict[str, Any]:
        if self.schema_version == 2:
            bundle: Dict[str, Any] = {
                "schema_version": 2,
                "case_id": self.case_id,
                "timestamp": now_iso(),
                "source": "playwright",
                "capture_source": "playwright",
                "page_url": self.page_url,
                "evidence": self.evidence,
                "capture_metadata": {
                    "collector": "capture/capture.py",
                    "collector_version": COLLECTOR_VERSION,
                    "headless": headless,
                    "interaction_selector": self.click_selector,
                    "click_wait_seconds": self.click_wait_seconds,
                },
                "redaction_applied": True,
                "warnings": self.warnings,
            }
            if self.incident_description:
                bundle["incident_description"] = self.incident_description[:4000]
            return bundle

        return {
            "case_id": self.case_id,
            "timestamp": now_iso(),
            "source": "playwright",
            "page_url": self.page_url,
            "evidence": self.evidence,
            "redaction_applied": True,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DEV-SQUAD Playwright evidence collector"
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Local demo URL to capture evidence from, e.g. http://localhost:3001/",
    )
    parser.add_argument(
        "--case-id",
        required=True,
        help="Case identifier, e.g. DS-001",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSON bundle path, e.g. bundles\\DS-001.json",
    )
    parser.add_argument(
        "--schema-version",
        type=int,
        choices=(1, 2),
        default=1,
        help="Evidence schema to emit (default: 1). Use 2 for source-prefixed IDs.",
    )
    parser.add_argument(
        "--click",
        default=None,
        help="Optional CSS selector to click after load, e.g. \"#loginBtn\".",
    )
    parser.add_argument(
        "--click-wait",
        type=float,
        default=2.0,
        help="Seconds to wait after the click before recapturing DOM state (default: 2.0).",
    )
    parser.add_argument(
        "--incident-description",
        default=None,
        help="Optional developer description of the incident (v2 only).",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run the browser in headed mode (visible) instead of headless",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Validate case_id format (DS-###).
    if not re.match(r"^DS-\d{3}$", args.case_id):
        print(f"ERROR: --case-id must match DS-### (got {args.case_id!r})", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    collector = EvidenceCollector(
        case_id=args.case_id,
        page_url=args.url,
        schema_version=args.schema_version,
        click_selector=args.click,
        click_wait_seconds=args.click_wait,
        incident_description=args.incident_description,
    )
    bundle = collector.run(headless=not args.headed)

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)

    print(f"Bundle written: {out_path}")
    print(f"  schema_version: {bundle.get('schema_version', 1)}")
    print(f"  case_id: {bundle['case_id']}")
    print(f"  evidence items: {len(bundle['evidence'])}")
    print(f"  warnings: {len(bundle['warnings'])}")
    for w in bundle["warnings"]:
        print(f"  - {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
