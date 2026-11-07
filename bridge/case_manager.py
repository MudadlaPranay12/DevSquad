"""
DEV-SQUAD — case ingestion and lifecycle.

The case manager is the only place that decides how a raw bundle becomes a
stored case: validate, migrate, redact, normalize, correlate, persist.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import storage
from .config import BUNDLES_DIR, max_bundle_bytes, max_evidence_items
from .correlation import correlate
from .migration import migrate_v1_to_v2
from .normalizer import normalize_bundle
from .redact import redact_bundle
from .validator import detect_schema_version, validate_bundle

CASE_ID_PATTERN = re.compile(r"^DS-\d{3}$")


def generate_case_id() -> str:
    """Generate the next DS-### using both SQLite and existing bundle filenames."""
    numbers = []
    if BUNDLES_DIR.exists():
        for path in BUNDLES_DIR.glob("*.json"):
            match = re.search(r"DS-(\d{3})", path.stem)
            if match:
                numbers.append(int(match.group(1)))
    numbers.append(storage.next_case_number() - 1)
    return f"DS-{(max(numbers) + 1) if numbers else 1:03d}"


def ingest_bundle(raw_bundle: Dict[str, Any], *, transport: Optional[str] = None) -> Dict[str, Any]:
    """Validate, migrate, redact, normalize, correlate and persist one bundle."""
    if not isinstance(raw_bundle, dict):
        raise ValueError("Evidence bundle must be a JSON object.")

    serialized = json.dumps(raw_bundle, ensure_ascii=False)
    if len(serialized.encode("utf-8")) > max_bundle_bytes():
        raise ValueError("Evidence bundle exceeds the configured size limit.")

    version = detect_schema_version(raw_bundle)
    is_valid, errors = validate_bundle(raw_bundle)
    if not is_valid:
        raise ValueError("Invalid evidence bundle: " + "; ".join(errors))

    working = raw_bundle
    migration_warnings: list[str] = []
    if version == 1:
        working, _ = migrate_v1_to_v2(raw_bundle)
        migration_warnings = list(working.get("warnings") or [])
        # Validate the migrated bundle before any mutation.
        migrated_valid, migrated_errors = validate_bundle(working)
        if not migrated_valid:
            raise ValueError(
                "Schema v1 bundle could not be migrated safely: "
                + "; ".join(migrated_errors)
            )

    evidence_count = len(working.get("evidence") or [])
    if evidence_count > max_evidence_items():
        raise ValueError(
            f"Evidence bundle contains {evidence_count} items; maximum is {max_evidence_items()}."
        )

    case_id = working.get("case_id")
    if not case_id or not CASE_ID_PATTERN.match(str(case_id)):
        case_id = generate_case_id()
    working["case_id"] = case_id

    redacted = redact_bundle(working)
    normalized, normalization_warnings = normalize_bundle(redacted)

    final_valid, final_errors = validate_bundle(normalized)
    if not final_valid:
        raise ValueError(
            "Redaction and normalization produced an invalid bundle: "
            + "; ".join(final_errors)
        )

    # Deduplicate warnings while preserving order.
    warnings = []
    for warning in list(migration_warnings) + list(normalization_warnings) + list(normalized.get("warnings") or []):
        if warning not in warnings:
            warnings.append(warning)
    normalized["warnings"] = warnings

    timeline = correlate(normalized)
    storage.save_case(normalized, timeline, status="received", transport=transport)

    return {
        "status": "accepted",
        "case_id": case_id,
        "schema_version": 2,
        "source_schema_version": version,
        "migrated": version == 1,
        "evidence_count": len(normalized.get("evidence") or []),
        "redaction_applied": bool(normalized.get("redaction_applied")),
        "warnings": warnings,
        "timeline": timeline,
    }


def get_case_bundle(case_id: str) -> Optional[Dict[str, Any]]:
    case = storage.get_case(case_id)
    if not case:
        return None
    return case["bundle"]


def get_case_detail(case_id: str) -> Optional[Dict[str, Any]]:
    case = storage.get_case(case_id)
    if not case:
        return None
    return {
        "case_id": case["case_id"],
        "created_at": case["created_at"],
        "updated_at": case["updated_at"],
        "schema_version": case["schema_version"],
        "capture_source": case["capture_source"],
        "page_url": case["page_url"],
        "incident_description": case["incident_description"],
        "status": case["status"],
        "stage": case["stage"],
        "transport": case["transport"],
        "evidence": case["bundle"].get("evidence", []),
        "evidence_count": len(case["bundle"].get("evidence", [])),
        "warnings": case["bundle"].get("warnings", []),
        "timeline": case["timeline"],
        "verdict": case["verdict"],
        "decision": case["decision"],
        "error": case["error"],
    }


def get_status(case_id: str) -> Optional[Dict[str, Any]]:
    case = storage.get_case(case_id)
    if not case:
        return None
    return {
        "case_id": case["case_id"],
        "status": case["status"],
        "stage": case["stage"],
        "transport": case["transport"],
        "started_at": case["started_at"],
        "finished_at": case["finished_at"],
        "error": case["error"],
        "agent_rounds": case["agent_rounds"],
        "verdict_available": case["verdict"] is not None,
    }


def record_decision(case_id: str, decision: str, note: str = "") -> Dict[str, Any]:
    case = storage.get_case(case_id)
    if not case:
        raise KeyError(case_id)
    if case["status"] not in {"completed", "failed", "timed_out"} and not case["verdict"]:
        raise ValueError("A verdict must be available before a human decision is recorded.")
    allowed = {"approve", "reject", "need_more_evidence"}
    if decision not in allowed:
        raise ValueError(f"decision must be one of {sorted(allowed)}")
    from .storage import now_iso

    record = {
        "decision": decision,
        "note": note[:2000],
        "decided_at": now_iso(),
        "verdict_confidence": (case["verdict"] or {}).get("confidence"),
        "verdict_root_cause": (case["verdict"] or {}).get("root_cause"),
    }
    storage.set_decision(case_id, record)
    storage.add_event(case_id, "status", {
        "status": case["status"],
        "stage": "human_decided",
        "decision": decision,
    })
    return record


def parse_bundle_path(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
