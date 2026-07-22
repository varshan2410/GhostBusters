"""Registry for fixture-backed cloud provider adapters."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

from app.models import CloudResource
from integrations.cloud_adapters import AWSCloudAdapter, AzureCloudAdapter, CloudProviderAdapter, GCPCloudAdapter


@dataclass(slots=True)
class CloudProviderRegistry:
    _adapters: dict[str, CloudProviderAdapter]

    def __init__(self, adapters: Iterable[CloudProviderAdapter] = ()) -> None:
        self._adapters = {adapter.provider: adapter for adapter in adapters}

    def register(self, adapter: CloudProviderAdapter) -> None:
        self._adapters[adapter.provider] = adapter

    def get(self, provider: str) -> CloudProviderAdapter | None:
        return self._adapters.get(provider)

    def names(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def list_resources(self, scope: str) -> list:
        providers = self.names() if scope == "multi_cloud" else (scope,)
        resources = []
        for provider in providers:
            adapter = self.get(provider)
            if adapter is not None:
                resources.extend(adapter.list_resources())
        return resources


def build_fixture_cloud_registry() -> CloudProviderRegistry:
    path = Path(__file__).resolve().parent.parent / "fixtures" / "cloud_inventory.json"
    resources = [CloudResource.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]
    grouped = {provider: [item for item in resources if item.provider == provider] for provider in ("aws", "azure", "gcp")}
    return CloudProviderRegistry(
        [
            AWSCloudAdapter(grouped["aws"]),
            AzureCloudAdapter(grouped["azure"]),
            GCPCloudAdapter(grouped["gcp"]),
        ]
    )


default_cloud_registry = build_fixture_cloud_registry()
