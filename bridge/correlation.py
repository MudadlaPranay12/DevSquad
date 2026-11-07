"""
DEV-SQUAD — deterministic correlation engine.

What this module does:
  * normalizes timestamps to UTC;
  * computes relative event times from the earliest observation;
  * sorts events chronologically, with missing timestamps after timed events;
  * preserves original evidence IDs;
  * identifies the first directly observed error;
  * proposes *candidate* relationships only — never causal claims.

It does not use an LLM. Running it twice on the same bundle produces the same
timeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

ERROR_TYPES = {
    "console_error",
    "page_error",
    "unhandled_rejection",
    "runtime_error",
    "network_failure",
}
APP_FAILURE_MARKERS = (
    "error",
    "failed",
    "failure",
    "absent",
    "missing",
    "disabled: true",
    "stuck",
    "timeout",
)


def parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_relative(milliseconds: int) -> str:
    sign = "-" if milliseconds < 0 else ""
    ms = abs(milliseconds)
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{sign}{minutes:02d}:{seconds:02d}.{millis:03d}"


def _event_summary(item: Dict[str, Any]) -> str:
    evidence_type = item.get("type", "evidence")
    if item.get("message"):
        return f"{evidence_type}: {item['message']}"
    if item.get("url"):
        status = item.get("status")
        method = item.get("method", "")
        if status is not None:
            return f"{method} {item['url']} → {status}".strip()
        return f"{method} {item['url']}".strip()
    if item.get("observation"):
        selector = f"{item.get('selector')}: " if item.get("selector") else ""
        return f"{evidence_type}: {selector}{item['observation']}"
    if item.get("cookie_name"):
        return f"cookie metadata: {item['cookie_name']}"
    return evidence_type


def _is_error(item: Dict[str, Any]) -> bool:
    if item.get("type") in ERROR_TYPES:
        return True
    status = item.get("status")
    return isinstance(status, int) and status >= 400


def _is_app_failure(item: Dict[str, Any]) -> bool:
    if item.get("source") != "application":
        return False
    # The page-title observation is descriptive metadata, not an app failure
    # signal. Demo titles contain words like "auth-failure" or "stuck-spinner",
    # which must not be mistaken for an observed failure state.
    if item.get("type") == "dom_observation" and item.get("selector") == "html":
        return False
    text = f"{item.get('observation', '')} {item.get('message', '')}".lower()
    return any(marker in text for marker in APP_FAILURE_MARKERS)


def _network_key(item: Dict[str, Any]) -> Tuple[str, str]:
    method = str(item.get("method", "GET")).upper()
    url = str(item.get("url", ""))
    parsed = urlparse(url)
    path = parsed.path or url
    return method, f"{parsed.netloc}{path}"


def correlate(bundle: Dict[str, Any]) -> Dict[str, Any]:
    raw_evidence = bundle.get("evidence") or []
    parsed: List[Tuple[Optional[datetime], int, Dict[str, Any]]] = []
    warnings: List[str] = []

    for index, item in enumerate(raw_evidence):
        if not isinstance(item, dict):
            continue
        item_ts = parse_timestamp(item.get("timestamp"))
        parsed.append((item_ts, index, item))

    timed = [entry for entry in parsed if entry[0] is not None]
    untimed = [entry for entry in parsed if entry[0] is None]

    bundle_ts = parse_timestamp(bundle.get("timestamp"))
    base_time = min((entry[0] for entry in timed), default=bundle_ts)
    if base_time is None:
        base_time = datetime(1970, 1, 1, tzinfo=timezone.utc)
        warnings.append("No usable timestamps; timeline uses original evidence order.")

    # Stable sort: time first, then original index. Untimed events follow in
    # original order and are explicitly marked sequence-only.
    timed.sort(key=lambda entry: (entry[0], entry[1]))
    ordered = timed + untimed

    timestamp_counts: Dict[str, int] = {}
    for ts, _, _ in timed:
        key = ts.isoformat()
        timestamp_counts[key] = timestamp_counts.get(key, 0) + 1

    events: List[Dict[str, Any]] = []
    id_to_event: Dict[str, Dict[str, Any]] = {}
    for order_index, (ts, original_index, item) in enumerate(ordered):
        evidence_id = str(item.get("id", f"UNKNOWN-{original_index}"))
        if ts is None:
            relative_ms = None
            relative = None
            ordering = "sequence_only"
        else:
            relative_ms = int(round((ts - base_time).total_seconds() * 1000))
            relative = format_relative(relative_ms)
            ordering = "timestamp"
            if timestamp_counts.get(ts.isoformat(), 0) > 1:
                ordering = "same_timestamp"

        event = {
            "evidence_id": evidence_id,
            "legacy_id": item.get("legacy_id"),
            "source": item.get("source"),
            "type": item.get("type"),
            "timestamp": item.get("timestamp"),
            "relative_ms": relative_ms,
            "relative": relative,
            "ordering": ordering,
            "order": order_index,
            "summary": _event_summary(item),
            "is_error": _is_error(item),
            "is_app_failure": _is_app_failure(item),
            "related_evidence_ids": [],
            "relationships": [],
        }
        events.append(event)
        id_to_event[evidence_id] = event

    # Build candidate associations.
    relationships: List[Dict[str, Any]] = []
    requests: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for _, _, item in ordered:
        if item.get("type") == "network_request":
            requests.setdefault(_network_key(item), []).append(item)

    paired_requests: set[str] = set()
    for response in [item for _, _, item in ordered if item.get("type") == "network_response"]:
        key = _network_key(response)
        candidates = requests.get(key, [])
        request = None
        for candidate in candidates:
            candidate_id = str(candidate.get("id"))
            if candidate_id in paired_requests:
                continue
            request_ts = parse_timestamp(candidate.get("timestamp"))
            response_ts = parse_timestamp(response.get("timestamp"))
            if request_ts is None or response_ts is None or request_ts <= response_ts:
                request = candidate
                break
        if request is None:
            continue
        paired_requests.add(str(request.get("id")))
        relationship = {
            "from": request.get("id"),
            "to": response.get("id"),
            "basis": "matching method and URL; request precedes response",
            "causal": False,
            "confidence": "candidate",
        }
        relationships.append(relationship)
        for evidence_id in (str(request.get("id")), str(response.get("id"))):
            other = str(response.get("id")) if evidence_id == str(request.get("id")) else str(request.get("id"))
            if other not in id_to_event[evidence_id]["related_evidence_ids"]:
                id_to_event[evidence_id]["related_evidence_ids"].append(other)

    # Console errors and network failures that mention the same URL path are
    # candidates for the same failure chain. They are not declared causal.
    console_items = [
        item for _, _, item in ordered
        if item.get("source") == "console" or item.get("type") in {"console_error", "page_error", "runtime_error"}
    ]
    network_items = [
        item for _, _, item in ordered
        if item.get("type") in {"network_response", "network_failure", "network_request"}
    ]
    for console_item in console_items:
        console_text = f"{console_item.get('message', '')} {console_item.get('location', '')}".lower()
        for network_item in network_items:
            url = str(network_item.get("url", ""))
            path = urlparse(url).path
            status = network_item.get("status")
            mentioned = bool(path and path.lower() in console_text)
            failing = isinstance(status, int) and status >= 400
            if not (mentioned or failing):
                continue
            relationship = {
                "from": console_item.get("id"),
                "to": network_item.get("id"),
                "basis": "temporal proximity with a related URL or failure signal",
                "causal": False,
                "confidence": "candidate",
            }
            if relationship not in relationships:
                relationships.append(relationship)
                a = id_to_event.get(str(console_item.get("id")))
                b = id_to_event.get(str(network_item.get("id")))
                if a and b:
                    a["related_evidence_ids"].append(b["evidence_id"])
                    b["related_evidence_ids"].append(a["evidence_id"])

    # Application observations near a failing event are candidates for context.
    for app_item in [
        item for _, _, item in ordered if item.get("source") == "application"
    ]:
        app_ts = parse_timestamp(app_item.get("timestamp"))
        if app_ts is None:
            continue
        for failing_item in [
            item for _, _, item in ordered
            if _is_error(item) or _is_app_failure(item)
        ]:
            fail_ts = parse_timestamp(failing_item.get("timestamp"))
            if fail_ts is None or abs((app_ts - fail_ts).total_seconds()) > 2:
                continue
            relationship = {
                "from": failing_item.get("id"),
                "to": app_item.get("id"),
                "basis": "within 2 seconds of a failure observation",
                "causal": False,
                "confidence": "candidate",
            }
            if relationship not in relationships:
                relationships.append(relationship)
                a = id_to_event.get(str(failing_item.get("id")))
                b = id_to_event.get(str(app_item.get("id")))
                if a and b:
                    a["related_evidence_ids"].append(b["evidence_id"])
                    b["related_evidence_ids"].append(a["evidence_id"])

    first_error = next((event for event in events if event["is_error"]), None)
    app_failures = [event for event in events if event["is_app_failure"]]
    sources = sorted({
        str(item.get("source")) for _, _, item in ordered if item.get("source")
    })
    has_console_error = any(item.get("type") in ERROR_TYPES for _, _, item in ordered)
    has_network_failure = any(
        item.get("type") == "network_failure"
        or (isinstance(item.get("status"), int) and item["status"] >= 400)
        for _, _, item in ordered
    )
    has_app_failure = bool(app_failures)
    direct_failure = has_console_error or has_network_failure

    if any(event["ordering"] == "same_timestamp" for event in events):
        warnings.append(
            "Some events share the same timestamp; their relative ordering is unverified."
        )
    if any(event["ordering"] == "sequence_only" for event in events):
        warnings.append(
            "Some events have no timestamp; their position is based only on capture order."
        )

    lines = []
    for event in events:
        prefix = event["relative"] if event["relative"] is not None else "[no timestamp]"
        marker = " *first-error*" if first_error and event["evidence_id"] == first_error["evidence_id"] else ""
        lines.append(f"{prefix} {event['evidence_id']} {event['summary']}{marker}")

    return {
        "case_id": bundle.get("case_id"),
        "base_time": base_time.isoformat().replace("+00:00", "Z"),
        "events": events,
        "relationships": relationships,
        "first_error_id": first_error["evidence_id"] if first_error else None,
        "coverage": {
            "evidence_count": len(events),
            "sources": sources,
            "has_console_error": has_console_error,
            "has_network_failure": has_network_failure,
            "has_app_failure": has_app_failure,
            "has_direct_failure": direct_failure,
            "ordering_verified": all(
                event["ordering"] in {"timestamp", "same_timestamp"} for event in events
            ) and bool(events),
            "same_timestamp_events": [
                event["evidence_id"]
                for event in events
                if event["ordering"] == "same_timestamp"
            ],
            "untimed_events": [
                event["evidence_id"]
                for event in events
                if event["ordering"] == "sequence_only"
            ],
            "capture_complete": not any(
                "Insufficient evidence" in str(w) for w in (bundle.get("warnings") or [])
            ),
        },
        "timeline_text": "\n".join(lines),
        "warnings": warnings,
        "insufficient_evidence": not direct_failure and not has_app_failure,
    }
