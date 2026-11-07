"""
DEV-SQUAD — Python Evidence Bridge (bridge.py)

FastAPI service that accepts v1 or v2 evidence bundles, validates them, applies
second-stage redaction, migrates v1 IDs to source-prefixed v2 IDs, correlates a
deterministic timeline, stores cases in SQLite, and runs real AI investigations.

Run (localhost only):
    python -m bridge

The service binds to 127.0.0.1. Mutating case endpoints require the local
pairing token printed by `python -m bridge --token`.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Literal

from . import case_manager, storage
from .case_manager import generate_case_id  # re-export for existing callers
from .config import (
    BUNDLES_DIR as CONFIG_BUNDLES_DIR,
    PROJECT_ROOT,
    agent_model,
    allowed_origins,
    ensure_pairing_token,
    require_pairing_token,
    transport_mode,
)
from .redact import redact_bundle
from .transport import (
    LocalTransport,
    SwitchTransport,
    TransportError,
    get_transport,
    switch_configured,
)

LOGGER = logging.getLogger(__name__)
BUNDLES_DIR = CONFIG_BUNDLES_DIR
CASE_ID_PATTERN = re.compile(r"^DS-\d{3}$")
ALLOWED_HOST_PATTERN = re.compile(r"^(127\.0\.0\.1|localhost|testserver)(:\d+)?$")
SERVICE_VERSION = "0.3.0"
CAPTURE_SCRIPT = PROJECT_ROOT / "capture" / "capture.py"
CAPTURE_TIMEOUT_SECONDS = 120
LOCAL_CAPTURE_HOSTS = {"127.0.0.1", "localhost", "::1"}

app = FastAPI(
    title="DEV-SQUAD Evidence Bridge",
    version=SERVICE_VERSION,
    description="Local evidence engine and collaborative AI investigation bridge.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-DevSquad-Token"],
    allow_credentials=False,
    max_age=600,
)


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "need_more_evidence"]
    note: str = Field(default="", max_length=2000)


class CaptureRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000)
    case_id: str = Field(..., pattern=r"^DS-\d{3}$")
    schema_version: Literal[1, 2] = 2
    click: Optional[str] = Field(default=None, max_length=200)
    incident_description: Optional[str] = Field(default=None, max_length=4000)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_case_id(case_id: str) -> bool:
    return bool(CASE_ID_PATTERN.match(case_id))


def _require_case(case_id: str) -> Dict[str, Any]:
    if not _valid_case_id(case_id):
        raise HTTPException(status_code=400, detail="Invalid case ID format. Expected DS-###.")
    case = storage.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found.")
    return case


def require_token(
    x_devsquad_token: Optional[str] = Header(default=None, alias="X-DevSquad-Token"),
) -> None:
    """Validate the local pairing token on every case endpoint."""
    if not require_pairing_token():
        return
    expected = ensure_pairing_token()
    if not x_devsquad_token or not secrets.compare_digest(x_devsquad_token, expected):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Invalid or missing DEV-SQUAD pairing token.",
                "hint": "Copy the token from bridge/.devsquad_token into the extension settings.",
            },
        )


@app.middleware("http")
async def localhost_security(request: Request, call_next):
    """Reject non-local Host headers and unknown browser Origins."""
    host = request.headers.get("host", "")
    if host and not ALLOWED_HOST_PATTERN.match(host.lower()):
        return JSONResponse(
            status_code=400,
            content={"detail": f"Host header {host!r} is not allowed. Bind the bridge to 127.0.0.1."},
        )

    origin = request.headers.get("origin")
    if origin:
        extension_origin = origin.startswith("chrome-extension://") and not origin.endswith("/")
        if not extension_origin and origin not in allowed_origins():
            return JSONResponse(
                status_code=403,
                content={"detail": f"Origin {origin!r} is not allowed."},
            )

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/cases"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.on_event("startup")
def startup() -> None:
    storage.init_db()


def save_bundle(case_id: str, bundle: Dict[str, Any]) -> Path:
    """Save the redacted v2 bundle to the module-level bundles directory."""
    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    path = BUNDLES_DIR / f"{case_id}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(bundle, handle, indent=2, ensure_ascii=False)
    return path


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "devsquad-evidence-bridge",
        "version": SERVICE_VERSION,
        "schema_versions": [1, 2],
        "transport": transport_mode(),
        "model": agent_model(),
        "switch_configured": switch_configured(),
        "token_required": require_pairing_token(),
        "timestamp": now_iso(),
    }


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def _accept_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest one bundle and return the same response shape for all entry points."""
    try:
        result = case_manager.ingest_bundle(bundle, transport=transport_mode())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid evidence bundle",
                "validation_errors": [str(exc)],
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 - return a structured local error
        LOGGER.exception("Unexpected ingestion failure")
        raise HTTPException(
            status_code=500,
            detail={"error": "Evidence ingestion failed", "validation_errors": [str(exc)]},
        ) from exc

    case = storage.get_case(result["case_id"])
    if not case:
        raise HTTPException(status_code=500, detail="Case was accepted but could not be read back.")
    path = save_bundle(result["case_id"], case["bundle"])

    return {
        "status": "accepted",
        "case_id": result["case_id"],
        "file": path.name,
        "schema_version": result["schema_version"],
        "source_schema_version": result["source_schema_version"],
        "migrated": result["migrated"],
        "evidence_count": result["evidence_count"],
        "redaction_applied": result["redaction_applied"],
        "warnings": result["warnings"],
        "timeline_preview": result["timeline"].get("timeline_text", "").splitlines()[:20],
        "message": (
            "Case accepted and stored in SQLite. "
            f"Start an investigation with POST /cases/{result['case_id']}/investigate."
        ),
    }


