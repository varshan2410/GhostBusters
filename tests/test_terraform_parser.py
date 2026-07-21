from __future__ import annotations

from pathlib import Path

import pytest

from integrations.terraform_parser import (
    TerraformPlanFormatError,
    TerraformPlanPathError,
    parse_terraform_plan,
)


def test_safe_update_parsing_is_repository_relative(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    changes = parse_terraform_plan("fixtures/terraform/safe_plan.json")

    assert len(changes) == 1
    resource = changes[0]
    assert resource.address == "aws_instance.app"
    assert resource.resource_type == "aws_instance"
    assert resource.actions == ["update"]
    assert resource.environment == "staging"
    assert resource.current_instance_type == "m5.xlarge"
    assert resource.proposed_instance_type == "m5.large"
    assert resource.tags == {"Environment": "staging", "Name": "ghostbusters-app"}
    assert resource.destructive is False


def test_delete_action_is_marked_destructive() -> None:
    resource = parse_terraform_plan("fixtures/terraform/destructive_plan.json")[0]

    assert resource.actions == ["delete"]
    assert resource.destructive is True
    assert resource.after is None


def test_replace_action_combination_is_supported() -> None:
    resource = parse_terraform_plan("fixtures/terraform/conflicting_plan.json")[0]

    assert resource.actions == ["delete", "create"]
    assert resource.destructive is True
    assert resource.current_instance_type == "t3.medium"
    assert resource.proposed_instance_type == "m5.large"


def test_missing_resource_changes_returns_empty_list(tmp_path: Path) -> None:
    plan_file = tmp_path / "empty_plan.json"
    plan_file.write_text('{"format_version": "1.0"}', encoding="utf-8")

    assert parse_terraform_plan(plan_file) == []


def test_invalid_terraform_file_raises_clear_error() -> None:
    with pytest.raises(TerraformPlanPathError, match="Terraform plan file not found"):
        parse_terraform_plan("fixtures/terraform/not-a-real-plan.json")


def test_malformed_terraform_json_raises_clear_error(tmp_path: Path) -> None:
    plan_file = tmp_path / "malformed.json"
    plan_file.write_text('{"resource_changes": [', encoding="utf-8")

    with pytest.raises(TerraformPlanFormatError, match="Malformed Terraform plan JSON"):
        parse_terraform_plan(plan_file)
