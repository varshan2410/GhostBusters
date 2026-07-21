"""Mock git activity evidence tool."""

from __future__ import annotations

from typing import Any

from app.models import EvidenceItem, ScenarioDefinition, TerraformResourceChange

from integrations.base import build_evidence_item, unavailable_item


class MockGitActivityTool:
    name = "git_activity"

    def collect(
        self,
        scenario: ScenarioDefinition,
        resource: TerraformResourceChange,
    ) -> list[EvidenceItem]:
        git_activity = scenario.git_activity
        metadata = {
            "scenario": scenario.name,
            "resource_type": resource.resource_type,
        }
        if not git_activity.get("available", True):
            return [
                unavailable_item(
                    source=self.name,
                    tool_name=self.name,
                    resource_id=resource.address,
                    claim="Git activity data unavailable",
                    reason=str(git_activity.get("reason", "git history unavailable")),
                    metadata=metadata,
                )
            ]

        value: dict[str, Any] = {
            "recent_commit_count": git_activity.get("recent_commit_count"),
            "days_since_last_commit": git_activity.get("days_since_last_commit"),
            "branch": git_activity.get("branch"),
        }
        return [
            build_evidence_item(
                source=self.name,
                tool_name=self.name,
                claim="Recent git activity",
                value=value,
                resource_id=resource.address,
                freshness_status="fresh",
                reliability=float(git_activity.get("reliability", 0.8)),
                metadata=metadata,
            )
        ]

