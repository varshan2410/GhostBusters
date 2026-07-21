from __future__ import annotations

import json

import pytest

from app.models import EvidenceItem, InvestigationPlan, RunStatus, ScenarioDefinition, TerraformResourceChange
from core.investigator import collect_evidence
from core.reasoning_engine import analyze_resource
from core.retry import RetryConfig, RetryExecutor
from core.run_store import InMemoryRunStore
from core.workflow_service import WorkflowService
from integrations.registry import ToolRegistry, default_registry
from tests.scenario_helpers import load_resource, load_scenario


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


class HttpFailure(Exception):
    def __init__(self, status_code: int, retry_after: float | None = None) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.retry_after = retry_after


def executor(clock: FakeClock | None = None, **overrides: object) -> RetryExecutor:
    values = {
        "enabled": True,
        "max_attempts": 3,
        "initial_delay_seconds": 0.1,
        "multiplier": 2.0,
        "max_delay_seconds": 1.0,
        "jitter_seconds": 0.0,
        "timeout_seconds": 1.0,
    }
    values.update(overrides)
    fake_clock = clock or FakeClock()
    return RetryExecutor(
        RetryConfig(**values),  # type: ignore[arg-type]
        sleep=fake_clock.sleep,
        monotonic=fake_clock.monotonic,
        random_value=lambda: 0.5,
    )


def flaky_operation(failures: list[BaseException], value: object = "ok"):
    attempts = 0

    def operation():  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        if failures:
            raise failures.pop(0)
        return value

    return operation, lambda: attempts


def test_tool_succeeds_on_first_attempt() -> None:
    operation, attempts = flaky_operation([])
    result = executor().execute("jira", operation)

    assert result.value == "ok"
    assert result.result.success is True
    assert result.result.attempts == 1
    assert attempts() == 1


@pytest.mark.parametrize("failure_count", [1, 2])
def test_temporary_failure_succeeds_on_later_attempt(failure_count: int) -> None:
    operation, attempts = flaky_operation([ConnectionError("temporary")] * failure_count)
    result = executor().execute("jira", operation)

    assert result.result.success is True
    assert result.result.attempts == failure_count + 1
    assert attempts() == failure_count + 1


def test_retryable_failure_exhausts_maximum_attempts() -> None:
    operation, attempts = flaky_operation([ConnectionError("down")] * 3)
    result = executor().execute("jira", operation)

    assert result.result.success is False
    assert result.result.attempts == 3
    assert result.result.retry_exhausted is True
    assert result.result.failure_category == "temporary_network_failure"
    assert attempts() == 3


def test_timeout_is_retried() -> None:
    operation, attempts = flaky_operation([TimeoutError("slow")])
    result = executor().execute("utilization", operation)

    assert result.result.success is True
    assert result.result.attempts == 2
    assert attempts() == 2
    assert any(
        item.failure_category == "timeout" for item in result.result.events
    )


@pytest.mark.parametrize("status", [429, 503])
def test_retryable_http_statuses_are_retried(status: int) -> None:
    operation, attempts = flaky_operation([HttpFailure(status)])
    result = executor().execute("pricing", operation)

    assert result.result.success is True
    assert attempts() == 2


def test_retry_after_is_respected_within_maximum() -> None:
    clock = FakeClock()
    operation, _ = flaky_operation([HttpFailure(429, retry_after=0.75)])

    executor(clock, max_delay_seconds=1.0).execute("jira", operation)

    assert clock.sleeps == [0.75]


@pytest.mark.parametrize("status, category", [(401, "authentication_failure"), (403, "authorization_failure")])
def test_authentication_and_authorization_failures_are_not_retried(
    status: int,
    category: str,
) -> None:
    operation, attempts = flaky_operation([HttpFailure(status)])
    result = executor().execute("jira", operation)

    assert result.result.success is False
    assert result.result.retryable is False
    assert result.result.failure_category == category
    assert attempts() == 1


def test_jitter_can_be_disabled_for_deterministic_tests() -> None:
    clock = FakeClock()
    operation, _ = flaky_operation([ConnectionError(), ConnectionError()])

    executor(clock, jitter_seconds=0.0).execute("jira", operation)

    assert clock.sleeps == [0.1, 0.2]


def test_maximum_delay_is_enforced_and_sleep_is_injected() -> None:
    clock = FakeClock()
    operation, _ = flaky_operation([ConnectionError(), ConnectionError()])

    executor(
        clock,
        initial_delay_seconds=5.0,
        multiplier=3.0,
        max_delay_seconds=0.4,
        jitter_seconds=0.2,
    ).execute("jira", operation)

    assert clock.sleeps == [0.4, 0.4]


