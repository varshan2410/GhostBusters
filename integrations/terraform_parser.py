"""Deterministic Terraform plan JSON parsing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import TerraformResourceChange


class TerraformPlanError(Exception):
    """Base error for Terraform plan parsing."""


class TerraformPlanPathError(TerraformPlanError):
    """Raised when a plan path cannot be resolved."""


class TerraformPlanFormatError(TerraformPlanError):
    """Raised when the plan JSON structure is malformed."""


REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve_plan_path(plan_file: str | Path) -> Path:
    path = Path(plan_file)
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        resolved = path.resolve()
    except OSError as exc:  # pragma: no cover - defensive on odd filesystems
        raise TerraformPlanPathError(f"Unable to resolve Terraform plan path: {plan_file}") from exc
    if not resolved.exists() or not resolved.is_file():
        raise TerraformPlanPathError(f"Terraform plan file not found: {resolved}")
    return resolved


def _load_plan_json(plan_path: Path) -> dict[str, Any]:
    try:
        return json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TerraformPlanFormatError(
            f"Malformed Terraform plan JSON in {plan_path}: {exc.msg}"
        ) from exc


def _extract_tags(before: Any, after: Any) -> dict[str, Any] | None:
    for payload in (after, before):
        if isinstance(payload, dict):
            tags = payload.get("tags")
            if isinstance(tags, dict):
                return dict(tags)
    return None


def _extract_environment(before: Any, after: Any, tags: dict[str, Any] | None) -> str | None:
    if tags:
        for key in ("Environment", "environment", "env"):
            value = tags.get(key)
            if isinstance(value, str) and value:
                return value
    for payload in (after, before):
        if isinstance(payload, dict):
            value = payload.get("environment")
            if isinstance(value, str) and value:
                return value
    return None


def _extract_instance_type(payload: Any) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("instance_type")
        if isinstance(value, str) and value:
            return value
    return None


def _validate_payload(entry: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    change = entry.get("change")
    if not isinstance(change, dict):
        raise TerraformPlanFormatError(f"resource_changes[{index}].change must be an object")

    before = change.get("before")
    after = change.get("after")
    actions = change.get("actions")

    if before is not None and not isinstance(before, dict):
        raise TerraformPlanFormatError(f"resource_changes[{index}].change.before must be an object or null")
    if after is not None and not isinstance(after, dict):
        raise TerraformPlanFormatError(f"resource_changes[{index}].change.after must be an object or null")
    if not isinstance(actions, list):
        raise TerraformPlanFormatError(f"resource_changes[{index}].change.actions must be a list")

    normalized_actions = [str(action) for action in actions]
    return before, after, normalized_actions


def parse_terraform_plan(plan_file: str | Path) -> list[TerraformResourceChange]:
    """Parse resource changes from a Terraform plan JSON file."""

    plan_path = _resolve_plan_path(plan_file)
    plan = _load_plan_json(plan_path)

    resource_changes = plan.get("resource_changes")
    if resource_changes is None:
        return []
    if not isinstance(resource_changes, list):
        raise TerraformPlanFormatError("resource_changes must be a list")

    parsed: list[TerraformResourceChange] = []
    for index, entry in enumerate(resource_changes):
        if not isinstance(entry, dict):
            raise TerraformPlanFormatError(f"resource_changes[{index}] must be an object")

        address = entry.get("address")
        resource_type = entry.get("type")
        if not isinstance(address, str) or not address:
            raise TerraformPlanFormatError(f"resource_changes[{index}].address must be a string")
        if not isinstance(resource_type, str) or not resource_type:
            raise TerraformPlanFormatError(f"resource_changes[{index}].type must be a string")

        before, after, actions = _validate_payload(entry, index)
        tags = _extract_tags(before, after)
        parsed.append(
            TerraformResourceChange(
                address=address,
                resource_type=resource_type,
                actions=actions,
                before=before,
                after=after,
                environment=_extract_environment(before, after, tags),
                current_instance_type=_extract_instance_type(before),
                proposed_instance_type=_extract_instance_type(after),
                destructive="delete" in actions,
                tags=tags,
            )
        )

    return parsed

