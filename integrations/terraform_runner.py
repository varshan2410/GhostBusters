"""Controlled Terraform diff analysis and optional read-only CLI commands."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from app.models import GitHubTerraformChange, GitHubTerraformResourceChange
from app.settings import Settings, settings


class TerraformAnalysisError(Exception):
    pass


SAFE_ATTRIBUTES = ("instance_type", "machine_type", "size")


def validate_repository_path(path: str) -> str:
    value = PurePosixPath(path)
    if not path or value.is_absolute() or ".." in value.parts or "\\" in path:
        raise TerraformAnalysisError("Unsafe repository path rejected.")
    return value.as_posix()


def select_terraform_files(files: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    selected, skipped = [], []
    for item in files:
        path = validate_repository_path(str(item.get("filename", "")))
        if path.endswith(".tf") or path.endswith(".tf.json"):
            selected.append({**item, "filename": path})
        else:
            skipped.append(path)
    return selected, skipped


def _provider(resource_type: str) -> str:
    if resource_type.startswith("aws_"):
        return "aws"
    if resource_type.startswith("azurerm_"):
        return "azure"
    if resource_type.startswith("google_"):
        return "gcp"
    return resource_type.split("_", 1)[0]


def parse_github_terraform_change(repository: str, pr: dict[str, Any], files: list[dict[str, Any]], fetched: dict[str, str]) -> GitHubTerraformChange:
    selected, skipped = select_terraform_files(files)
    resources: list[GitHubTerraformResourceChange] = []
    warnings: list[str] = []
    for item in selected:
        path, patch, content = item["filename"], item.get("patch") or "", fetched.get(item["filename"], "")
        blocks = list(re.finditer(r'resource\s+"([A-Za-z0-9_]+)"\s+"([A-Za-z0-9_-]+)"\s*\{', content))
        resource_type, resource_name = (blocks[0].group(1), blocks[0].group(2)) if len(blocks) == 1 else ("unknown_resource", "unknown")
        changed: list[str] = []
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        for attribute in SAFE_ATTRIBUTES:
            old = re.search(rf'^-\s*{attribute}\s*=\s*"([^"]+)"', patch, re.MULTILINE)
            new = re.search(rf'^\+\s*{attribute}\s*=\s*"([^"]+)"', patch, re.MULTILINE)
            if old or new:
                changed.append(attribute)
                if old: before[attribute] = old.group(1)
                if new: after[attribute] = new.group(1)
        delete = item.get("status") == "removed" or bool(re.search(r"^-\s*resource\s+", patch, re.MULTILINE))
        replacement = delete and bool(re.search(r"^\+\s*resource\s+", patch, re.MULTILINE))
        actions = ["delete", "create"] if replacement else ["delete"] if delete else ["update"]
        if resource_type == "unknown_resource":
            warnings.append(f"Could not identify one unambiguous resource block in {path}.")
        resources.append(GitHubTerraformResourceChange(
            address=f"{resource_type}.{resource_name}", provider=_provider(resource_type), resource_type=resource_type,
            resource_name=resource_name, actions=actions, before=before or None, after=after or None,
            changed_attributes=changed, destructive=delete, replacement=replacement, source_file=path,
        ))
    head, base = pr.get("head", {}), pr.get("base", {})
    providers = {item.provider for item in resources if item.provider}
    environment = "production" if any("prod" in path.lower() for path in fetched) or any(re.search(r'(?i)environment\s*=\s*"production"', content) for content in fetched.values()) else None
    return GitHubTerraformChange(
        repository=repository, pull_request_number=int(pr["number"]), pull_request_url=pr.get("html_url", ""),
        pull_request_title=pr.get("title"), author=(pr.get("user") or {}).get("login"),
        base_branch=base.get("ref", ""), base_sha=base.get("sha", ""), head_branch=head.get("ref", ""), head_sha=head.get("sha", ""),
        changed_files=[item["filename"] for item in files], terraform_files=[item["filename"] for item in selected],
        resource_changes=resources, provider=next(iter(providers)) if len(providers) == 1 else None,
        environment=environment, warnings=warnings, unsupported_changes=skipped,
    )


class TerraformRunner:
    def __init__(self, configuration: Settings = settings) -> None:
        self.configuration = configuration

    def run(self, command: str, workspace: Path, plan_file: Path | None = None) -> subprocess.CompletedProcess[str]:
        if not self.configuration.terraform_cli_enabled:
            raise TerraformAnalysisError("Terraform CLI mode is disabled.")
        allowed = {"version": ["version"], "fmt-check": ["fmt", "-check"], "validate": ["validate"]}
        if command == "show-json" and plan_file is not None:
            args = ["show", "-json", str(plan_file.resolve())]
        elif command in allowed:
            args = allowed[command]
        else:
            raise TerraformAnalysisError("Terraform command is not allowed.")
        return subprocess.run([self.configuration.terraform_binary, *args], cwd=workspace.resolve(), capture_output=True, text=True, timeout=self.configuration.terraform_timeout_seconds, check=False)