def test_invalid_response_schema_is_not_retried() -> None:
    class InvalidTool:
        name = "jira"

        def __init__(self) -> None:
            self.calls = 0

        def collect(self, scenario, resource):  # type: ignore[no-untyped-def]
            self.calls += 1
            return {"invalid": True}

    tool = InvalidTool()
    plan = InvestigationPlan(goal="test", resource_id="resource", selected_tools=["jira"])
    scenario = load_scenario("safe")
    resource = load_resource("safe")

    evidence, records, _ = collect_evidence(
        plan, scenario, resource, ToolRegistry([tool]), executor()
    )

    assert tool.calls == 1
    assert records[0].external_call is not None
    assert records[0].external_call.failure_category == "invalid_response_schema"
    assert evidence[0].freshness_status == "unavailable"


def test_exhausted_retries_create_structured_unavailable_evidence() -> None:
    class OfflineUtilization:
        name = "utilization"

        def collect(self, scenario, resource):  # type: ignore[no-untyped-def]
            raise ConnectionError("secret-host.internal")

    plan = InvestigationPlan(
        goal="test", resource_id="resource", selected_tools=["utilization"]
    )
    evidence, records, missing = collect_evidence(
        plan,
        load_scenario("safe"),
        load_resource("safe"),
        ToolRegistry([OfflineUtilization()]),
        executor(),
    )

    item = evidence[0]
    execution = records[0].external_call
    assert execution is not None
    assert item.value is None
    assert item.freshness_status == "unavailable"
    assert item.metadata["attempts"] == 3
    assert item.metadata["retry_exhausted"] is True
    assert item.metadata["failure_category"] == "temporary_network_failure"
    assert "secret-host" not in json.dumps(item.model_dump(mode="json"))
    assert missing[0].critical is True


def registry_replacing(name: str, replacement: object) -> ToolRegistry:
    tools = [replacement if tool_name == name else tool for tool_name, tool in default_registry.items()]
    return ToolRegistry(tools)  # type: ignore[arg-type]


def test_missing_critical_evidence_lowers_confidence_and_prevents_approval_ready() -> None:
    class OfflineUtilization:
        name = "utilization"

        def collect(self, scenario, resource):  # type: ignore[no-untyped-def]
            raise TimeoutError("monitoring unavailable")

    scenario = load_scenario("safe")
    resource = load_resource("safe")
    baseline = analyze_resource(scenario.goal, scenario, resource, default_registry)
    degraded = analyze_resource(
        scenario.goal,
        scenario,
        resource,
        registry_replacing("utilization", OfflineUtilization()),
        retry_executor=executor(),
    )

    assert degraded.confidence.final_confidence < baseline.confidence.final_confidence
    assert degraded.final_status != "recommendation_ready"
    assert degraded.preferred_action in {"request_evidence", "keep", "abstain"}


def test_alternative_git_evidence_is_selected_when_jira_is_unavailable() -> None:
    class OfflineJira:
        name = "jira"

        def collect(self, scenario, resource):  # type: ignore[no-untyped-def]
            raise ConnectionError("jira unavailable")

    scenario = load_scenario("safe")
    decision = analyze_resource(
        scenario.goal,
        scenario,
        load_resource("safe"),
        registry_replacing("jira", OfflineJira()),
        retry_executor=executor(),
    )
    git_record = next(
        item for item in decision.tool_executions if item.tool_name == "git_activity"
    )

    assert git_record.external_call is not None
    assert any(
        event.event_type == "alternative_evidence_selected"
        for event in git_record.external_call.events
    )


def test_audit_retry_events_are_ordered_and_do_not_contain_sensitive_values() -> None:
    class FlakyJira:
        name = "jira"

        def __init__(self) -> None:
            self.calls = 0

        def collect(
            self,
            scenario: ScenarioDefinition,
            resource: TerraformResourceChange,
        ) -> list[EvidenceItem]:
            self.calls += 1
            if self.calls < 3:
                raise ConnectionError("Authorization: Bearer very-secret-token")
            return next(tool for name, tool in default_registry.items() if name == "jira").collect(
                scenario, resource
            )

    service = WorkflowService(
        InMemoryRunStore(),
        registry_replacing("jira", FlakyJira()),
        retry_executor=executor(),
    )
    run, _ = service.start_run_request("safe")
    events = [
        event
        for event in run.audit_events
        if event.details.get("tool_name") == "jira"
        and event.event_type.startswith("external_call_")
    ]

    assert [event.event_type for event in events] == [
        "external_call_started",
        "external_call_failed",
        "external_call_retry_scheduled",
        "external_call_started",
        "external_call_failed",
        "external_call_retry_scheduled",
        "external_call_started",
        "external_call_succeeded",
    ]
    serialized = json.dumps([event.model_dump(mode="json") for event in events])
    assert "very-secret-token" not in serialized
    assert "Authorization" not in serialized


def test_non_idempotent_operation_is_never_retried() -> None:
    operation, attempts = flaky_operation([ConnectionError("temporary")])

    result = executor().execute("future_github_pr_create", operation, idempotent=False)

    assert result.result.success is False
    assert attempts() == 1
