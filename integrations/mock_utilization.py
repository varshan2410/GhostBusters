"""Mock utilization evidence tool."""

from __future__ import annotations

from typing import Any

from app.models import EvidenceItem, ScenarioDefinition, TerraformResourceChange

from integrations.base import build_evidence_item, unavailable_item


class MockUtilizationTool:
    name = "utilization"

    def collect(
        self,
        scenario: ScenarioDefinition,
        resource: TerraformResourceChange,
    ) -> list[EvidenceItem]:
        utilization = scenario.utilization
        metadata = {
            "scenario": scenario.name,
            "resource_type": resource.resource_type,
        }
        if not utilization.get("available", True):
            return [
                unavailable_item(
                    source=self.name,
                    tool_name=self.name,
                    resource_id=resource.address,
                    claim="Utilization data unavailable",
                    reason=str(utilization.get("reason", "utilization telemetry unavailable")),
                    metadata=metadata,
                )
            ]

        value: dict[str, Any] = {
            "average_cpu_pct": utilization.get("average_cpu_pct"),
            "peak_cpu_pct": utilization.get("peak_cpu_pct"),
            "sample_window_days": utilization.get("sample_window_days"),
        }
        return [
            build_evidence_item(
                source=self.name,
                tool_name=self.name,
                claim="Observed average and peak utilization",
                value=value,
                resource_id=resource.address,
                freshness_status="fresh",
                reliability=float(utilization.get("reliability", 0.9)),
                metadata=metadata,
            )
        ]

