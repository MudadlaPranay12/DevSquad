"""
DEV-SQUAD — schema v1 to v2 migration.

Rules:
  * Every original evidence item is preserved.
  * The original E### identifier is kept in legacy_id.
  * A stable, deterministic legacy_id_map is produced.
  * References to old IDs in text fields are rewritten to the new IDs.
  * No evidence item is silently dropped or reordered.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Tuple

TYPE_TO_SOURCE: Dict[str, str] = {
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
    "performance_metric": "performance",
    "security_observation": "security",
    "recorder_event": "recorder",
    "lighthouse_audit": "lighthouse",
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

PREFIX_TO_SOURCE = {prefix: source for source, prefix in SOURCE_TO_PREFIX.items()}
OLD_ID_PATTERN = re.compile(r"\bE(\d{3})\b")
PRESERVED_ID_KEYS = {"id", "legacy_id", "case_id", "legacy_id_map"}


def _rewrite_references(value: Any, mapping: Dict[str, str]) -> Any:
    """Rewrite old evidence IDs inside nested text fields."""
    if isinstance(value, str):
        return OLD_ID_PATTERN.sub(lambda m: mapping.get(m.group(0), m.group(0)), value)
    if isinstance(value, list):
        return [_rewrite_references(v, mapping) for v in value]
    if isinstance(value, dict):
        return {
            key: (
                item
                if key in PRESERVED_ID_KEYS
                else _rewrite_references(item, mapping)
            )
            for key, item in value.items()
        }
    return value


def migrate_v1_to_v2(bundle: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Return (v2_bundle, legacy_id_map).

    The input bundle is not mutated. Migration is deterministic for the same
    input: evidence order determines the sequence numbers within each source.
    """
    migrated = copy.deepcopy(bundle)
    counters = {source: 0 for source in SOURCE_TO_PREFIX}
    legacy_map: Dict[str, str] = {}
    warnings: List[str] = list(migrated.get("warnings") or [])
    duplicate_legacy_ids: List[str] = []
    unknown_types: List[str] = []

    new_evidence: List[Dict[str, Any]] = []
    for item in migrated.get("evidence", []):
        item_copy = copy.deepcopy(item)
        evidence_type = str(item_copy.get("type", "app_observation"))
        source = TYPE_TO_SOURCE.get(evidence_type)
        if source is None:
            source = "application"
            unknown_types.append(evidence_type)

        counters[source] += 1
        new_id = f"{SOURCE_TO_PREFIX[source]}-{counters[source]:03d}"
        old_id = item_copy.get("id")
        if isinstance(old_id, str):
            if old_id in legacy_map:
                duplicate_legacy_ids.append(old_id)
            else:
                legacy_map[old_id] = new_id
            item_copy["legacy_id"] = old_id
        item_copy["id"] = new_id
        item_copy["source"] = source
        new_evidence.append(item_copy)

    migrated["evidence"] = new_evidence
    migrated["schema_version"] = 2
    migrated["capture_source"] = migrated.get("source", "playwright")
    migrated["legacy_id_map"] = legacy_map

    # Rewrite E### references everywhere except the preserved identifier fields.
    migrated = _rewrite_references(migrated, legacy_map)

    warnings.append(
        "Migrated from schema v1 to v2. Original evidence IDs are preserved in legacy_id."
    )
    if duplicate_legacy_ids:
        warnings.append(
            "Duplicate legacy evidence IDs were found and given distinct v2 IDs: "
            + ", ".join(sorted(set(duplicate_legacy_ids)))
        )
    if unknown_types:
        warnings.append(
            "Unknown v1 evidence types were preserved and mapped to the application source: "
            + ", ".join(sorted(set(unknown_types)))
        )
    migrated["warnings"] = warnings
    return migrated, legacy_map
