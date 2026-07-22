"""Fixture-backed, read-only cloud provider adapters for Cloud Hunt Mode."""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any

from app.models import CloudProvider, CloudResource


class CloudProviderAdapter(ABC):
    provider: CloudProvider
    display_name: str
    fixture_backed = True

    @abstractmethod
    def list_resources(self) -> list[CloudResource]:
        """Return normalized resources from the controlled inventory fixture."""

    def get_resource_details(self, resource_id: str) -> CloudResource | None:
        return next((item for item in self.list_resources() if item.resource_id == resource_id), None)

    def _evidence(self, resource_id: str, key: str) -> dict[str, Any]:
        resource = self.get_resource_details(resource_id)
        if resource is None:
            return {"available": False, "reason": "resource not found"}
        return deepcopy(resource.metadata.get(key, {"available": False, "reason": f"{key} unavailable"}))

    def get_cost_evidence(self, resource_id: str) -> dict[str, Any]:
        return self._evidence(resource_id, "pricing")

    def get_utilization_evidence(self, resource_id: str) -> dict[str, Any]:
        return self._evidence(resource_id, "utilization")

    def get_dependency_evidence(self, resource_id: str) -> dict[str, Any]:
        return self._evidence(resource_id, "dependencies")

    def get_activity_evidence(self, resource_id: str) -> dict[str, Any]:
        return self._evidence(resource_id, "activity")

    def get_ownership_evidence(self, resource_id: str) -> dict[str, Any]:
        return self._evidence(resource_id, "ownership")

    def build_remediation_proposal(self, resource_id: str, action: str) -> dict[str, Any]:
        resource = self.get_resource_details(resource_id)
        if resource is None:
            raise ValueError(f"Unknown {self.provider} resource: {resource_id}")
        if not resource.infrastructure_as_code_managed or not resource.terraform_address:
            return {
                "managed": False,
                "message": "Resource is not currently managed by Terraform.",
                "recommended_next_steps": ["import into Terraform", "create Jira remediation task", "request platform-owner action"],
            }
        return {
            "managed": True,
            "terraform_address": resource.terraform_address,
            "action": action,
            "provider": self.provider,
            "resource_id": resource.resource_id,
            "note": "Simulated proposal only; no provider mutation was performed.",
        }


class AWSCloudAdapter(CloudProviderAdapter):
    provider = "aws"
    display_name = "AWS"

    def __init__(self, resources: list[CloudResource]) -> None:
        self._resources = resources

    def list_resources(self) -> list[CloudResource]:
        return [item.model_copy(deep=True) for item in self._resources]


class AzureCloudAdapter(CloudProviderAdapter):
    provider = "azure"
    display_name = "Azure"

    def __init__(self, resources: list[CloudResource]) -> None:
        self._resources = resources

    def list_resources(self) -> list[CloudResource]:
        return [item.model_copy(deep=True) for item in self._resources]


class GCPCloudAdapter(CloudProviderAdapter):
    provider = "gcp"
    display_name = "Google Cloud"

    def __init__(self, resources: list[CloudResource]) -> None:
        self._resources = resources

    def list_resources(self) -> list[CloudResource]:
        return [item.model_copy(deep=True) for item in self._resources]
