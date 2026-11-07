"""
DEV-SQUAD — SQLite case storage.

SQLite is used directly (no ORM) because the hackathon MVP needs transparent,
parameterized SQL and a zero-setup local database. All writes are transactional.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .config import get_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    capture_source TEXT,
    page_url TEXT,
    incident_description TEXT,
    status TEXT NOT NULL DEFAULT 'received',
    stage TEXT NOT NULL DEFAULT 'received',
    transport TEXT,
    bundle_json TEXT NOT NULL,
    timeline_json TEXT,
    verdict_json TEXT,
    decision_json TEXT,
    error TEXT,
    agent_rounds INTEGER NOT NULL DEFAULT 0,
    token_usage_json TEXT,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    case_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    legacy_id TEXT,
    source TEXT,
    type TEXT,
    timestamp TEXT,
    relative_ms INTEGER,
    order_index INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (case_id, evidence_id),
    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    message_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    content_json TEXT NOT NULL,
    round INTEGER NOT NULL DEFAULT 0,
    accepted INTEGER NOT NULL DEFAULT 1,
    validation_error TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS case_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    data_json TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence(case_id, order_index);
CREATE INDEX IF NOT EXISTS idx_messages_case ON agent_messages(case_id, id);
CREATE INDEX IF NOT EXISTS idx_events_case ON case_events(case_id, id);
"""

CASE_UPDATE_FIELDS = {
    "status", "stage", "transport", "timeline_json", "verdict_json",
    "decision_json", "error", "agent_rounds", "token_usage_json",
    "started_at", "finished_at", "incident_description",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn, conn:
        conn.executescript(SCHEMA)


def next_case_number() -> int:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(CAST(SUBSTR(case_id, 4) AS INTEGER)) AS max_num FROM cases"
        ).fetchone()
    return int(row["max_num"] or 0) + 1


def case_exists(case_id: str) -> bool:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
    return row is not None


