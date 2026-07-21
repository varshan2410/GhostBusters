from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.models import Alternative, ConfidenceBreakdown, MissingEvidenceRecord, VerifierFinding
from core.conftest_policy import ConftestPolicyEvaluator
from core.reasoning_engine import analyze_resource
from core.run_store import InMemoryRunStore
from core.workflow_service import WorkflowService
from integrations.registry import default_registry
from tests.scenario_helpers import load_resource, load_scenario


def context(name: str):  # type: ignore[no-untyped-def]
    scenario = load_scenario(name)
    resource = load_resource(name)
    evaluator = ConftestPolicyEvaluator(enabled=False)
    decision = analyze_resource(
        scenario.goal, scenario, resource, default_registry, evaluator
    )
    preferred = next(
        item for item in decision.alternatives if item.action == decision.preferred_action
    )
    return scenario, resource, decision, preferred


def fallback_result(name: str):  # type: ignore[no-untyped-def]
    scenario, resource, decision, preferred = context(name)
    evaluator = ConftestPolicyEvaluator(enabled=False)
    result = evaluator.evaluate(
        resource,
        decision.evidence,
        decision.missing_evidence,
        preferred,
        decision.verifier_findings,
        decision.conflicts,
        decision.confidence,
        scenario_name=scenario.name,
    )
    return result


def test_safe_staging_resource_is_allowed() -> None:
    result = fallback_result("safe")

    assert result.allowed is True
    assert result.engine == "python_fallback"
    assert result.requires_human_approval is True


def test_production_remediation_is_blocked() -> None:
    result = fallback_result("production")

    assert result.allowed is False
    assert any(item.code == "PRODUCTION_REMEDIATION_BLOCKED" for item in result.violations)


def test_destructive_terraform_action_is_blocked() -> None:
    result = fallback_result("destructive")

    assert result.allowed is False
    assert any(item.code == "DESTRUCTIVE_ACTION_BLOCKED" for item in result.violations)


def test_unknown_ownership_is_blocked() -> None:
    scenario, resource, decision, _ = context("safe")
    evidence = [item for item in decision.evidence if item.source != "jira"]
    preferred = next(item for item in decision.alternatives if item.action == "downsize")
    evaluator = ConftestPolicyEvaluator(enabled=False)

    result = evaluator.evaluate(
        resource, evidence, [], preferred, decision.verifier_findings,
        decision.conflicts, decision.confidence, scenario_name=scenario.name,
    )

    assert result.allowed is False
    assert any(item.code == "UNKNOWN_OWNERSHIP" for item in result.violations)


def test_active_critical_dependency_is_blocked() -> None:
    result = fallback_result("dependency")

    assert result.allowed is False
    assert any(item.code == "ACTIVE_DEPENDENCY" for item in result.violations)


def test_missing_critical_evidence_is_blocked_for_remediation() -> None:
    scenario, resource, decision, _ = context("safe")
    preferred = next(item for item in decision.alternatives if item.action == "downsize")
    missing = [
        MissingEvidenceRecord(
            source="utilization",
            claim_needed="recent utilization",
            critical=True,
            impact="Cannot safely rightsize.",
        )
    ]
    evaluator = ConftestPolicyEvaluator(enabled=False)

    result = evaluator.evaluate(
        resource, decision.evidence, missing, preferred,
        decision.verifier_findings, decision.conflicts, decision.confidence,
        scenario_name=scenario.name,
    )

    assert result.allowed is False
    assert any(item.code == "MISSING_CRITICAL_EVIDENCE" for item in result.violations)


def test_critical_verifier_failure_is_blocked() -> None:
    scenario, resource, decision, preferred = context("safe")
    findings = list(decision.verifier_findings) + [
        VerifierFinding(
            check_name="forced_critical",
            status="failed",
            severity="critical",
            explanation="Forced test failure.",
        )
    ]
    evaluator = ConftestPolicyEvaluator(enabled=False)

    result = evaluator.evaluate(
        resource, decision.evidence, [], preferred, findings,
        decision.conflicts, decision.confidence, scenario_name=scenario.name,
    )

    assert result.allowed is False
    assert any(item.code == "CRITICAL_VERIFIER_FAILURE" for item in result.violations)


def test_low_confidence_is_blocked() -> None:
    scenario, resource, decision, preferred = context("safe")
    low_confidence = decision.confidence.model_copy(update={"final_confidence": 0.20})
    evaluator = ConftestPolicyEvaluator(enabled=False, minimum_confidence=0.70)

    result = evaluator.evaluate(
        resource, decision.evidence, [], preferred, decision.verifier_findings,
        decision.conflicts, low_confidence, scenario_name=scenario.name,
    )

    assert result.allowed is False
    assert any(item.code == "LOW_CONFIDENCE" for item in result.violations)


