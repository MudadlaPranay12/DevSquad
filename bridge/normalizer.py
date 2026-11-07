"""
DEV-SQUAD — evidence normalization.

Normalization is deliberately conservative:
  * timestamps are converted to UTC and made comparable;
  * control characters are removed from untrusted text;
  * oversized untrusted strings are truncated with an explicit marker;
  * missing timestamps are marked instead of invented.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_TEXT_LENGTH = 8000
MAX_DESCRIPTION_LENGTH = 4000
TIMESTAMP_KEYS = {"timestamp", "started_at", "finished_at", "captured_at"}
ID_KEYS = {"id", "legacy_id", "case_id", "evidence_ids"}


def strip_control_chars(value: str) -> str:
    """Remove NUL and control characters while keeping newline and tab."""
    return CONTROL_CHARS.sub("", value)


def truncate_text(value: str, limit: int = MAX_TEXT_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + " …[truncated]"


def sanitize_untrusted_text(value: str, limit: int = MAX_TEXT_LENGTH) -> str:
    return truncate_text(strip_control_chars(value), limit=limit)


def normalize_timestamp(value: Any) -> Tuple[Optional[str], bool]:
    """Return (canonical UTC timestamp or None, had_no_timezone).

    Accepts ISO-8601 strings. Naive timestamps are treated as UTC and flagged.
    """
    if value is None or value == "":
        return None, False
    if not isinstance(value, str):
        return None, False

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None, False

    had_no_timezone = parsed.tzinfo is None
    if had_no_timezone:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)

    if parsed.microsecond:
        canonical = parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    else:
        canonical = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    return canonical, had_no_timezone


def _sanitize_nested(value: Any, key: str = "") -> Any:
    if isinstance(value, str):
        if key in ID_KEYS:
            return value
        if key in TIMESTAMP_KEYS:
            # Timestamps are normalized separately; leave invalid values intact
            # so validation can report them rather than silently changing them.
            return value
        limit = MAX_DESCRIPTION_LENGTH if key == "incident_description" else MAX_TEXT_LENGTH
        return sanitize_untrusted_text(value, limit=limit)
    if isinstance(value, list):
        return [_sanitize_nested(item) for item in value]
    if isinstance(value, dict):
        return {k: _sanitize_nested(v, key=k) for k, v in value.items()}
    return value


def normalize_bundle(bundle: Dict[str, Any]) -> Tuple[Dict[str, Any], list[str]]:
    """Normalize a v2 bundle in place-free fashion.

    Returns (normalized_bundle, warnings). The caller should validate again
    after normalization.
    """
    normalized = copy.deepcopy(bundle)
    warnings: list[str] = list(normalized.get("warnings") or [])

    overall_ts, overall_naive = normalize_timestamp(normalized.get("timestamp"))
    if overall_ts is None:
        # Keep missing overall time explicit rather than using wall-clock time
        # inside stored evidence.
        normalized["timestamp"] = None
        warnings.append("Bundle timestamp is missing or not ISO-8601.")
    else:
        normalized["timestamp"] = overall_ts
        if overall_naive:
            warnings.append("Bundle timestamp had no timezone; treated as UTC.")

    evidence = normalized.get("evidence")
    if isinstance(evidence, list):
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                continue
            if "timestamp" not in item or item.get("timestamp") in (None, ""):
                item["timestamp"] = None
                item["timestamp_missing"] = True
                warnings.append(
                    f"Evidence item {item.get('id', index)} has no timestamp; ordering is sequence-based."
                )
                continue

            item_ts, item_naive = normalize_timestamp(item.get("timestamp"))
            if item_ts is None:
                item["timestamp"] = None
                item["timestamp_missing"] = True
                warnings.append(
                    f"Evidence item {item.get('id', index)} has an invalid timestamp; ordering is sequence-based."
                )
            else:
                item["timestamp"] = item_ts
                item["timestamp_missing"] = False
                if item_naive:
                    warnings.append(
                        f"Evidence item {item.get('id', index)} had no timezone; treated as UTC."
                    )

    normalized = _sanitize_nested(normalized)
    # _sanitize_nested leaves timestamp fields alone, including the None values.
    normalized["warnings"] = warnings
    normalized["redaction_applied"] = True
    return normalized, warnings
