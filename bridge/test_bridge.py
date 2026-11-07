"""
DEV-SQUAD — Bridge tests (test_bridge.py)

Covers:
  1. Valid auth-failure bundle is accepted.
  2. Valid stuck-spinner bundle is accepted.
  3. Invalid JSON structure is rejected.
  4. Authorization headers are redacted.
  5. JWT-like tokens are redacted.
  6. Password fields are redacted.
  7. Sensitive URL query parameters are redacted.
  8. Evidence IDs are preserved.
  9. Saved bundles remain schema-valid.
  10. Health endpoint works.

Run from E:\DevSquad:
    pytest bridge/test_bridge.py -v
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from bridge.bridge import app, BUNDLES_DIR, generate_case_id
from bridge.validator import validate_bundle
from bridge.redact import redact_bundle

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """FastAPI test client with the local pairing token."""
    test_client = TestClient(app)
    test_client.headers.update({"X-DevSquad-Token": os.environ["DEV_SQUAD_TOKEN"]})
    return test_client


@pytest.fixture
def clean_bundles(tmp_path, monkeypatch):
    """Point BUNDLES_DIR at a temp directory and restore after the test."""
    original = BUNDLES_DIR
    tmp_bundles = tmp_path / "bundles"
    tmp_bundles.mkdir(parents=True, exist_ok=True)

    # Monkeypatch the module-level constant used by bridge.py.
    import bridge.bridge as bridge_mod

    bridge_mod.BUNDLES_DIR = tmp_bundles
    yield tmp_bundles
    bridge_mod.BUNDLES_DIR = original


# ---------------------------------------------------------------------------
# Test bundles
# ---------------------------------------------------------------------------

AUTH_FAILURE_BUNDLE: Dict[str, Any] = {
    "case_id": "DS-001",
    "timestamp": "2026-11-04T16:19:10Z",
    "source": "playwright",
    "page_url": "http://localhost:3001/",
    "evidence": [
        {
            "id": "E001",
            "type": "network_request",
            "timestamp": "2026-11-04T16:19:08Z",
            "url": "http://localhost:3001/",
            "method": "GET",
            "headers": {
                "user-agent": "Mozilla/5.0",
                "authorization": "Bearer secret-token-123",
            },
        },
        {
            "id": "E002",
            "type": "network_response",
            "timestamp": "2026-11-04T16:19:08Z",
            "url": "http://localhost:3001/api/user",
            "method": "GET",
            "status": 401,
            "headers": {
                "content-type": "application/json",
            },
        },
        {
            "id": "E003",
            "type": "console_error",
            "timestamp": "2026-11-04T16:19:08Z",
            "level": "error",
            "message": "Authentication initialization failed",
            "location": {"url": "http://localhost:3001/app.js", "line": 23},
        },
    ],
    "redaction_applied": True,
    "warnings": [],
}

STUCK_SPINNER_BUNDLE: Dict[str, Any] = {
    "case_id": "DS-002",
    "timestamp": "2026-11-04T16:19:38Z",
    "source": "playwright",
    "page_url": "http://localhost:3002/",
    "evidence": [
        {
            "id": "E001",
            "type": "network_request",
            "timestamp": "2026-11-04T16:19:35Z",
            "url": "http://localhost:3002/",
            "method": "GET",
            "headers": {"user-agent": "Mozilla/5.0"},
        },
        {
            "id": "E002",
            "type": "network_response",
            "timestamp": "2026-11-04T16:19:35Z",
            "url": "http://localhost:3002/",
            "method": "GET",
            "status": 200,
            "headers": {"content-type": "text/html"},
        },
    ],
    "redaction_applied": True,
    "warnings": [
        "Insufficient evidence: no console errors, no failed network responses.",
    ],
}

INVALID_BUNDLE: Dict[str, Any] = {
    "case_id": "not-a-valid-case-id",
    "timestamp": "not-a-timestamp",
    "source": "unknown",
    "evidence": "not-a-list",
}

SENSITIVE_BUNDLE: Dict[str, Any] = {
    "case_id": "DS-010",
    "timestamp": "2026-11-04T17:00:00Z",
    "source": "playwright",
    "page_url": "http://localhost:3001/api/user?token=abc123&api_key=supersecret",
    "evidence": [
        {
            "id": "E001",
            "type": "network_request",
            "timestamp": "2026-11-04T17:00:00Z",
            "url": "http://localhost:3001/login?token=abc123&api_key=supersecret",
            "method": "POST",
            "headers": {
                "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sig",
                "cookie": "session=abc123",
            },
        },
        {
            "id": "E002",
            "type": "console_error",
            "timestamp": "2026-11-04T17:00:00Z",
            "level": "error",
            "message": "Login failed for user@example.com with password hunter2",
        },
    ],
    "redaction_applied": True,
    "warnings": [],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_ok(self, client, clean_bundles):
        """Test 10: Health endpoint works."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "devsquad-evidence-bridge"


class TestAcceptValidBundles:
    def test_auth_failure_bundle_accepted(self, client, clean_bundles):
        """Test 1: Valid auth-failure bundle is accepted."""
        response = client.post("/cases", json=AUTH_FAILURE_BUNDLE)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "accepted"
        assert data["case_id"] == "DS-001"
        assert data["evidence_count"] == 3
        assert data["redaction_applied"] is True

    def test_stuck_spinner_bundle_accepted(self, client, clean_bundles):
        """Test 2: Valid stuck-spinner bundle is accepted."""
        response = client.post("/cases", json=STUCK_SPINNER_BUNDLE)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "accepted"
        assert data["case_id"] == "DS-002"