@pytest.mark.parametrize("action", ["keep", "abstain"])
def test_keep_or_abstain_remains_safe(action: str) -> None:
    scenario, resource, decision, _ = context("safe")
    preferred = Alternative(
        action=action,  # type: ignore[arg-type]
        description="Safe no-change outcome.",
        eligible=True,
        score=1.0,
    )
    low_confidence = decision.confidence.model_copy(update={"final_confidence": 0.10})
    evaluator = ConftestPolicyEvaluator(enabled=False)

    result = evaluator.evaluate(
        resource, [], [], preferred, [], [], low_confidence,
        scenario_name=scenario.name,
    )

    assert result.allowed is True
    assert result.requires_human_approval is False


def test_valid_conftest_json_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario, resource, decision, preferred = context("safe")
    payload = [
        {
            "namespace": "ghostbusters",
            "failures": [
                {
                    "msg": "Production resources cannot be automatically remediated",
                    "metadata": {
                        "code": "PRODUCTION_REMEDIATION_BLOCKED",
                        "severity": "critical",
                    },
                }
            ],
            "warnings": [],
        }
    ]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, json.dumps(payload), ""),
    )
    evaluator = ConftestPolicyEvaluator(enabled=True, executable="conftest-test")

    result = evaluator.evaluate(
        resource, decision.evidence, [], preferred, decision.verifier_findings,
        decision.conflicts, decision.confidence, scenario_name=scenario.name,
    )

    assert result.allowed is False
    assert result.engine == "conftest"
    assert result.violations[0].code == "PRODUCTION_REMEDIATION_BLOCKED"


def test_malformed_output_activates_python_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario, resource, decision, preferred = context("safe")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "not-json", ""),
    )
    evaluator = ConftestPolicyEvaluator(enabled=True, executable="conftest-test")

    result = evaluator.evaluate(
        resource, decision.evidence, [], preferred, decision.verifier_findings,
        decision.conflicts, decision.confidence,
    )

    assert result.engine == "python_fallback"
    assert result.fallback_reason == "Conftest returned malformed JSON output."


def test_missing_executable_activates_python_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario, resource, decision, preferred = context("safe")

    def missing(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)
    evaluator = ConftestPolicyEvaluator(enabled=True, executable="missing-conftest")

    result = evaluator.evaluate(
        resource, decision.evidence, [], preferred, decision.verifier_findings,
        decision.conflicts, decision.confidence,
    )

    assert result.engine == "python_fallback"
    assert result.fallback_reason == "Conftest executable was not found."


def test_timeout_activates_python_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario, resource, decision, preferred = context("safe")

    def timeout(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

    monkeypatch.setattr(subprocess, "run", timeout)
    evaluator = ConftestPolicyEvaluator(enabled=True, executable="slow-conftest")

    result = evaluator.evaluate(
        resource, decision.evidence, [], preferred, decision.verifier_findings,
        decision.conflicts, decision.confidence,
    )

    assert result.engine == "python_fallback"
    assert result.fallback_reason == "Conftest policy evaluation timed out."


def test_policy_audit_events_are_written() -> None:
    evaluator = ConftestPolicyEvaluator(enabled=False)
    service = WorkflowService(InMemoryRunStore(), policy_evaluator=evaluator)

    run, _ = service.start_run_request("safe")
    event_types = {item.event_type for item in run.audit_events}

    assert "policy_evaluation_started" in event_types
    assert "policy_engine_selected" in event_types
    assert "policy_fallback_used" in event_types
    assert "policy_evaluation_completed" in event_types
    completed = next(
        item for item in run.audit_events if item.event_type == "policy_evaluation_completed"
    )
    assert completed.details["engine"] == "python_fallback"
    assert completed.details["allowed"] is True


@pytest.mark.skipif(shutil.which("conftest") is None, reason="Conftest is not installed")
def test_real_rego_policy_optional_integration() -> None:
    scenario, resource, decision, preferred = context("safe")
    evaluator = ConftestPolicyEvaluator(enabled=True)

    result = evaluator.evaluate(
        resource, decision.evidence, [], preferred, decision.verifier_findings,
        decision.conflicts, decision.confidence, scenario_name=scenario.name,
    )

    assert result.engine == "conftest"
    assert result.allowed is True
