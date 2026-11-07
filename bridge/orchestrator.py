"""
DEV-SQUAD — local multi-agent investigation orchestrator.

This is a real orchestration of four model calls (lead + three specialists),
not a scripted conversation. Findings are only accepted when every factual
claim cites an evidence ID that exists in the captured case.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import agents, storage
from .config import investigation_timeout_seconds
from .normalizer import sanitize_untrusted_text
from .opencode_runner import OpenCodeError, OpenCodeRunner, RunnerResult
from .verdict_validator import (
    VerdictValidationError,
    aggregate_findings,
    finalize_verdict,
    insufficient_verdict,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class Metrics:
    calls: List[Dict[str, Any]] = field(default_factory=list)
    failures: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, agent_id: str, stage: str, result: RunnerResult) -> None:
        self.calls.append({
            "agent_id": agent_id,
            "stage": stage,
            "latency_ms": result.latency_ms,
            "session_id": result.session_id,
            "token_usage": result.token_usage,
        })

    def record_failure(self, agent_id: str, stage: str, error: str) -> None:
        self.failures.append({
            "agent_id": agent_id,
            "stage": stage,
            "error": sanitize_untrusted_text(error, 1200),
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "total_calls": len(self.calls),
            "total_latency_ms": sum(int(call.get("latency_ms") or 0) for call in self.calls),
            "token_usage_available": any(call.get("token_usage") for call in self.calls),
        }


def _now() -> str:
    return storage.now_iso()


def _safe(value: Any, limit: int = 2000) -> str:
    return sanitize_untrusted_text(str(value or ""), limit=limit)


def _source_map(bundle: Dict[str, Any]) -> Dict[str, str]:
    return {
        str(item.get("id")): str(item.get("source"))
        for item in (bundle.get("evidence") or [])
        if isinstance(item, dict) and item.get("id")
    }


def _record_message(
    case_id: str,
    agent_id: str,
    message_type: str,
    content: Dict[str, Any],
    evidence_ids: Sequence[str],
    *,
    round_number: int,
    accepted: bool = True,
    validation_error: Optional[str] = None,
) -> int:
    payload = dict(content)
    payload.setdefault("case_id", case_id)
    payload.setdefault("agent_id", agent_id)
    return storage.add_message(case_id, {
        "agent_id": agent_id,
        "message_type": message_type,
        "timestamp": _now(),
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
        "content": payload,
        "round": round_number,
        "accepted": accepted,
        "validation_error": validation_error,
    })


def _status(case_id: str, status: str, stage: str, message: str, **extra: Any) -> None:
    storage.update_case(case_id, status=status, stage=stage, error=extra.pop("error", None))
    storage.add_event(case_id, "status", {
        "status": status,
        "stage": stage,
        "message": _safe(message, 1000),
        **extra,
    })


class _Investigation:
    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        case = storage.get_case(case_id)
        if not case:
            raise KeyError(f"Unknown case {case_id}")
        self.case = case
        self.bundle: Dict[str, Any] = case["bundle"]
        self.timeline: Dict[str, Any] = case["timeline"] or {}
        self.valid_ids: Set[str] = {
            str(item.get("id"))
            for item in (self.bundle.get("evidence") or [])
            if isinstance(item, dict) and item.get("id")
        }
        self.source_by_id = _source_map(self.bundle)
        self.runner = OpenCodeRunner()
        self.metrics = Metrics()
        self.findings: Dict[str, Dict[str, Any]] = {}
        self.revisions: Dict[str, Dict[str, Any]] = {}
        self.unresolved = 0

    async def _run_prompt(
        self,
        agent_id: str,
        stage: str,
        prompt: str,
        title: str,
    ) -> str:
        try:
            result = await asyncio.to_thread(
                self.runner.run, prompt, title=title
            )
        except OpenCodeError as exc:
            self.metrics.record_failure(agent_id, stage, str(exc))
            raise
        self.metrics.record(agent_id, stage, result)
        return result.text

    async def _call_json(
        self,
        agent_id: str,
        stage: str,
        prompt: str,
        title: str,
    ) -> Dict[str, Any]:
        text = await self._run_prompt(agent_id, stage, prompt, title)
        try:
            return agents.extract_json(text)
        except agents.AgentResponseError:
            strict_prompt = (
                prompt
                + "\n\nCRITICAL: Return exactly one valid JSON object. "
                "No markdown, no code fences, no prose."
            )
            retry_text = await self._run_prompt(agent_id, stage + "_retry", strict_prompt, title)
            return agents.extract_json(retry_text)

    def _source_ids(self, sources: Sequence[str], limit: int = 30) -> List[str]:
        ids = [
            evidence_id for evidence_id, source in self.source_by_id.items()
            if source in sources
        ]
        return ids[:limit]

    def _normalize_tasks(self, payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
        tasks: List[Dict[str, Any]] = []
        warnings: List[str] = []
        seen: Set[str] = set()
        for item in payload.get("tasks") or []:
            if not isinstance(item, dict):
                continue
            agent_id = item.get("agent_id") or item.get("agent")
            if agent_id not in agents.SPECIALIST_AGENTS or agent_id in seen:
                continue
            focus = _safe(item.get("focus") or item.get("task") or "", 2000)
            cited = [
                str(evidence_id)
                for evidence_id in (item.get("evidence_ids") or [])
                if str(evidence_id) in self.valid_ids
            ]
            invalid = [
                str(evidence_id)
                for evidence_id in (item.get("evidence_ids") or [])
                if str(evidence_id) not in self.valid_ids
            ]
            if invalid:
                warnings.append(
                    f"Lead task for {agent_id} cited unknown evidence: {', '.join(invalid)}"
                )
            tasks.append({
                "agent_id": agent_id,
                "focus": focus or f"Review all {agents.ROLES[agent_id].domain} evidence.",
                "evidence_ids": cited,
                "origin": "lead",
            })
            seen.add(agent_id)

        # Coverage fallback: a specialist with relevant evidence must not be
        # silently skipped. The bridge records these tasks as bridge-originated.
        for agent_id in agents.SPECIALIST_AGENTS:
            if agent_id in seen:
                continue
            role = agents.ROLES[agent_id]
            source_ids = self._source_ids(role.sources)
            if not source_ids:
                continue
            tasks.append({
                "agent_id": agent_id,
                "focus": f"Review every captured {role.domain} observation and report only what is directly supported.",
                "evidence_ids": source_ids,
                "origin": "coverage_fallback",
            })
        return tasks, warnings

    async def plan(self) -> List[Dict[str, Any]]:
        _status(self.case_id, "investigating", "lead_planning", "Lead is planning the investigation.")
        storage.add_event(self.case_id, "agent_status", {
            "agent_id": "devsquad-lead", "status": "running", "stage": "planning",
        })
        prompt = (
            agents.task_prompt(self.case_id, {})
            + "\n\n"
            + agents.render_evidence(self.bundle, self.timeline)
        )
        try:
            payload = await self._call_json(
                "devsquad-lead", "planning", prompt, "DEV-SQUAD lead planning"
            )
        except (OpenCodeError, agents.AgentResponseError) as exc:
            self.metrics.record_failure("devsquad-lead", "planning", str(exc))
            storage.add_event(self.case_id, "agent_status", {
                "agent_id": "devsquad-lead",
                "status": "failed",
                "stage": "planning",
                "error": _safe(exc, 800),
            })
            payload = {}

        tasks, plan_warnings = self._normalize_tasks(payload)
        for warning in plan_warnings:
            storage.add_event(self.case_id, "warning", {"message": warning})

        for task in tasks:
            sender = "devsquad-lead" if task["origin"] == "lead" else "devsquad-bridge"
            _record_message(
                self.case_id,
                sender,
                "TASK",
                {
                    "target_agent": task["agent_id"],
                    "focus": task["focus"],
                    "origin": task["origin"],
                    "notes": _safe(payload.get("notes"), 1000),
                },
                task["evidence_ids"],
                round_number=0,
            )
        storage.add_event(self.case_id, "agent_status", {
            "agent_id": "devsquad-lead",
            "status": "completed",
            "stage": "planning",
            "task_count": len(tasks),
        })
        return tasks

    async def run_specialist(self, task: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
        agent_id = task["agent_id"]
        role = agents.ROLES[agent_id]
        _status(
            self.case_id, "investigating", f"{agent_id}_investigating",
            f"{role.display_name} is investigating.",
        )
        storage.add_event(self.case_id, "agent_status", {
            "agent_id": agent_id, "status": "running", "stage": "investigating",
        })
        prompt = (
            agents.specialist_prompt(self.case_id, agent_id, task)
            + "\n\n"
            + agents.render_evidence(self.bundle, self.timeline, sources=role.sources)
        )

        async def attempt(current_prompt: str, suffix: str = "") -> Optional[Dict[str, Any]]:
            try:
                payload = await self._call_json(
                    agent_id,
                    f"finding{suffix}",
                    current_prompt,
                    f"DEV-SQUAD {role.display_name}",
                )
            except (OpenCodeError, agents.AgentResponseError) as exc:
                self.metrics.record_failure(agent_id, f"finding{suffix}", str(exc))
                return None

            finding = agents.normalize_finding(payload)
            valid, errors = agents.validate_finding(finding, self.valid_ids)
            if valid:
                for claim_index, claim in enumerate(finding.get("claims") or []):
                    for evidence_id in claim.get("evidence_ids") or []:
                        if self.source_by_id.get(evidence_id) not in role.sources:
                            errors.append(
                                f"Claim {claim_index + 1} cites {evidence_id} outside {agent_id}'s domain."
                            )
                valid = not errors
            if not valid:
                _record_message(
                    self.case_id, agent_id, finding.get("message_type", "FINDING"),
                    {**finding, "rejected": True},
                    [evidence_id for claim in finding.get("claims") or [] for evidence_id in claim.get("evidence_ids") or []],
                    round_number=0,
                    accepted=False,
                    validation_error="; ".join(errors),
                )
                return None
            return finding

        finding = await attempt(prompt)
        if finding is None:
            correction = (
                prompt
                + "\n\nYOUR PREVIOUS RESPONSE WAS REJECTED BY THE BRIDGE. "
                "Every factual claim must cite at least one real evidence ID from your own domain. "
                "Return one corrected JSON object only."
            )
            finding = await attempt(correction, "_correction")

        if finding is None:
            storage.add_event(self.case_id, "agent_status", {
                "agent_id": agent_id,
                "status": "failed",
                "stage": "investigating",
                "error": "No valid cited finding was produced.",
            })
            return agent_id, None

        evidence_ids = [
            evidence_id
            for claim in finding.get("claims") or []
            for evidence_id in claim.get("evidence_ids") or []
        ]
        _record_message(
            self.case_id,
            agent_id,
            finding.get("message_type", "FINDING"),
            finding,
            evidence_ids,
            round_number=0,
        )
        if finding.get("message_type") == "FINDING":
            self.findings[agent_id] = finding
        storage.add_event(self.case_id, "agent_status", {
            "agent_id": agent_id,
            "status": "completed",
            "stage": "investigating",
            "message_type": finding.get("message_type"),
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
        })
        return agent_id, finding

    async def challenge_round(self) -> None:
        if not self.findings:
            return

        _status(self.case_id, "investigating", "challenge", "Lead is challenging specialist findings.")
        prompt = agents.challenge_prompt(self.case_id, self.findings, self.timeline)
        try:
            payload = await self._call_json(
                "devsquad-lead", "challenge", prompt, "DEV-SQUAD lead challenge"
            )
        except (OpenCodeError, agents.AgentResponseError) as exc:
            self.metrics.record_failure("devsquad-lead", "challenge", str(exc))
            storage.add_event(self.case_id, "warning", {
                "message": "Lead challenge step failed: " + _safe(exc, 800),
            })
            return

        normalized = agents.normalize_challenges(payload, self.findings.keys())
        challenges = normalized["challenges"][:2]  # MVP max: one round, two targets
        if not challenges:
            storage.add_event(self.case_id, "agent_status", {
                "agent_id": "devsquad-lead",
                "status": "completed",
                "stage": "challenge",
                "challenges": 0,
            })
            return

        for challenge in challenges:
            valid_citations = [
                evidence_id for evidence_id in challenge.get("evidence_ids") or []
                if evidence_id in self.valid_ids
            ]
            _record_message(
                self.case_id,
                "devsquad-lead",
                "CHALLENGE",
                {
                    "target_agent": challenge["agent_id"],
                    "question": challenge["question"],
                },
                valid_citations,
                round_number=1,
            )
            storage.add_event(self.case_id, "agent_status", {
                "agent_id": "devsquad-lead",
                "status": "challenging",
                "stage": "challenge",
                "target_agent": challenge["agent_id"],
            })

        async def revise(challenge: Dict[str, Any]) -> None:
            agent_id = challenge["agent_id"]
            if agent_id not in self.findings:
                self.unresolved += 1
                return
            storage.add_event(self.case_id, "agent_status", {
                "agent_id": agent_id, "status": "revising", "stage": "revision",
            })
            prompt = (
                agents.revise_prompt(
                    self.case_id,
                    agent_id,
                    challenge["question"],
                    self.findings[agent_id],
                )
                + "\n\n"
                + agents.render_evidence(
                    self.bundle, self.timeline, sources=agents.ROLES[agent_id].sources
                )
            )
            try:
                payload = await self._call_json(
                    agent_id, "revision", prompt, f"DEV-SQUAD {agent_id} revision"
                )
            except (OpenCodeError, agents.AgentResponseError) as exc:
                self.metrics.record_failure(agent_id, "revision", str(exc))
                self.unresolved += 1
                storage.add_event(self.case_id, "agent_status", {
                    "agent_id": agent_id, "status": "failed", "stage": "revision",
                    "error": _safe(exc, 800),
                })
                return

            revised = agents.normalize_finding(payload)
            # A revision answers a lead challenge and may legitimately reference
            # evidence from another domain as context. Every citation must still
            # exist in the case; initial findings remain domain-restricted.
            valid, errors = agents.validate_finding(revised, self.valid_ids)
            evidence_ids = [
                evidence_id
                for claim in revised.get("claims") or []
                for evidence_id in claim.get("evidence_ids") or []
            ]
            if not valid:
                self.unresolved += 1
                _record_message(
                    self.case_id, agent_id, "REVISE",
                    {**revised, "rejected": True},
                    evidence_ids,
                    round_number=1,
                    accepted=False,
                    validation_error="; ".join(errors),
                )
                storage.add_event(self.case_id, "agent_status", {
                    "agent_id": agent_id, "status": "failed", "stage": "revision",
                    "error": "; ".join(errors),
                })
                return

            self.revisions[agent_id] = revised
            _record_message(
                self.case_id,
                agent_id,
                "REVISE",
                {
                    "target_agent": "devsquad-lead",
                    "challenge_question": challenge["question"],
                    "finding": revised,
                },
                evidence_ids,
                round_number=1,
            )
            storage.add_event(self.case_id, "agent_status", {
                "agent_id": agent_id, "status": "completed", "stage": "revision",
                "message_type": revised.get("message_type"),
            })

        await asyncio.gather(*(revise(challenge) for challenge in challenges))

    async def produce_verdict(self) -> Dict[str, Any]:
        _status(self.case_id, "investigating", "verdict", "Lead is producing the final verdict.")
        prompt = (
            agents.verdict_prompt(
                self.case_id, self.findings, self.revisions, self.timeline
            )
            + "\n\n"
            + agents.render_evidence(self.bundle, self.timeline)
        )
        fallback_reason = ""
        verdict: Optional[Dict[str, Any]] = None
        try:
            payload = await self._call_json(
                "devsquad-lead", "verdict", prompt, "DEV-SQUAD final verdict"
            )
            verdict = agents.normalize_verdict(payload)
        except (OpenCodeError, agents.AgentResponseError) as exc:
            self.metrics.record_failure("devsquad-lead", "verdict", str(exc))
            fallback_reason = "Agent verdict failed: " + _safe(exc, 800)
            verdict = aggregate_findings(
                self.findings, self.bundle, self.timeline, self.revisions
            )

        try:
            final = finalize_verdict(
                self.bundle,
                self.timeline,
                verdict,
                unresolved_challenges=self.unresolved,
            )
        except VerdictValidationError as exc:
            correction = (
                prompt
                + "\n\nREJECTED BY BRIDGE: "
                + _safe(exc, 1200)
                + "\nReturn a corrected JSON verdict. Cite only real evidence IDs."
            )
            try:
                payload = await self._call_json(
                    "devsquad-lead", "verdict_correction", correction,
                    "DEV-SQUAD corrected verdict",
                )
                final = finalize_verdict(
                    self.bundle,
                    self.timeline,
                    agents.normalize_verdict(payload),
                    unresolved_challenges=self.unresolved,
                )
            except (OpenCodeError, agents.AgentResponseError, VerdictValidationError) as retry_exc:
                self.metrics.record_failure("devsquad-lead", "verdict_correction", str(retry_exc))
                fallback_reason = "Verdict failed validation: " + _safe(retry_exc, 1000)
                final = insufficient_verdict([
                    "The structured verdict was invalid. Re-run with a model that follows the JSON contract."
                ])
                final = finalize_verdict(
                    self.bundle, self.timeline, final,
                    unresolved_challenges=self.unresolved,
                )
                final["validation_fallback"] = True

        if fallback_reason:
            final["fallback_reason"] = fallback_reason
            final["validation_fallback"] = True

        evidence_ids = final.get("supporting_evidence") or []
        _record_message(
            self.case_id,
            "devsquad-lead",
            "VERDICT",
            final,
            evidence_ids,
            round_number=1 if self.revisions else 0,
        )
        storage.set_verdict(self.case_id, final)
        return final

    async def run(self) -> Dict[str, Any]:
        storage.update_case(
            self.case_id,
            status="investigating",
            stage="starting",
            transport="local",
            started_at=_now(),
            finished_at=None,
            error=None,
            agent_rounds=0,
        )
        storage.add_event(self.case_id, "status", {
            "status": "investigating",
            "stage": "starting",
            "message": "Investigation started with four real agents.",
        })

        try:
            tasks = await self.plan()
            results = await asyncio.gather(
                *(self.run_specialist(task) for task in tasks)
            )
            for agent_id, finding in results:
                if finding and finding.get("message_type") == "FINDING":
                    self.findings[agent_id] = finding

            if not self.findings and not any(
                result[1] is not None for result in results
            ):
                storage.add_event(self.case_id, "warning", {
                    "message": "No specialist produced a valid citation-backed response. "
                               "Proceeding to verdict with insufficient-evidence override.",
                })

            await self.challenge_round()
            verdict = await self.produce_verdict()
            rounds = 2 if self.revisions else 1
            storage.update_case(
                self.case_id,
                status="completed",
                stage="completed",
                finished_at=_now(),
                agent_rounds=rounds,
                token_usage_json=json.dumps(self.metrics.to_dict(), ensure_ascii=False),
                error=None,
            )
            storage.add_event(self.case_id, "status", {
                "status": "completed",
                "stage": "completed",
                "message": "Investigation completed. Human decision is required.",
                "confidence": verdict.get("confidence"),
                "root_cause": verdict.get("root_cause"),
            })
            return verdict
        except Exception as exc:  # noqa: BLE001 - persisted for the UI
            LOGGER.exception("Investigation failed for %s", self.case_id)
            storage.update_case(
                self.case_id,
                status="failed",
                stage="error",
                finished_at=_now(),
                token_usage_json=json.dumps(self.metrics.to_dict(), ensure_ascii=False),
                error=_safe(exc, 1200),
            )
            storage.add_event(self.case_id, "status", {
                "status": "failed",
                "stage": "error",
                "message": "Investigation failed.",
                "error": _safe(exc, 1200),
            })
            raise


async def run_local_investigation(case_id: str) -> Dict[str, Any]:
    investigation = _Investigation(case_id)
    timeout = investigation_timeout_seconds()
    try:
        return await asyncio.wait_for(investigation.run(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        storage.update_case(
            case_id,
            status="timed_out",
            stage="timeout",
            finished_at=_now(),
            error=f"Investigation exceeded {timeout} seconds.",
        )
        storage.add_event(case_id, "status", {
            "status": "timed_out",
            "stage": "timeout",
            "message": f"Investigation exceeded {timeout} seconds.",
        })
        raise RuntimeError(f"Investigation timed out after {timeout} seconds.") from exc