@app.post("/cases", dependencies=[Depends(require_token)])
def create_case(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Accept, migrate, redact, correlate and persist an evidence bundle."""
    return _accept_bundle(bundle)


# ---------------------------------------------------------------------------
# Capture (server-side Playwright, invoked by the DevTools extension)
# ---------------------------------------------------------------------------


def _validate_capture_target(url: str) -> str:
    """Only allow the local demo applications to be captured."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Capture URL must use http or https.")
    if parsed.hostname not in LOCAL_CAPTURE_HOSTS:
        raise HTTPException(
            status_code=400,
            detail="Capture is restricted to localhost / 127.0.0.1 demo applications.",
        )
    return url


def _run_capture(request: CaptureRequest) -> Dict[str, Any]:
    """Run the Playwright collector as a subprocess and return its bundle."""
    _validate_capture_target(request.url)
    if not CAPTURE_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="Capture collector is not installed.")

    with tempfile.TemporaryDirectory(prefix="devsquad-capture-") as tmp_dir:
        out_path = Path(tmp_dir) / "bundle.json"
        command = [
            sys.executable,
            str(CAPTURE_SCRIPT),
            "--url",
            request.url,
            "--case-id",
            request.case_id,
            "--out",
            str(out_path),
            "--schema-version",
            str(request.schema_version),
        ]
        if request.click:
            command.extend(["--click", request.click])
        if request.incident_description and request.schema_version == 2:
            command.extend(["--incident-description", request.incident_description])

        try:
            completed = subprocess.run(
                command,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=CAPTURE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                status_code=504,
                detail=f"Capture timed out after {CAPTURE_TIMEOUT_SECONDS} seconds.",
            ) from exc

        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip()[-1500:]
            raise HTTPException(
                status_code=500,
                detail={"error": "Capture failed.", "output": tail},
            )

        try:
            return json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500,
                detail={"error": "Capture produced an unreadable bundle.", "output": str(exc)},
            ) from exc


@app.post("/capture/preview", dependencies=[Depends(require_token)])
def capture_preview(request: CaptureRequest) -> Dict[str, Any]:
    """Capture evidence and return a redacted preview without storing a case."""
    bundle = _run_capture(request)
    preview = redact_bundle(bundle)
    evidence = preview.get("evidence") or []
    return {
        "status": "preview",
        "case_id": preview.get("case_id"),
        "schema_version": preview.get("schema_version", 1),
        "evidence_count": len(evidence),
        "warnings": preview.get("warnings") or [],
        "redaction_applied": bool(preview.get("redaction_applied")),
        "bundle": preview,
        "note": "Review this redacted preview, then submit it to store the case.",
    }


@app.post("/capture", dependencies=[Depends(require_token)])
def capture_and_submit(request: CaptureRequest) -> Dict[str, Any]:
    """Capture evidence and ingest it in one step."""
    bundle = _run_capture(request)
    return _accept_bundle(bundle)


@app.get("/cases", dependencies=[Depends(require_token)])
def list_cases_endpoint() -> Dict[str, Any]:
    cases = storage.list_cases()
    return {"cases": cases, "count": len(cases), "transport": transport_mode()}


@app.get("/cases/{case_id}", dependencies=[Depends(require_token)])
def get_case_endpoint(case_id: str) -> Dict[str, Any]:
    """Return the redacted, normalized v2 evidence bundle."""
    case = _require_case(case_id)
    return case["bundle"]


