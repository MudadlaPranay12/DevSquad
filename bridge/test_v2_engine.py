"""
DEV-SQUAD — v0.1/v0.2 engine tests.

These tests cover schema v2, v1 migration, redaction, deterministic correlation,
SQLite persistence, API security, and the complete four-agent workflow using a
test-only fake model runner. The product itself never uses fake agent findings.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from bridge import case_manager, orchestrator, storage
from bridge.bridge import app
from bridge.correlation import correlate
from bridge.migration import migrate_v1_to_v2
from bridge.opencode_runner import RunnerResult
from bridge.redact import redact_bundle
from bridge.validator import validate_bundle


def auth_bundle() -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "case_id": "DS-101",
        "timestamp": "2026-11-06T10:00:01Z",
        "capture_source": "devtools-extension",
        "page_url": "http://localhost:3001/",
        "incident_description": "Sign in never completes.",
        "evidence": [
            {
                "id": "CON-001",
                "source": "console",
                "type": "console_error",
                "timestamp": "2026-11-06T10:00:00.100Z",
                "level": "error",
                "message": "Authentication initialization failed",
                "location": {"url": "http://localhost:3001/app.js", "line": 23},
            },
            {
                "id": "APP-001",
                "source": "application",
                "type": "app_observation",
                "timestamp": "2026-11-06T10:00:00.150Z",
                "selector": "document.cookie",
                "observation": "Session cookie absent",
            },
            {
                "id": "NET-001",
                "source": "network",
                "type": "network_response",
                "timestamp": "2026-11-06T10:00:00.180Z",
                "method": "GET",
                "url": "http://localhost:3001/api/user",
                "status": 401,
            },
            {
                "id": "APP-002",
                "source": "application",
                "type": "app_observation",
                "timestamp": "2026-11-06T10:00:00.200Z",
                "selector": "#loginBtn",
                "observation": "Login button disabled: true; loading text visible",
            },
            {
                "id": "NET-002",
                "source": "network",
                "type": "network_response",
                "timestamp": "2026-11-06T10:00:00.250Z",
                "method": "GET",
                "url": "http://localhost:3001/favicon.ico",
                "status": 404,
            },
        ],
        "warnings": [],
    }


def spinner_bundle() -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "case_id": "DS-102",
        "timestamp": "2026-11-06T10:05:01Z",
        "capture_source": "devtools-extension",
        "page_url": "http://localhost:3002/",
        "incident_description": "The page keeps loading.",
        "evidence": [
            {
                "id": "APP-001",
                "source": "application",
                "type": "app_observation",
                "timestamp": "2026-11-06T10:05:00.100Z",
                "selector": ".spinner",
                "observation": "Loading spinner visible: true; status text: Loading application…",
            },
            {
                "id": "NET-001",
                "source": "network",
                "type": "network_response",
                "timestamp": "2026-11-06T10:05:00.150Z",
                "method": "GET",
                "url": "http://localhost:3002/",
                "status": 200,
            },
        ],
        "warnings": [
            "Insufficient evidence: no console errors, no failed network responses.",
        ],
    }


class FakeRunner:
    """Test-only deterministic model stand-in; never used by the product."""

    def run(self, prompt: str, *, title: str = "") -> RunnerResult:
        lower = title.lower()
        if "planning" in lower:
            tasks: List[Dict[str, Any]] = []
            if "CON-001" in prompt:
                tasks.append({"agent_id": "console-agent", "focus": "Explain the console failure.", "evidence_ids": ["CON-001"]})
            if "NET-001" in prompt:
                tasks.append({"agent_id": "network-agent", "focus": "Interpret the HTTP status.", "evidence_ids": ["NET-001"]})
            if "APP-001" in prompt:
                tasks.append({"agent_id": "application-agent", "focus": "Describe the observed UI state.", "evidence_ids": ["APP-001"]})
            return RunnerResult(json.dumps({"tasks": tasks, "notes": "test plan"}), 1)

        if "challenge" in lower:
            if "console-agent" in prompt and "network-agent" in prompt:
                return RunnerResult(json.dumps({
                    "challenges": [{
                        "agent_id": "network-agent",
                        "question": "Does the 401 establish the root cause, or only a downstream symptom?",
                        "evidence_ids": ["NET-001"],
                    }],
                    "unresolved": [],
                }), 1)
            return RunnerResult(json.dumps({"challenges": [], "unresolved": []}), 1)

        if "revision" in lower:
            return RunnerResult(json.dumps({
                "message_type": "FINDING",
                "summary": "401 is a downstream rejection, not proof of the initialization failure.",
                "claims": [{
                    "claim": "GET /api/user returned 401 after the console failure.",
                    "evidence_ids": ["NET-001"],
                    "direct": True,
                }],
                "needed": "",
            }), 1)

        if "verdict" in lower:
            if "CON-001" in prompt:
                return RunnerResult(json.dumps({
                    "root_cause": "Authentication initialization failed, so the session was absent and /api/user returned 401.",
                    "root_cause_determined": True,
                    "summary": "A runtime auth initialization failure precedes a missing cookie and a 401 response.",
                    "supporting_evidence": ["CON-001", "NET-001", "APP-001"],
                    "failure_chain": [
                        {"step": "Authentication initialization failed", "evidence_ids": ["CON-001"]},
                        {"step": "No session cookie was observed", "evidence_ids": ["APP-001"]},
                        {"step": "/api/user returned 401", "evidence_ids": ["NET-001"]},
                        {"step": "Login button remained disabled", "evidence_ids": ["APP-002"]},
                    ],
                    "rejected_hypotheses": [{
                        "hypothesis": "The favicon 404 caused the login failure",
                        "reason": "It is an unrelated static asset response.",
                        "evidence_ids": ["NET-002"],
                    }],
                    "suggested_next_action": "Inspect auth initialization and session issuance.",
                    "missing_evidence": [],
                    "reported_confidence": "High",
                }), 1)
            return RunnerResult(json.dumps({
                "root_cause": "The spinner is stuck because the application never finishes loading.",
                "root_cause_determined": True,
                "summary": "A spinner is visible, but no failure is captured.",
                "supporting_evidence": ["APP-001"],
                "failure_chain": [{"step": "Spinner visible", "evidence_ids": ["APP-001"]}],
                "rejected_hypotheses": [],
                "suggested_next_action": "Capture additional evidence.",
                "missing_evidence": ["A failed request or runtime exception"],
                "reported_confidence": "High",
            }), 1)

        if "console agent" in lower:
            return RunnerResult(json.dumps({
                "message_type": "FINDING",
                "summary": "A console error reports auth initialization failure.",
                "claims": [{"claim": "Authentication initialization failed", "evidence_ids": ["CON-001"], "direct": True}],
                "needed": "",
            }), 1)

        if "network agent" in lower:
            return RunnerResult(json.dumps({
                "message_type": "FINDING",
                "summary": "The user request returns 401.",
                "claims": [{"claim": "GET /api/user returned HTTP 401", "evidence_ids": ["NET-001"], "direct": True}],
                "needed": "",
            }), 1)

        if "application agent" in lower:
            evidence_id = "APP-001" if "APP-001" in prompt else "APP-001"
            return RunnerResult(json.dumps({
                "message_type": "FINDING",
                "summary": "The page shows a loading state with no session cookie.",
                "claims": [{"claim": "A loading or missing-session state was observed", "evidence_ids": [evidence_id], "direct": True}],
                "needed": "",
            }), 1)

        return RunnerResult(json.dumps({"error": "unknown test prompt"}), 1)


# ---------------------------------------------------------------------------
# Schema and migration
# ---------------------------------------------------------------------------


def test_v2_bundle_validates():
    valid, errors = validate_bundle(auth_bundle())
    assert valid, errors


def test_v2_duplicate_ids_rejected():
    bundle = auth_bundle()
    bundle["evidence"][1]["id"] = "CON-001"
    bundle["evidence"][1]["source"] = "console"
    valid, errors = validate_bundle(bundle)
    assert not valid
    assert any("Duplicate evidence id" in error for error in errors)


def test_v2_source_prefix_mismatch_rejected():
    bundle = auth_bundle()
    bundle["evidence"][0]["source"] = "network"
    valid, errors = validate_bundle(bundle)
    assert not valid
    assert any("expected 'console'" in error for error in errors)


def test_v1_migration_preserves_evidence_and_rewrites_references():
    v1 = {
        "case_id": "DS-001",
        "timestamp": "2026-11-04T16:19:10Z",
        "source": "playwright",
        "page_url": "http://localhost:3001/",
        "evidence": [
            {
                "id": "E001",
                "type": "network_response",
                "timestamp": "2026-11-04T16:19:08Z",
                "url": "http://localhost:3001/api/user",
                "method": "GET",
                "status": 401,
                "headers": {"content-type": "application/json"},
            },
            {
                "id": "E002",
                "type": "console_error",
                "timestamp": "2026-11-04T16:19:08Z",
                "message": "Request E001 was rejected",
            },
        ],
        "warnings": [],
    }
    valid, errors = validate_bundle(v1)
    assert valid, errors
    migrated, mapping = migrate_v1_to_v2(v1)
    assert mapping == {"E001": "NET-001", "E002": "CON-001"}
    assert migrated["schema_version"] == 2
    assert migrated["capture_source"] == "playwright"
    assert len(migrated["evidence"]) == 2
    assert migrated["evidence"][0]["legacy_id"] == "E001"
    assert migrated["evidence"][0]["headers"] == {"content-type": "application/json"}
    assert migrated["evidence"][1]["message"] == "Request NET-001 was rejected"
    assert migrated["legacy_id_map"] == mapping
    valid_v2, errors_v2 = validate_bundle(migrated)
    assert valid_v2, errors_v2


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_redaction_removes_secrets_but_keeps_ids_and_metadata():
    bundle = auth_bundle()
    bundle["page_url"] = "http://localhost:3001/?token=secret-query"
    bundle["evidence"][2]["headers"] = {
        "authorization": "Bearer abc.def.ghi",
        "cookie": "session=super-secret-cookie",
        "content-type": "application/json",
    }
    bundle["evidence"][2]["url"] = "http://localhost:3001/api/user?api_key=secret-api-key"
    bundle["evidence"].append({
        "id": "APP-003",
        "source": "application",
        "type": "storage_observation",
        "timestamp": "2026-11-06T10:00:00.300Z",
        "localStorage": {"authToken": "super-secret-storage-value"},
        "cookie_name": "session",
    })
    redacted = redact_bundle(bundle)
    serialized = json.dumps(redacted)
    assert redacted["evidence"][2]["id"] == "NET-001"
    assert redacted["evidence"][2]["headers"]["authorization"] == "[REDACTED]"
    assert redacted["evidence"][2]["headers"]["cookie"] == "[REDACTED]"
    assert "secret-api-key" not in serialized
    assert "super-secret-cookie" not in serialized
    assert "super-secret-storage-value" not in serialized
    assert redacted["evidence"][-1]["localStorage"] == {"authToken": "[REDACTED]"}
    assert redacted["evidence"][-1]["cookie_name"] == "session"
    assert redacted["redaction_applied"] is True


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------


def test_timeline_is_deterministic_and_marks_uncertainty():
    bundle = auth_bundle()
    bundle["evidence"][1]["timestamp"] = None
    bundle["evidence"][1]["timestamp_missing"] = True
    first = correlate(bundle)
    second = correlate(copy.deepcopy(bundle))
    assert first["timeline_text"] == second["timeline_text"]
    assert first["first_error_id"] == "CON-001"
    assert any(event["ordering"] == "sequence_only" for event in first["events"])
    timed = [event for event in first["events"] if event["relative_ms"] is not None]
    assert [event["relative_ms"] for event in timed] == sorted(event["relative_ms"] for event in timed)
    assert all(rel["causal"] is False for rel in first["relationships"])
    assert "CON-001" in first["timeline_text"]


def test_timeline_detects_insufficient_evidence():
    result = correlate(spinner_bundle())
    assert result["insufficient_evidence"] is True
    assert result["first_error_id"] is None
    assert "APP-001" in result["timeline_text"]


# ---------------------------------------------------------------------------
# Storage and API
# ---------------------------------------------------------------------------


def test_sqlite_case_persistence_and_human_decision():
    result = case_manager.ingest_bundle(auth_bundle())
    case_id = result["case_id"]
    case = storage.get_case(case_id)
    assert case is not None
    assert len(storage.get_evidence(case_id)) == 5
    assert case["timeline"]["first_error_id"] == "CON-001"

    storage.update_case(case_id, status="completed", stage="completed")
    storage.set_verdict(case_id, {"root_cause": "Auth failure", "confidence": "Medium"})
    decision = case_manager.record_decision(case_id, "approve", "Looks right.")
    assert decision["decision"] == "approve"
    reloaded = storage.get_case(case_id)
    assert reloaded["decision"]["note"] == "Looks right."
    assert storage.get_events(case_id)


def test_api_requires_pairing_token():
    client = TestClient(app)
    response = client.get("/cases")
    assert response.status_code == 401
    response = client.get("/cases", headers={"X-DevSquad-Token": os.environ["DEV_SQUAD_TOKEN"]})
    assert response.status_code == 200


def test_api_rejects_foreign_host_and_origin():
    client = TestClient(app)
    headers = {"X-DevSquad-Token": os.environ["DEV_SQUAD_TOKEN"]}
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/cases", headers={**headers, "Origin": "https://evil.example"}).status_code == 403


def test_decision_requires_a_verdict():
    case_manager.ingest_bundle(auth_bundle())
    client = TestClient(app)
    client.headers.update({"X-DevSquad-Token": os.environ["DEV_SQUAD_TOKEN"]})
    response = client.post("/cases/DS-101/decision", json={"decision": "approve", "note": ""})
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Four-agent workflow (fake runner is test-only)
# ---------------------------------------------------------------------------


def test_four_agent_workflow_auth_failure(monkeypatch):
    monkeypatch.setattr(orchestrator, "OpenCodeRunner", lambda: FakeRunner())
    case_manager.ingest_bundle(auth_bundle())
    verdict = asyncio.run(orchestrator.run_local_investigation("DS-101"))

    case = storage.get_case("DS-101")
    assert case["status"] == "completed"
    messages = storage.get_messages("DS-101")
    message_types = {message["message_type"] for message in messages}
    assert {"TASK", "FINDING", "CHALLENGE", "REVISE", "VERDICT"} <= message_types
    assert case["agent_rounds"] == 2
    assert verdict["root_cause_determined"] is True
    assert verdict["confidence"] == "Medium"
    assert verdict["confidence_method"] == "rule-derived-v1"
    evidence_ids = {
        item["id"] for item in storage.get_case("DS-101")["bundle"]["evidence"]
    }
    assert set(verdict["supporting_evidence"]) <= evidence_ids
    for message in messages:
        for evidence_id in message["evidence_ids"]:
            assert evidence_id in evidence_ids
    assert any(
        message["message_type"] == "VERDICT" and message["accepted"]
        for message in messages
    )


def test_insufficient_evidence_workflow_never_invents_cause(monkeypatch):
    monkeypatch.setattr(orchestrator, "OpenCodeRunner", lambda: FakeRunner())
    case_manager.ingest_bundle(spinner_bundle())
    verdict = asyncio.run(orchestrator.run_local_investigation("DS-102"))

    assert verdict["root_cause"] == "Not determined"
    assert verdict["root_cause_determined"] is False
    assert verdict["confidence"] == "Low"
    assert verdict["insufficient_evidence_override"] is True
    assert verdict["missing_evidence"]
    assert storage.get_case("DS-102")["status"] == "completed"

def test_capture_endpoints_require_token_and_local_targets():
    client = TestClient(app)
    body = {
        "url": "http://example.com/",
        "case_id": "DS-201",
        "schema_version": 2,
    }
    assert client.post("/capture/preview", json=body).status_code == 401
    headers = {"X-DevSquad-Token": os.environ["DEV_SQUAD_TOKEN"]}
    response = client.post("/capture/preview", json=body, headers=headers)
    assert response.status_code == 400
    assert "localhost" in response.json()["detail"]

    body["url"] = "file:///etc/passwd"
    response = client.post("/capture/preview", json=body, headers=headers)
    assert response.status_code == 400
    assert "http or https" in response.json()["detail"]

def test_same_timestamp_ties_keep_ordering_verified():
    bundle = auth_bundle()
    for item in bundle["evidence"]:
        if item["id"] in {"CON-001", "APP-001"}:
            item["timestamp"] = "2026-11-06T10:00:00.100Z"
    timeline = correlate(bundle)
    assert timeline["coverage"]["ordering_verified"] is True
    assert set(timeline["coverage"]["same_timestamp_events"]) == {"CON-001", "APP-001"}
