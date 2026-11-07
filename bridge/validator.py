"""
DEV-SQUAD — evidence bundle validator.

Supports both schema versions:
  * v1: bridge/schema.json (legacy E### IDs) — unchanged.
  * v2: bridge/schema_v2.json (source-prefixed IDs).

validate_bundle() auto-detects the version so existing callers keep working.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import jsonschema

BRIDGE_DIR = Path(__file__).parent
SCHEMA_V1_PATH = BRIDGE_DIR / "schema.json"
SCHEMA_V2_PATH = BRIDGE_DIR / "schema_v2.json"
PREFIX_TO_SOURCE = {
    "CON": "console",
    "NET": "network",
    "APP": "application",
    "PERF": "performance",
    "SEC": "security",
    "REC": "recorder",
    "LH": "lighthouse",
}


def load_schema(version: int = 1) -> Dict[str, Any]:
    path = SCHEMA_V2_PATH if version == 2 else SCHEMA_V1_PATH
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def detect_schema_version(bundle: Dict[str, Any]) -> int:
    return 2 if bundle.get("schema_version") == 2 else 1


def _validate_timestamp(value: Any) -> bool:
    if value in (None, ""):
        return True
    if not isinstance(value, str):
        return False
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        return False


def _validate_v2_semantics(bundle: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    seen: set[str] = set()
    evidence = bundle.get("evidence") or []
    if not isinstance(evidence, list):
        return errors

    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            continue
        evidence_id = item.get("id")
        source = item.get("source")
        if isinstance(evidence_id, str):
            if evidence_id in seen:
                errors.append(f"Duplicate evidence id {evidence_id} (index {index}).")
            seen.add(evidence_id)
            prefix = evidence_id.split("-", 1)[0]
            expected_source = PREFIX_TO_SOURCE.get(prefix)
            if expected_source and source != expected_source:
                errors.append(
                    f"Evidence {evidence_id} has source {source!r}, expected {expected_source!r}."
                )
        if not _validate_timestamp(item.get("timestamp")):
            errors.append(f"Evidence {evidence_id or index} has an invalid timestamp.")
        if item.get("timestamp") in (None, "") and item.get("timestamp_missing") is not True:
            errors.append(
                f"Evidence {evidence_id or index} has no timestamp but timestamp_missing is not true."
            )

    legacy_map = bundle.get("legacy_id_map")
    if isinstance(legacy_map, dict):
        for old_id, new_id in legacy_map.items():
            if new_id not in seen:
                errors.append(
                    f"legacy_id_map points {old_id} at {new_id}, which is not in evidence."
                )
        item_legacy_ids = {
            item.get("legacy_id")
            for item in evidence
            if isinstance(item, dict) and item.get("legacy_id")
        }
        missing = sorted(item_legacy_ids - set(legacy_map))
        if missing:
            errors.append(
                "Evidence items have legacy_id values missing from legacy_id_map: "
                + ", ".join(missing)
            )
    return errors


def validate_bundle(bundle: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a v1 or v2 bundle.

    Returns:
        (is_valid, error_messages). When is_valid is True, error_messages is empty.
    """
    version = detect_schema_version(bundle)
    schema = load_schema(version)
    try:
        jsonschema.validate(instance=bundle, schema=schema)
    except jsonschema.ValidationError as e:
        path = " -> ".join(str(p) for p in e.path) if e.path else "root"
        return False, [f"{e.message} (at {path})"]
    except jsonschema.SchemaError as e:
        return False, [f"Schema error: {e.message}"]

    if version == 2:
        semantic_errors = _validate_v2_semantics(bundle)
        if semantic_errors:
            return False, semantic_errors
    return True, []