class TestRejectInvalid:
    def test_invalid_bundle_rejected(self, client, clean_bundles):
        """Test 3: Invalid JSON structure is rejected."""
        response = client.post("/cases", json=INVALID_BUNDLE)
        assert response.status_code == 400, response.text
        data = response.json()
        assert "detail" in data
        assert "error" in data["detail"]
        assert "validation_errors" in data["detail"]
        assert len(data["detail"]["validation_errors"]) > 0


class TestRedaction:
    def test_authorization_headers_redacted(self, client, clean_bundles):
        """Test 4: Authorization headers are redacted."""
        response = client.post("/cases", json=AUTH_FAILURE_BUNDLE)
        assert response.status_code == 200
        # Fetch the saved bundle and check headers.
        case_id = response.json()["case_id"]
        get_resp = client.get(f"/cases/{case_id}")
        assert get_resp.status_code == 200
        saved = get_resp.json()
        for item in saved["evidence"]:
            if item.get("type") == "network_request":
                headers = item.get("headers", {})
                assert headers.get("authorization") == "[REDACTED]"

    def test_jwt_tokens_redacted(self, client, clean_bundles):
        """Test 5: JWT-like tokens are redacted."""
        response = client.post("/cases", json=SENSITIVE_BUNDLE)
        assert response.status_code == 200
        case_id = response.json()["case_id"]
        get_resp = client.get(f"/cases/{case_id}")
        saved = get_resp.json()
        for item in saved["evidence"]:
            headers = item.get("headers", {})
            if "authorization" not in headers:
                continue
            auth_val = headers.get("authorization", "")
            # Authorization header is fully redacted since it is in REDACTED_HEADERS.
            assert "eyJ" not in auth_val, f"JWT not redacted: {auth_val}"
            assert auth_val == "[REDACTED]" or "[REDACTED_JWT]" in auth_val

    def test_password_fields_redacted(self, client, clean_bundles):
        """Test 6: Password fields are redacted."""
        response = client.post("/cases", json=SENSITIVE_BUNDLE)
        assert response.status_code == 200
        case_id = response.json()["case_id"]
        get_resp = client.get(f"/cases/{case_id}")
        saved = get_resp.json()
        for item in saved["evidence"]:
            msg = item.get("message", "")
            assert "hunter2" not in msg, f"Password not redacted: {msg}"

    def test_sensitive_url_query_params_redacted(self, client, clean_bundles):
        """Test 7: Sensitive URL query parameters are redacted."""
        response = client.post("/cases", json=SENSITIVE_BUNDLE)
        assert response.status_code == 200
        case_id = response.json()["case_id"]
        get_resp = client.get(f"/cases/{case_id}")
        saved = get_resp.json()
        for item in saved["evidence"]:
            url = item.get("url", "")
            assert "supersecret" not in url, f"API key not redacted in URL: {url}"
            assert "abc123" not in url, f"Token not redacted in URL: {url}"

    def test_evidence_ids_preserved(self, client, clean_bundles):
        """Test 8: Legacy v1 IDs survive migration in legacy_id."""
        response = client.post("/cases", json=AUTH_FAILURE_BUNDLE)
        assert response.status_code == 200
        case_id = response.json()["case_id"]
        get_resp = client.get(f"/cases/{case_id}")
        saved = get_resp.json()
        ids = [item["id"] for item in saved["evidence"]]
        legacy_ids = [item.get("legacy_id") for item in saved["evidence"]]
        assert "E001" in legacy_ids
        assert "E002" in legacy_ids
        assert "E003" in legacy_ids
        assert all(
            evidence_id.startswith(("CON-", "NET-", "APP-"))
            for evidence_id in ids
        )
        assert saved["legacy_id_map"] == {
            "E001": "NET-001",
            "E002": "NET-002",
            "E003": "CON-001",
        }

    def test_saved_bundles_remain_schema_valid(self, client, clean_bundles):
        """Test 9: Saved bundles remain schema-valid."""
        response = client.post("/cases", json=AUTH_FAILURE_BUNDLE)
        assert response.status_code == 200
        case_id = response.json()["case_id"]
        path = BUNDLES_DIR / f"{case_id}.json"
        if not path.exists():
            # bridge.py may have been monkeypatched to a temp dir.
            import bridge.bridge as bridge_mod
            path = bridge_mod.BUNDLES_DIR / f"{case_id}.json"
        with path.open("r", encoding="utf-8") as f:
            saved = json.load(f)
        is_valid, errors = validate_bundle(saved)
        assert is_valid, f"Saved bundle is not schema-valid: {errors}"


class TestListAndGet:
    def test_list_cases_returns_metadata(self, client, clean_bundles):
        """GET /cases returns list of saved cases."""
        client.post("/cases", json=AUTH_FAILURE_BUNDLE)
        client.post("/cases", json=STUCK_SPINNER_BUNDLE)

        response = client.get("/cases")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        case_ids = [c["case_id"] for c in data["cases"]]
        assert "DS-001" in case_ids
        assert "DS-002" in case_ids

    def test_get_case_returns_bundle(self, client, clean_bundles):
        """GET /cases/{case_id} returns the sanitized bundle."""
        client.post("/cases", json=AUTH_FAILURE_BUNDLE)
        response = client.get("/cases/DS-001")
        assert response.status_code == 200
        data = response.json()
        assert data["case_id"] == "DS-001"
        assert len(data["evidence"]) == 3

    def test_get_case_not_found(self, client, clean_bundles):
        """GET /cases/{case_id} returns 404 for missing case."""
        response = client.get("/cases/DS-999")
        assert response.status_code == 404
