"""Deterministic confidence scoring."""

from __future__ import annotations

from app.models import ConfidenceBreakdown, ConflictRecord, EvidenceItem, MissingEvidenceRecord, PolicyResult


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def calculate_confidence(
    evidence: list[EvidenceItem],
    missing_evidence: list[MissingEvidenceRecord],
    conflicts: list[ConflictRecord],
    policy_result: PolicyResult,
    expected_sources: list[str],
) -> ConfidenceBreakdown:
    explanation: list[str] = []
    available_sources = {
        item.source for item in evidence if item.freshness_status not in {"unavailable", "unknown"}
    }
    expected = set(expected_sources)
    evidence_completeness = len(available_sources & expected) / len(expected) if expected else 1.0
    if missing_evidence:
        explanation.append(f"{len(missing_evidence)} evidence source(s) are missing or unavailable.")
    explanation.append(f"Evidence completeness is {evidence_completeness:.2f}.")

    available_items = [item for item in evidence if item.freshness_status != "unavailable"]
    evidence_reliability = (
        sum(item.reliability for item in available_items) / len(available_items)
        if available_items
        else 0.0
    )
    explanation.append(f"Average evidence reliability is {evidence_reliability:.2f}.")

    freshness_values = [
        1.0 if item.freshness_status == "fresh" else 0.5 if item.freshness_status == "stale" else 0.0
        for item in evidence
    ]
    evidence_freshness = sum(freshness_values) / len(freshness_values) if freshness_values else 0.0
    explanation.append(f"Evidence freshness score is {evidence_freshness:.2f}.")

    conflict_penalty = min(0.5, sum(0.25 if item.severity == "high" else 0.15 if item.severity == "medium" else 0.05 for item in conflicts))
    if conflicts:
        explanation.append(f"Conflict penalty is {conflict_penalty:.2f}.")

    policy_certainty = 1.0 if policy_result.status in {"passed", "blocked"} else 0.75
    if not policy_result.allowed:
        policy_certainty = 1.0
    explanation.append(f"Policy certainty is {policy_certainty:.2f}.")

    final = _clamp(
        0.30 * evidence_completeness
        + 0.25 * evidence_reliability
        + 0.20 * evidence_freshness
        + 0.25 * policy_certainty
        - conflict_penalty
    )

    return ConfidenceBreakdown(
        evidence_completeness=_clamp(evidence_completeness),
        evidence_reliability=_clamp(evidence_reliability),
        evidence_freshness=_clamp(evidence_freshness),
        conflict_penalty=_clamp(conflict_penalty),
        policy_certainty=_clamp(policy_certainty),
        final_confidence=final,
        explanation=explanation,
    )

