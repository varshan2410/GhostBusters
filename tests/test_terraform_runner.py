from __future__ import annotations

import pytest

from integrations.terraform_runner import TerraformAnalysisError, parse_github_terraform_change, select_terraform_files, validate_repository_path


def pr() -> dict:
    return {"number": 42, "html_url": "https://github.test/demo/infra/pull/42", "title": "Resize", "user": {"login": "dev"}, "head": {"ref": "resize", "sha": "head"}, "base": {"ref": "main", "sha": "base"}}


@pytest.mark.parametrize(("resource_type", "provider", "attribute"), [("aws_instance", "aws", "instance_type"), ("azurerm_linux_virtual_machine", "azure", "size"), ("google_compute_instance", "gcp", "machine_type")])
def test_diff_parser_detects_provider_and_size(resource_type: str, provider: str, attribute: str) -> None:
    content = f'resource "{resource_type}" "app" {{\n  {attribute} = "large"\n}}\n'
    files = [{"filename": "infra/main.tf", "status": "modified", "patch": f'-  {attribute} = "small"\n+  {attribute} = "large"'}]
    result = parse_github_terraform_change("demo/infra", pr(), files, {"infra/main.tf": content})
    assert result.provider == provider
    assert result.resource_changes[0].changed_attributes == [attribute]


def test_file_selection_skips_unrelated_and_rejects_traversal() -> None:
    selected, skipped = select_terraform_files([{"filename": "main.tf"}, {"filename": "README.md"}])
    assert [item["filename"] for item in selected] == ["main.tf"]
    assert skipped == ["README.md"]
    with pytest.raises(TerraformAnalysisError):
        validate_repository_path("../secret.tf")


def test_delete_replacement_and_production_are_hard_signals() -> None:
    files = [{"filename": "production/main.tf", "status": "modified", "patch": '-resource "aws_instance" "app" {\n+resource "aws_instance" "app" {'}]
    result = parse_github_terraform_change("demo/infra", pr(), files, {"production/main.tf": 'resource "aws_instance" "app" {}'})
    assert result.environment == "production"
    assert result.resource_changes[0].destructive is True
    assert result.resource_changes[0].replacement is True
