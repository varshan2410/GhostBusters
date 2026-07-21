from __future__ import annotations

import json
from pathlib import Path

from app.models import ScenarioDefinition, TerraformResourceChange
from integrations.terraform_parser import parse_terraform_plan


REPO_ROOT = Path(__file__).resolve().parent.parent


def load_scenario(name: str) -> ScenarioDefinition:
    path = REPO_ROOT / "fixtures" / "scenarios" / f"{name}.json"
    return ScenarioDefinition.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_resource(name: str) -> TerraformResourceChange:
    scenario = load_scenario(name)
    return parse_terraform_plan(scenario.terraform_plan_file)[0]

