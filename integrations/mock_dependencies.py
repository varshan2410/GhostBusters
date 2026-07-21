"""Mock dependency evidence tool."""

from __future__ import annotations

from typing import Any

from app.models import EvidenceItem, ScenarioDefinition, TerraformResourceChange

from integrations.base import build_evidence_item, unavailable_item


class MockDependencyTool:
    name = "dependencies"

    def collect(
        self,
        scenario: ScenarioDefinition,
        resource: TerraformResourceChange,
    ) -> list[EvidenceItem]:
        dependencies = scenario.dependencies
        metadata = {
            "scenario": scenario.name,
            "resource_type": resource.resource_type,
        }
        if not dependencies.get("available", True):
            return [
                unavailable_item(
                    source=self.name,
                    tool_name=self.name,
                    resource_id=resource.address,
                    claim="Dependency data unavailable",
                    reason=str(dependencies.get("reason", "dependency graph unavailable")),
                    metadata=metadata,
                )
            ]

        active_dependencies = dependencies.get("active_downstream_dependencies", [])
        blocking_services = dependencies.get("blocking_services", [])
        value: dict[str, Any] = {
            "active_downstream_dependencies": active_dependencies,
            "blocking_services": blocking_services,
            "has_active_dependencies": bool(active_dependencies or blocking_services),
        }
        return [
            build_evidence_item(
                source=self.name,
                tool_name=self.name,
                claim="Downstream dependency footprint",
                value=value,
                resource_id=resource.address,
                freshness_status="fresh",
                reliability=float(dependencies.get("reliability", 0.88)),
                metadata=metadata,
            )
        ]

