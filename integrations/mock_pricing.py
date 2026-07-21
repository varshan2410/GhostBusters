"""Mock pricing evidence tool."""

from __future__ import annotations

from typing import Any

from app.models import EvidenceItem, ScenarioDefinition, TerraformResourceChange

from integrations.base import EvidenceTool, build_evidence_item, unavailable_item


class MockPricingTool:
    name = "pricing"

    def collect(
        self,
        scenario: ScenarioDefinition,
        resource: TerraformResourceChange,
    ) -> list[EvidenceItem]:
        pricing = scenario.pricing
        metadata = {
            "scenario": scenario.name,
            "resource_type": resource.resource_type,
        }
        if not pricing.get("available", True):
            return [
                unavailable_item(
                    source=self.name,
                    tool_name=self.name,
                    resource_id=resource.address,
                    claim="Pricing data unavailable",
                    reason=str(pricing.get("reason", "pricing export unavailable")),
                    metadata=metadata,
                )
            ]

        value: dict[str, Any] = {
            "current_monthly_cost": pricing.get("current_monthly_cost"),
            "proposed_monthly_cost": pricing.get("proposed_monthly_cost"),
            "currency": pricing.get("currency", "USD"),
        }
        return [
            build_evidence_item(
                source=self.name,
                tool_name=self.name,
                claim="Estimated current and optimized monthly cost",
                value=value,
                resource_id=resource.address,
                freshness_status="fresh",
                reliability=float(pricing.get("reliability", 0.95)),
                metadata=metadata,
            )
        ]

