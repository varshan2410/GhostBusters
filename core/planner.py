"""Dynamic investigation planning for one Terraform resource."""

from __future__ import annotations

from app.models import InvestigationPlan, InvestigationQuestion, ScenarioDefinition, TerraformResourceChange
from integrations.registry import ToolRegistry


NORMAL_TOOLS = ("pricing", "utilization", "jira", "git_activity", "dependencies")


def _add_question(
    questions: list[InvestigationQuestion],
    question_id: str,
    question: str,
    sources: list[str],
) -> None:
    questions.append(
        InvestigationQuestion(
            id=question_id,
            question=question,
            required_evidence_sources=sources,
        )
    )


def create_investigation_plan(
    goal: str,
    scenario: ScenarioDefinition,
    resource: TerraformResourceChange,
    tool_registry: ToolRegistry,
) -> InvestigationPlan:
    selected: list[str] = []
    skipped: list[str] = []
    notes = [
        "Terraform change inspected before evidence tool selection.",
        f"Resource actions: {', '.join(resource.actions)}.",
    ]
    questions: list[InvestigationQuestion] = []

    available_tools = set(tool_registry.names())

    explicit_audit = scenario.name == "conflicting"
    if resource.destructive and not explicit_audit:
        notes.append("Destructive Terraform action detected; normal optimization evidence was skipped.")
        return InvestigationPlan(
            goal=goal,
            resource_id=resource.address,
            questions=[
                InvestigationQuestion(
                    id="policy_destructive",
                    question="Does policy allow a Terraform delete or replacement?",
                    required_evidence_sources=[],
                    status="skipped",
                    resolution_summary="Direct policy evaluation required.",
                )
            ],
            selected_tools=[],
            skipped_tools=[tool for tool in NORMAL_TOOLS if tool in available_tools],
            planning_notes=notes,
        )
    if resource.destructive and explicit_audit:
        notes.append("Destructive action detected, but explicit conflict-audit scenario requires contextual evidence.")

    if (resource.environment or "").lower() == "production":
        notes.append("Production resource detected; normal optimization was skipped for policy evaluation.")
        return InvestigationPlan(
            goal=goal,
            resource_id=resource.address,
            questions=[
                InvestigationQuestion(
                    id="policy_production",
                    question="Does policy allow automated remediation in production?",
                    required_evidence_sources=[],
                    status="skipped",
                    resolution_summary="Direct policy evaluation required.",
                )
            ],
            selected_tools=[],
            skipped_tools=[tool for tool in NORMAL_TOOLS if tool in available_tools],
            planning_notes=notes,
        )

    def select(tool_name: str, reason: str) -> None:
        if tool_name in available_tools and tool_name not in selected:
            selected.append(tool_name)
            notes.append(f"Selected {tool_name}: {reason}")

    instance_type_changed = resource.current_instance_type != resource.proposed_instance_type
    dependency_known = bool(scenario.dependencies.get("active_downstream_dependencies")) or bool(
        scenario.dependencies.get("blocking_services")
    )
    evidence_missing = not scenario.pricing.get("available", True) or not scenario.dependencies.get("available", True)
    conflict_possible = (
        scenario.jira.get("status") == "completed"
        and int(scenario.git_activity.get("recent_commit_count", 0)) > 0
    )

    if instance_type_changed and not dependency_known and not conflict_possible:
        select("pricing", "Instance type changed and cost impact must be quantified.")
        _add_question(questions, "cost_impact", "What is the cost impact of the proposed instance type?", ["pricing"])
    elif instance_type_changed:
        skipped.append("pricing")
        notes.append("Skipped pricing: dependency or conflict risk should be understood before cost optimization.")

    if instance_type_changed or "cost" in goal.lower() or "right" in goal.lower():
        select("utilization", "Rightsizing needs utilization evidence.")
        _add_question(questions, "utilization", "Is utilization low enough for remediation?", ["utilization"])

    select("jira", "Project purpose and work status need context.")
    _add_question(questions, "project_context", "Is the project context clear enough?", ["jira"])

    jira_completed_or_inactive = str(scenario.jira.get("status", "")).lower() in {"completed", "inactive"}
    if jira_completed_or_inactive or conflict_possible:
        select("git_activity", "Jira status should be checked against recent git activity.")
        _add_question(questions, "git_activity", "Does recent git activity contradict Jira status?", ["git_activity"])
    else:
        skipped.append("git_activity")
        notes.append("Skipped git_activity: Jira status does not yet suggest inactivity.")

    if instance_type_changed or dependency_known or evidence_missing:
        select("dependencies", "Remediation may affect downstream workloads.")
        _add_question(questions, "dependencies", "Are there active downstream dependencies?", ["dependencies"])

    for tool_name in NORMAL_TOOLS:
        if tool_name in available_tools and tool_name not in selected and tool_name not in skipped:
            skipped.append(tool_name)
            notes.append(f"Skipped {tool_name}: not relevant for this Terraform change.")

    return InvestigationPlan(
        goal=goal,
        resource_id=resource.address,
        questions=questions,
        selected_tools=selected,
        skipped_tools=skipped,
        planning_notes=notes,
    )
