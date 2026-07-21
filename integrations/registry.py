"""Registry for available mock evidence tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from integrations.base import EvidenceTool
from integrations.mock_dependencies import MockDependencyTool
from integrations.mock_git_activity import MockGitActivityTool
from integrations.mock_jira import MockJiraTool
from integrations.mock_pricing import MockPricingTool
from integrations.mock_utilization import MockUtilizationTool


@dataclass(slots=True)
class ToolRegistry:
    _tools: dict[str, EvidenceTool] = field(default_factory=dict)

    def __init__(self, tools: Iterable[EvidenceTool] | None = None) -> None:
        self._tools = {}
        if tools is not None:
            for tool in tools:
                self.register(tool)

    def register(self, tool: EvidenceTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> EvidenceTool | None:
        return self._tools.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools.keys())

    def items(self) -> tuple[tuple[str, EvidenceTool], ...]:
        return tuple(self._tools.items())


default_registry = ToolRegistry(
    tools=(
        MockPricingTool(),
        MockUtilizationTool(),
        MockJiraTool(),
        MockGitActivityTool(),
        MockDependencyTool(),
    )
)