def save_case(
    bundle: Dict[str, Any],
    timeline: Dict[str, Any],
    *,
    status: str = "received",
    transport: Optional[str] = None,
) -> None:
    """Insert or replace a case, its evidence rows and its timeline.

    Re-ingesting an existing case is intentional: demos repeat DS-001/DS-002.
    It clears prior investigation state so no stale verdict survives.
    """
    init_db()
    case_id = bundle["case_id"]
    timestamp = now_iso()
    evidence = bundle.get("evidence") or []
    relative_by_id = {
        event.get("evidence_id"): event.get("relative_ms")
        for event in (timeline.get("events") or [])
    }

    with connect() as conn, conn:
        existing = conn.execute(
            "SELECT created_at FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        created_at = existing["created_at"] if existing else timestamp

        conn.execute(
            """
            INSERT INTO cases (
                case_id, created_at, updated_at, schema_version, capture_source,
                page_url, incident_description, status, stage, transport,
                bundle_json, timeline_json, verdict_json, decision_json, error,
                agent_rounds, token_usage_json, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, NULL, NULL, NULL)
            ON CONFLICT(case_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                schema_version = excluded.schema_version,
                capture_source = excluded.capture_source,
                page_url = excluded.page_url,
                incident_description = excluded.incident_description,
                status = excluded.status,
                stage = excluded.stage,
                transport = excluded.transport,
                bundle_json = excluded.bundle_json,
                timeline_json = excluded.timeline_json,
                verdict_json = NULL,
                decision_json = NULL,
                error = NULL,
                agent_rounds = 0,
                token_usage_json = NULL,
                started_at = NULL,
                finished_at = NULL
            """,
            (
                case_id,
                created_at,
                timestamp,
                int(bundle.get("schema_version", 2)),
                bundle.get("capture_source") or bundle.get("source"),
                bundle.get("page_url"),
                bundle.get("incident_description"),
                status,
                status,
                transport,
                json.dumps(bundle, ensure_ascii=False),
                json.dumps(timeline, ensure_ascii=False),
            ),
        )
        conn.execute("DELETE FROM evidence WHERE case_id = ?", (case_id,))
        conn.execute("DELETE FROM agent_messages WHERE case_id = ?", (case_id,))
        conn.execute("DELETE FROM case_events WHERE case_id = ?", (case_id,))

        for order_index, item in enumerate(evidence):
            if not isinstance(item, dict):
                continue
            conn.execute(
                """
                INSERT INTO evidence (
                    case_id, evidence_id, legacy_id, source, type, timestamp,
                    relative_ms, order_index, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    str(item.get("id")),
                    item.get("legacy_id"),
                    item.get("source"),
                    item.get("type"),
                    item.get("timestamp"),
                    relative_by_id.get(item.get("id")),
                    order_index,
                    json.dumps(item, ensure_ascii=False),
                ),
            )
        add_event(case_id, "case_ingested", {
            "status": status,
            "evidence_count": len(evidence),
            "schema_version": bundle.get("schema_version", 2),
        }, conn=conn)


def _row_to_case(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "case_id": row["case_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "schema_version": row["schema_version"],
        "capture_source": row["capture_source"],
        "page_url": row["page_url"],
        "incident_description": row["incident_description"],
        "status": row["status"],
        "stage": row["stage"],
        "transport": row["transport"],
        "bundle": json.loads(row["bundle_json"]),
        "timeline": json.loads(row["timeline_json"]) if row["timeline_json"] else None,
        "verdict": json.loads(row["verdict_json"]) if row["verdict_json"] else None,
        "decision": json.loads(row["decision_json"]) if row["decision_json"] else None,
        "error": row["error"],
        "agent_rounds": row["agent_rounds"],
        "token_usage": json.loads(row["token_usage_json"]) if row["token_usage_json"] else None,
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
    return _row_to_case(row) if row else None


def list_cases() -> List[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT c.case_id, c.created_at, c.updated_at, c.schema_version,
                   c.capture_source, c.page_url, c.status, c.stage,
                   c.transport, c.incident_description,
                   (SELECT COUNT(*) FROM evidence e WHERE e.case_id = c.case_id) AS evidence_count
            FROM cases c
            ORDER BY c.created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_evidence(case_id: str) -> List[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM evidence WHERE case_id = ? ORDER BY order_index",
            (case_id,),
        ).fetchall()
    return [
        {
            **dict(row),
            "data": json.loads(row["data_json"]),
        }
        for row in rows
    ]


def evidence_ids(case_id: str) -> set[str]:
    return {row["evidence_id"] for row in get_evidence(case_id)}


def update_case(case_id: str, **fields: Any) -> None:
    unknown = set(fields) - CASE_UPDATE_FIELDS
    if unknown:
        raise ValueError(f"Unsupported case fields: {sorted(unknown)}")
    if not fields:
        return
    init_db()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [now_iso(), case_id]
    with connect() as conn, conn:
        conn.execute(
            f"UPDATE cases SET {assignments}, updated_at = ? WHERE case_id = ?",
            values,
        )


def add_event(
    case_id: str,
    event_type: str,
    data: Dict[str, Any],
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    owns_connection = conn is None
    if owns_connection:
        init_db()
        ctx = connect()
        conn = ctx.__enter__()
    try:
        conn.execute(
            "INSERT INTO case_events (case_id, event_type, timestamp, data_json) VALUES (?, ?, ?, ?)",
            (case_id, event_type, now_iso(), json.dumps(data, ensure_ascii=False)),
        )
        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            ctx.__exit__(None, None, None)


def get_events(case_id: str, after_id: int = 0) -> List[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM case_events WHERE case_id = ? AND id > ? ORDER BY id",
            (case_id, after_id),
        ).fetchall()
    return [
        {
            "event_id": row["id"],
            "case_id": row["case_id"],
            "event_type": row["event_type"],
            "timestamp": row["timestamp"],
            "data": json.loads(row["data_json"]),
        }
        for row in rows
    ]


def add_message(case_id: str, message: Dict[str, Any]) -> int:
    init_db()
    timestamp = message.get("timestamp") or now_iso()
    content = message.get("content") or {}
    evidence_ids = message.get("evidence_ids") or []
    with connect() as conn, conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_messages (
                case_id, agent_id, message_type, timestamp, evidence_ids_json,
                content_json, round, accepted, validation_error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                message.get("agent_id", "unknown"),
                message.get("message_type", "FINDING"),
                timestamp,
                json.dumps(evidence_ids, ensure_ascii=False),
                json.dumps(content, ensure_ascii=False),
                int(message.get("round", 0)),
                1 if message.get("accepted", True) else 0,
                message.get("validation_error"),
                now_iso(),
            ),
        )
        message_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO case_events (case_id, event_type, timestamp, data_json) VALUES (?, ?, ?, ?)",
            (
                case_id,
                "agent_message",
                timestamp,
                json.dumps({"message_id": message_id, **message}, ensure_ascii=False),
            ),
        )
    return message_id


def get_messages(case_id: str) -> List[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_messages WHERE case_id = ? ORDER BY id",
            (case_id,),
        ).fetchall()
    return [
        {
            "message_id": row["id"],
            "case_id": row["case_id"],
            "agent_id": row["agent_id"],
            "message_type": row["message_type"],
            "timestamp": row["timestamp"],
            "evidence_ids": json.loads(row["evidence_ids_json"]),
            "content": json.loads(row["content_json"]),
            "round": row["round"],
            "accepted": bool(row["accepted"]),
            "validation_error": row["validation_error"],
        }
        for row in rows
    ]


def set_verdict(case_id: str, verdict: Dict[str, Any]) -> None:
    update_case(case_id, verdict_json=json.dumps(verdict, ensure_ascii=False))
    add_event(case_id, "verdict", {"verdict": verdict})


def set_decision(case_id: str, decision: Dict[str, Any]) -> None:
    update_case(case_id, decision_json=json.dumps(decision, ensure_ascii=False))
    add_event(case_id, "human_decision", {"decision": decision})


def reset_investigation(case_id: str) -> None:
    """Clear prior collaboration and verdict state before a re-run."""
    init_db()
    with connect() as conn, conn:
        conn.execute(
            """
            UPDATE cases
            SET status = 'received', stage = 'received', verdict_json = NULL,
                decision_json = NULL, error = NULL, agent_rounds = 0,
                token_usage_json = NULL, started_at = NULL, finished_at = NULL,
                updated_at = ?
            WHERE case_id = ?
            """,
            (now_iso(), case_id),
        )
        conn.execute("DELETE FROM agent_messages WHERE case_id = ?", (case_id,))
        conn.execute("DELETE FROM case_events WHERE case_id = ?", (case_id,))


def delete_all_cases() -> None:
    """Test helper only."""
    init_db()
    with connect() as conn, conn:
        conn.execute("DELETE FROM cases")
