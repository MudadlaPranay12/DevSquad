"""LocalRunner transport — real OpenCode-backed agents, no Switch required."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .. import storage
from ..correlation import correlate
from ..orchestrator import run_local_investigation
from .base import Transport, TransportError


class LocalTransport(Transport):
    name = "local"

    async def submit_case(self, case_id: str) -> Dict[str, Any]:
        case = storage.get_case(case_id)
        if not case:
            raise TransportError(f"Unknown case {case_id}")
        if not case.get("timeline"):
            timeline = correlate(case["bundle"])
            storage.update_case(case_id, timeline_json=json.dumps(timeline, ensure_ascii=False))
        await run_local_investigation(case_id)
        status = storage.get_case(case_id)
        if not status:
            raise TransportError(f"Case {case_id} disappeared during investigation")
        if status["status"] in {"failed", "timed_out"}:
            raise TransportError(status.get("error") or "Investigation failed")
        return {
            "status": status["status"],
            "case_id": case_id,
            "transport": self.name,
            "verdict_available": status["verdict"] is not None,
        }

    async def get_events(self, case_id: str) -> List[Dict[str, Any]]:
        # storage.add_message already writes an agent_message case event, so this
        # is the complete ordered event stream without duplicates.
        return storage.get_events(case_id)

    async def get_verdict(self, case_id: str) -> Optional[Dict[str, Any]]:
        case = storage.get_case(case_id)
        return case["verdict"] if case else None
