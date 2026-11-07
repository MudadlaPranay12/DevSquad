"""
DEV-SQUAD — verdict validation and rule-derived confidence.

An agent's self-reported confidence is never trusted. The bridge computes the
category from observable properties of the evidence and the collaboration.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

CONFIDENCE_METHOD = "rule-derived-v1"
NOT_DETERMINED_REASON = "Available evidence does not establish the cause."
DEFAULT_NEEDED = (
    "Capture a failing request, a console exception, or an observable application "
    "error that distinguishes between candidate causes."
)


class VerdictValidationError(ValueError):
    pass


def strip_markdown_code_blocks(text: Any) -> str:
    """Strip markdown code fences from agent output before JSON parsing.

    Handles ```json ... ```, ``` ... ```, and stray backticks so the parser
    can recover cleanly from minor formatting quirks, including text that
    appears before or after the code block.
    """
    if not isinstance(text, str):
        return ""
    cleaned = text.strip()
    # Extract content between triple backticks if present
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: strip leading/trailing fence lines if the whole text is a fence
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _valid_ids(bundle: Dict[str, Any]) -> Set[str]:
    return {
        str(item.get("id"))
        for item in (bundle.get("evidence") or [])
        if isinstance(item, dict) and item.get("id")
    }


def _source_by_id(bundle: Dict[str, Any]) -> Dict[str, str]:
    return {
        str(item.get("id")): str(item.get("source"))
        for item in (bundle.get("evidence") or [])
        if isinstance(item, dict) and item.get("id")
    }


def validate_citations(
    verdict: Dict[str, Any],
    bundle: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    valid = _valid_ids(bundle)
    errors: List[str] = []

    def check(ids: Iterable[str], label: str) -> None:
        for evidence_id in ids or []:
            if evidence_id not in valid:
                errors.append(f"{label} cites unknown evidence {evidence_id}.")

    check(verdict.get("supporting_evidence") or [], "supporting_evidence")
    for index, step in enumerate(verdict.get("failure_chain") or []):
        if not str(step.get("step", "")).strip():
            errors.append(f"failure_chain[{index}] has an empty step.")
        if not (step.get("evidence_ids") or []):
            errors.append(f"failure_chain[{index}] has no evidence citation.")
        check(step.get("evidence_ids") or [], f"failure_chain[{index}]")
    for index, hypothesis in enumerate(verdict.get("rejected_hypotheses") or []):
        check(hypothesis.get("evidence_ids") or [], f"rejected_hypotheses[{index}]")

    if verdict.get("root_cause_determined"):
        if not (verdict.get("supporting_evidence") or []):
            errors.append("A determined root cause must cite supporting evidence.")
        if not (verdict.get("failure_chain") or []):
            errors.append("A determined root cause must include a cited failure chain.")
    return (not errors, errors)


def compute_confidence(
    bundle: Dict[str, Any],
    timeline: Dict[str, Any],
    verdict: Dict[str, Any],
    *,
    unresolved_challenges: int = 0,
) -> Dict[str, Any]:
    supporting = list(verdict.get("supporting_evidence") or [])
    source_by_id = _source_by_id(bundle)
    sources = {source_by_id.get(evidence_id) for evidence_id in supporting if source_by_id.get(evidence_id)}
    coverage = timeline.get("coverage") or {}
    ordering_verified = bool(coverage.get("ordering_verified"))
    capture_complete = bool(coverage.get("capture_complete"))
    insufficient = bool(timeline.get("insufficient_evidence"))

    # A conclusion that spans sources or multiple chain steps is a causal
    # inference, not a single direct observation.
    inferred = len(sources) > 1 or len(verdict.get("failure_chain") or []) > 1

    determined = bool(verdict.get("root_cause_determined")) and verdict.get("root_cause") != "Not determined"
    factors = {
        "supporting_evidence_count": len(supporting),
        "independent_source_count": len(sources),
        "independent_sources": sorted(sources),
        "ordering_verified": ordering_verified,
        "same_timestamp_events": list(coverage.get("same_timestamp_events") or []),
        "untimed_events": list(coverage.get("untimed_events") or []),
        "capture_complete": capture_complete,
        "unresolved_challenges": unresolved_challenges,
        "causal_inference_required": inferred,
        "insufficient_evidence": insufficient,
    }

    reasons: List[str] = []
    if not determined or insufficient:
        confidence = "Low"
        reasons.append("Root cause is not established by the available evidence.")
    elif len(sources) < 2:
        confidence = "Low"
        reasons.append("The conclusion relies on fewer than two independent evidence sources.")
    elif not ordering_verified:
        confidence = "Low"
        reasons.append("Event ordering is not fully verified.")
    elif unresolved_challenges > 0:
        confidence = "Low"
        reasons.append("At least one challenge remains unresolved.")
    elif not capture_complete:
        confidence = "Low"
        reasons.append("Capture coverage is incomplete.")
    elif inferred:
        confidence = "Medium"
        reasons.append(
            "Multiple independent sources support the conclusion, but it requires an inferred causal step."
        )
    else:
        confidence = "High"
        reasons.append(
            "A direct observation is supported by multiple independent sources, with verified ordering and complete coverage."
        )

    return {
        "confidence": confidence,
        "confidence_reason": " ".join(reasons),
        "confidence_factors": factors,
        "confidence_method": CONFIDENCE_METHOD,
    }


def insufficient_verdict(missing_evidence: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "root_cause": "Not determined",
        "root_cause_determined": False,
        "summary": "The captured evidence does not establish a root cause.",
        "supporting_evidence": [],
        "failure_chain": [],
        "rejected_hypotheses": [],
        "suggested_next_action": (
            "Capture additional browser observations before drawing a conclusion."
        ),
        "missing_evidence": missing_evidence or [DEFAULT_NEEDED],
        "reported_confidence": "Low",
        "reason": NOT_DETERMINED_REASON,
    }


def aggregate_findings(
    findings: Dict[str, Any],
    bundle: Dict[str, Any],
    timeline: Dict[str, Any],
    revisions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate specialist findings into a verdict when the lead agent fails.

    Builds an honest verdict from the evidence cited by specialists, falling back
    to "Not determined" only when no valid cited evidence exists.
    """
    valid_ids = _valid_ids(bundle)
    source_by_id = _source_by_id(bundle)

    cited_ids: Set[str] = set()
    claim_summaries: List[str] = []
    sources: Set[str] = set()

    for agent_id, finding in (findings or {}).items():
        message_type = finding.get("message_type", "FINDING")
        summary = finding.get("summary", "")
        if summary:
            claim_summaries.append(f"{agent_id}: {summary}")
        for claim in finding.get("claims") or []:
            for eid in claim.get("evidence_ids") or []:
                if eid in valid_ids:
                    cited_ids.add(eid)
                    src = source_by_id.get(eid)
                    if src:
                        sources.add(src)

    supporting = sorted(cited_ids)
    determined = bool(supporting) and len(sources) >= 1

    if determined:
        root_cause = "Specialist findings cite direct failure evidence: " + ", ".join(
            supporting[:5]
        )
        summary = (
            "; ".join(claim_summaries[:3])
            if claim_summaries
            else "Specialist agents investigated the evidence."
        )
        missing_evidence: List[str] = []
    else:
        root_cause = "Not determined"
        summary = "Specialist findings did not cite valid failure evidence."
        missing_evidence = [DEFAULT_NEEDED]

    return {
        "root_cause": root_cause,
        "root_cause_determined": determined,
        "summary": summary,
        "supporting_evidence": supporting,
        "failure_chain": [
            {"step": "Specialist findings cite direct evidence.", "evidence_ids": supporting}
        ]
        if supporting
        else [],
        "rejected_hypotheses": [],
        "suggested_next_action": "Review specialist findings and capture additional evidence if needed.",
        "missing_evidence": missing_evidence,
        "suggested_fix": "Apply the remediation suggested by the specialist findings, if any.",
        "reported_confidence": "Medium" if determined else "Low",
        "aggregated": True,
    }


def finalize_verdict(
    bundle: Dict[str, Any],
    timeline: Dict[str, Any],
    verdict: Dict[str, Any],
    *,
    unresolved_challenges: int = 0,
) -> Dict[str, Any]:
    """Validate citations, enforce evidence honesty, and attach rule confidence."""
    final = dict(verdict)

    # Honesty override: no direct failure evidence means no determined root cause,
    # regardless of what an agent claimed.
    if timeline.get("insufficient_evidence"):
        missing = final.get("missing_evidence") or []
        if not missing:
            missing = [DEFAULT_NEEDED]
        override = insufficient_verdict(missing)
        override["reported_confidence"] = final.get("reported_confidence", "")
        override["agent_summary"] = final.get("summary", "")
        override["insufficient_evidence_override"] = True
        final = override

    is_valid, errors = validate_citations(final, bundle)
    if not is_valid:
        raise VerdictValidationError("; ".join(errors))

    final.update(
        compute_confidence(
            bundle,
            timeline,
            final,
            unresolved_challenges=unresolved_challenges,
        )
    )
    final["validated"] = True
    return final
