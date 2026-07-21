"""Mock Jira evidence tool."""

from __future__ import annotations

from typing import Any

from app.models import EvidenceItem, ScenarioDefinition, TerraformResourceChange

from integrations.base import build_evidence_item, unavailable_item


class MockJiraTool:
    name = "jira"

    def collect(
        self,
        scenario: ScenarioDefinition,
        resource: TerraformResourceChange,
    ) -> list[EvidenceItem]:
        jira = scenario.jira
        metadata = {
            "scenario": scenario.name,
            "resource_type": resource.resource_type,
        }
        if not jira.get("available", True):
            return [
                unavailable_item(
                    source=self.name,
                    tool_name=self.name,
                    resource_id=resource.address,
                    claim="Jira evidence unavailable",
                    reason=str(jira.get("reason", "Jira connector unavailable")),
                    metadata=metadata,
                )
            ]

        value: dict[str, Any] = {
            "issue_key": jira.get("issue_key"),
            "status": jira.get("status"),
        }
        return [
            build_evidence_item(
                source=self.name,
                tool_name=self.name,
                claim="Jira delivery state",
                value=value,
                resource_id=resource.address,
                freshness_status="fresh",
                reliability=float(jira.get("reliability", 0.85)),
                metadata=metadata,
            )
        ]

