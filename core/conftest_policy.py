"""Conftest/OPA policy adapter with a deterministic Python fail-safe."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from app.models import (
    Alternative,
    ConfidenceBreakdown,
    ConflictRecord,
    EvidenceItem,
    MissingEvidenceRecord,
    PolicyResult,
    PolicyViolation,
    TerraformResourceChange,
    VerifierFinding,
)
from app.settings import settings
from core.evidence_utils import active_dependencies, value_for
from core.policy_engine import evaluate_policy


POLICY_VERSION = "1.0"
REMEDIATION_ACTIONS = {"downsize", "schedule"}
REPO_ROOT = Path(__file__).resolve().parent.parent


class ConftestPolicyEvaluator:
    """Evaluate sanitized workflow facts with Conftest and fail safely."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        executable: str | None = None,
        policy_dir: str | Path | None = None,
        timeout_seconds: float | None = None,
        minimum_confidence: float | None = None,
    ) -> None:
        self.enabled = settings.conftest_enabled if enabled is None else enabled
        self.executable = executable or settings.conftest_executable
        configured_dir = Path(policy_dir or settings.conftest_policy_dir)
        self.policy_dir = configured_dir if configured_dir.is_absolute() else REPO_ROOT / configured_dir
        self.timeout_seconds = timeout_seconds or settings.conftest_timeout_seconds
        self.minimum_confidence = (
            settings.minimum_policy_confidence
            if minimum_confidence is None
            else minimum_confidence
        )

    def evaluate(
        self,
        resource: TerraformResourceChange,
        evidence: list[EvidenceItem],
        missing_evidence: list[MissingEvidenceRecord],
        preferred: Alternative,
        verifier_findings: list[VerifierFinding],
        conflicts: list[ConflictRecord],
        confidence: ConfidenceBreakdown,
        *,
        run_id: UUID | None = None,
        scenario_name: str | None = None,
    ) -> PolicyResult:
        policy_input = self.build_input(
            resource,
            evidence,
            missing_evidence,
            preferred,
            verifier_findings,
            conflicts,
            confidence,
            run_id=run_id,
            scenario_name=scenario_name,
        )
        if not self.enabled:
            return self._fallback(
                "Conftest is disabled by configuration.",
                resource, evidence, missing_evidence, preferred,
                verifier_findings, conflicts, confidence, policy_input,
            )
        if not self.policy_dir.is_dir():
            return self._fallback(
                "Conftest policy directory is unavailable.",
                resource, evidence, missing_evidence, preferred,
                verifier_findings, conflicts, confidence, policy_input,
            )

        try:
            with tempfile.TemporaryDirectory(prefix="ghostbusters-policy-") as temp_dir:
                input_path = Path(temp_dir) / "input.json"
                input_path.write_text(json.dumps(policy_input), encoding="utf-8")
                completed = subprocess.run(
                    [
                        self.executable,
                        "test",
                        str(input_path),
                        "--policy",
                        str(self.policy_dir),
                        "--namespace",
                        "ghostbusters",
                        "--output",
                        "json",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
        except FileNotFoundError:
            return self._fallback(
                "Conftest executable was not found.",
                resource, evidence, missing_evidence, preferred,
                verifier_findings, conflicts, confidence, policy_input,
            )
        except subprocess.TimeoutExpired:
            return self._fallback(
                "Conftest policy evaluation timed out.",
                resource, evidence, missing_evidence, preferred,
                verifier_findings, conflicts, confidence, policy_input,
            )
        except OSError:
            return self._fallback(
                "Conftest could not be executed.",
                resource, evidence, missing_evidence, preferred,
                verifier_findings, conflicts, confidence, policy_input,
            )

        if completed.returncode not in {0, 1}:
            return self._fallback(
                f"Conftest execution failed with exit code {completed.returncode}.",
                resource, evidence, missing_evidence, preferred,
                verifier_findings, conflicts, confidence, policy_input,
            )
        try:
            return self.parse_output(completed.stdout, preferred)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            return self._fallback(
                "Conftest returned malformed JSON output.",
                resource, evidence, missing_evidence, preferred,
                verifier_findings, conflicts, confidence, policy_input,
            )

    def build_input(
        self,
        resource: TerraformResourceChange,
        evidence: list[EvidenceItem],
        missing_evidence: list[MissingEvidenceRecord],
        preferred: Alternative,
        verifier_findings: list[VerifierFinding],
        conflicts: list[ConflictRecord],
        confidence: ConfidenceBreakdown,
        *,
        run_id: UUID | None = None,
        scenario_name: str | None = None,
    ) -> dict[str, Any]:
        ownership_known = self._ownership_known(resource, evidence)
        return {
            "policy_version": POLICY_VERSION,
            "run_id": str(run_id) if run_id else None,
            "scenario_name": scenario_name,
            "resource": {
                "address": resource.address,
                "environment": resource.environment,
                "terraform_actions": list(resource.actions),
                "destructive": resource.destructive,
                "ownership_status": "known" if ownership_known else "unknown",
                "active_dependencies": active_dependencies(evidence),
            },
            "recommendation": {
                "action": preferred.action,
                "expected_monthly_savings": preferred.estimated_monthly_savings,
                "risk": "medium" if preferred.risks else "low",
                "risks": list(preferred.risks),
                "reversible": preferred.action in {"keep", "downsize", "schedule"},
            },
            "evidence": {
                "missing_critical": [
                    {"source": item.source, "claim": item.claim_needed}
                    for item in missing_evidence
                    if item.critical
                ],
                "conflicts": [
                    {"claim": item.claim, "severity": item.severity}
                    for item in conflicts
                ],
            },
            "verifier_failures": [
                {"check": item.check_name, "severity": item.severity}
                for item in verifier_findings
                if item.status == "failed"
            ],
            "confidence": {
                "score": confidence.final_confidence,
                "minimum_threshold": self.minimum_confidence,
            },
        }

    def parse_output(self, output: str, preferred: Alternative) -> PolicyResult:
        decoded = json.loads(output)
        if isinstance(decoded, dict):
            results = [decoded]
        elif isinstance(decoded, list):
            results = decoded
        else:
            raise ValueError("Conftest output must be an object or list.")
        if not all(isinstance(result, dict) for result in results):
            raise ValueError("Conftest result entries must be objects.")

        failures: list[dict[str, Any]] = []
        warning_messages: list[str] = []
        evaluated_rules: list[str] = []
        for result in results:
            namespace = result.get("namespace")
            if namespace:
                evaluated_rules.append(str(namespace))
            result_failures = result.get("failures", [])
            result_warnings = result.get("warnings", [])
            if not isinstance(result_failures, list) or not isinstance(result_warnings, list):
                raise ValueError("Conftest failures and warnings must be lists.")
            failures.extend(item for item in result_failures if isinstance(item, dict))
            warning_messages.extend(self._message(item) for item in result_warnings)

        violations = [self._violation(item) for item in failures]
        reasons = [item.message for item in violations]
        remediation = preferred.action in REMEDIATION_ACTIONS
        return PolicyResult(
            allowed=not violations,
            status="blocked" if violations else "passed",
            blocking_reasons=reasons,
            warnings=warning_messages + (
                ["Human approval is mandatory before any remediation action."]
                if remediation and not violations else []
            ),
            evaluated_rules=evaluated_rules or ["ghostbusters"],
            requires_human_approval=remediation and not violations,
            engine="conftest",
            policy_version=POLICY_VERSION,
            violations=violations,
        )

    def _fallback(
        self,
        reason: str,
        resource: TerraformResourceChange,
        evidence: list[EvidenceItem],
        missing_evidence: list[MissingEvidenceRecord],
        preferred: Alternative,
        verifier_findings: list[VerifierFinding],
        conflicts: list[ConflictRecord],
        confidence: ConfidenceBreakdown,
        policy_input: dict[str, Any],
    ) -> PolicyResult:
        result = evaluate_policy(
            resource,
            evidence,
            missing_evidence,
            preferred,
            verifier_findings,
            conflicts,
            ownership_known=policy_input["resource"]["ownership_status"] == "known",
            confidence_score=confidence.final_confidence,
            minimum_confidence=self.minimum_confidence,
        )
        warnings = list(result.warnings)
        warnings.append("Conftest was unavailable; deterministic Python policy checks were used.")
        return result.model_copy(
            update={
                "engine": "python_fallback",
                "policy_version": POLICY_VERSION,
                "fallback_reason": reason,
                "warnings": warnings,
            }
        )

    @staticmethod
    def _ownership_known(
        resource: TerraformResourceChange,
        evidence: list[EvidenceItem],
    ) -> bool:
        tags = resource.tags or {}
        tag_owner = next(
            (value for key, value in tags.items() if key.lower() in {"owner", "team", "service_owner"}),
            None,
        )
        if tag_owner:
            return True
        jira = value_for(evidence, "jira")
        return bool(jira.get("issue_key"))

    @staticmethod
    def _message(item: object) -> str:
        if isinstance(item, dict):
            return str(item.get("msg") or item.get("message") or "Policy warning")
        return str(item)

    @classmethod
    def _violation(cls, item: dict[str, Any]) -> PolicyViolation:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        return PolicyViolation(
            code=str(metadata.get("code") or "OPA_POLICY_DENIAL"),
            message=cls._message(item),
            severity=str(metadata.get("severity") or "critical"),  # type: ignore[arg-type]
        )


default_policy_evaluator = ConftestPolicyEvaluator()
