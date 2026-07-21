from __future__ import annotations

import json
from pathlib import Path

from app.models import ScenarioDefinition
from integrations.terraform_parser import parse_terraform_plan


REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_DIR = REPO_ROOT / "fixtures" / "scenarios"
TERRAFORM_DIR = REPO_ROOT / "fixtures" / "terraform"


def test_all_scenario_fixtures_load_successfully() -> None:
    scenario_files = sorted(SCENARIO_DIR.glob("*.json"))
    assert {path.stem for path in scenario_files} == {
        "safe",
        "dependency",
        "destructive",
        "production",
        "conflicting",
        "missing_evidence",
    }

    for path in scenario_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenario = ScenarioDefinition.model_validate(payload)
        assert (REPO_ROOT / scenario.terraform_plan_file).exists()


def test_all_terraform_fixtures_parse_successfully() -> None:
    plan_files = sorted(TERRAFORM_DIR.glob("*.json"))
    assert {path.stem for path in plan_files} == {
        "safe_plan",
        "dependency_plan",
        "destructive_plan",
        "production_plan",
        "conflicting_plan",
        "missing_evidence_plan",
    }

    for path in plan_files:
        changes = parse_terraform_plan(path.relative_to(REPO_ROOT))
        assert len(changes) == 1