@app.get("/cases/{case_id}/detail", dependencies=[Depends(require_token)])
def get_case_detail_endpoint(case_id: str) -> Dict[str, Any]:
    _require_case(case_id)
    detail = case_manager.get_case_detail(case_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found.")
    return detail


@app.get("/cases/{case_id}/timeline", dependencies=[Depends(require_token)])
def get_timeline_endpoint(case_id: str) -> Dict[str, Any]:
    case = _require_case(case_id)
    return case.get("timeline") or {}


# ---------------------------------------------------------------------------
# Investigation
# ---------------------------------------------------------------------------


async def _run_local_background(case_id: str) -> None:
    try:
        await LocalTransport().submit_case(case_id)
    except Exception as exc:  # noqa: BLE001 - background failures must be visible
        LOGGER.exception("Local investigation failed for %s", case_id)
        case = storage.get_case(case_id)
        if case and case.get("status") == "investigating":
            storage.update_case(
                case_id,
                status="failed",
                stage="error",
                finished_at=storage.now_iso(),
                error=str(exc)[:1200],
            )
            storage.add_event(case_id, "status", {
                "status": "failed",
                "stage": "error",
                "message": "Investigation failed.",
                "error": str(exc)[:1200],
            })


async def _run_switch_background(case_id: str) -> None:
    transport = SwitchTransport()
    try:
        result = await transport.submit_case(case_id)
        storage.update_case(case_id, status="investigating", stage="switch_submitted", error=None)
        storage.add_event(case_id, "status", {
            "status": "investigating",
            "stage": "switch_submitted",
            "message": "Case submitted to Switch. Live room ingestion is not enabled in this build.",
            "transport": result,
        })
    except TransportError as exc:
        LOGGER.info(
            "Switch transport unavailable or blocked; running via LocalRunner."
        )
        await _run_local_background(case_id)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Switch submission failed for %s", case_id)
        storage.update_case(
            case_id,
            status="failed",
            stage="switch_error",
            finished_at=storage.now_iso(),
            error=str(exc)[:1200],
        )
        storage.add_event(case_id, "status", {
            "status": "failed",
            "stage": "switch_error",
            "message": "Switch submission failed.",
            "error": str(exc)[:1200],
        })


@app.post("/cases/{case_id}/investigate", dependencies=[Depends(require_token)])
def investigate(case_id: str, background_tasks: BackgroundTasks) -> JSONResponse:
    case = _require_case(case_id)
    if case["status"] == "investigating":
        raise HTTPException(
            status_code=409,
            detail={"error": "An investigation is already running.", "status": case["status"]},
        )

    mode = transport_mode()
    if mode == "switch" and not switch_configured():
        LOGGER.info(
            "Switch transport unavailable or blocked; running via LocalRunner."
        )
        mode = "local"

    storage.reset_investigation(case_id)
    storage.update_case(case_id, status="investigating", stage="queued", transport=mode)
    storage.add_event(case_id, "investigation_requested", {
        "transport": mode,
        "message": "Investigation queued. Poll /status and /events for real progress.",
    })

    if mode == "switch":
        background_tasks.add_task(_run_switch_background, case_id)
        message = "Case queued for Switch submission. Poll status for the confirmed result."
    else:
        background_tasks.add_task(_run_local_background, case_id)
        message = "Investigation queued with LocalRunner. Poll status for real progress."

    return JSONResponse(
        status_code=202,
        content={
            "status": "investigating",
            "stage": "queued",
            "case_id": case_id,
            "transport": mode,
            "message": message,
        },
    )


@app.get("/cases/{case_id}/status", dependencies=[Depends(require_token)])
def get_status_endpoint(case_id: str) -> Dict[str, Any]:
    _require_case(case_id)
    status = case_manager.get_status(case_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found.")
    return status


@app.get("/cases/{case_id}/events", dependencies=[Depends(require_token)])
def get_events_endpoint(
    case_id: str,
    after_id: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    case = _require_case(case_id)
    events = storage.get_events(case_id, after_id=after_id)
    messages = storage.get_messages(case_id)
    return {
        "case_id": case_id,
        "status": case["status"],
        "stage": case["stage"],
        "count": len(events),
        "events": events,
        "messages": messages,
    }


@app.get("/cases/{case_id}/verdict", dependencies=[Depends(require_token)])
def get_verdict_endpoint(case_id: str) -> Dict[str, Any]:
    case = _require_case(case_id)
    if not case.get("verdict"):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "No verdict is available yet.",
                "status": case["status"],
                "stage": case["stage"],
            },
        )
    return {
        "case_id": case_id,
        "status": case["status"],
        "verdict": case["verdict"],
        "decision": case.get("decision"),
        "error": case.get("error"),
    }


@app.post("/cases/{case_id}/decision", dependencies=[Depends(require_token)])
def record_decision_endpoint(case_id: str, request: DecisionRequest) -> Dict[str, Any]:
    _require_case(case_id)
    try:
        record = case_manager.record_decision(case_id, request.decision, request.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "recorded", "case_id": case_id, "decision": record}


@app.get("/", include_in_schema=False)
def root() -> Dict[str, Any]:
    return {
        "service": "devsquad-evidence-bridge",
        "version": SERVICE_VERSION,
        "docs": "/docs",
        "health": "/health",
    }
