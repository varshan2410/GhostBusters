from __future__ import annotations

from dataclasses import replace

import pytest

from app.models import AgentNextAction, ObjectiveInterpretation
from app.settings import settings
from core.ai_client import AICallResult, AIClientError, GeminiAIClient, MockGeminiClient


def _interpretation() -> ObjectiveInterpretation:
    return ObjectiveInterpretation(
        original_objective="reduce cost safely",
        objective_type="cost_optimization",
        normalized_goal="Reduce cost safely",
        plain_language_summary="Cost optimization review.",
    )


class FallbackGeminiClient(GeminiAIClient):
    def _load_client(self) -> None:
        self._client = object()
        self._types = object()

    def _generate(self, model, schema, prompt):  # type: ignore[no-untyped-def]
        if model == self.configuration.gemini_model:
            raise AIClientError("model_unavailable", "Gemini model is unavailable.", model=model)
        value = _interpretation() if schema is ObjectiveInterpretation else AgentNextAction(
            action="finish_investigation", reason="Evidence is complete.", question_being_answered="Is it complete?", expected_information="Complete evidence.", confidence=0.8
        )
        return AICallResult(value=value, model=model, planning_mode="gemini_fallback_model", latency_ms=2, usage_metadata={})


class BothUnavailableClient(FallbackGeminiClient):
    def _generate(self, model, schema, prompt):  # type: ignore[no-untyped-def]
        raise AIClientError("model_unavailable", "Gemini model is unavailable.", model=model)


class PrimaryGeminiClient(FallbackGeminiClient):
    def _generate(self, model, schema, prompt):  # type: ignore[no-untyped-def]
        return AICallResult(value=_interpretation(), model=model, planning_mode="gemini_primary", latency_ms=1, usage_metadata={"tokens": 3})


def test_missing_key_is_classified_without_exposing_a_secret() -> None:
    client = GeminiAIClient(replace(settings, gemini_api_key=None))
    with pytest.raises(AIClientError) as error:
        client.interpret_objective({"objective": "safe"})
    assert error.value.category == "missing_api_key"
    assert "local-test-key" not in error.value.safe_message


def test_primary_model_unavailable_uses_configured_fallback_model() -> None:
    client = FallbackGeminiClient(replace(settings, gemini_api_key="local-test-key"))
    result = client.interpret_objective({"objective": "reduce cost safely"})
    assert result.planning_mode == "gemini_fallback_model"
    assert result.model == settings.gemini_fallback_model


def test_primary_model_success_records_primary_mode() -> None:
    client = PrimaryGeminiClient(replace(settings, gemini_api_key="local-test-key"))
    result = client.interpret_objective({"objective": "reduce cost safely"})
    assert result.planning_mode == "gemini_primary"
    assert result.model == settings.gemini_model


def test_both_models_unavailable_are_reported_as_safe_provider_failure() -> None:
    client = BothUnavailableClient(replace(settings, gemini_api_key="local-test-key"))
    with pytest.raises(AIClientError) as error:
        client.interpret_objective({"objective": "reduce cost safely"})
    assert error.value.category == "model_unavailable"
    assert error.value.model == settings.gemini_fallback_model


def test_mock_provider_is_structured_and_offline() -> None:
    client = MockGeminiClient()
    result = client.interpret_objective({"objective": "reduce cost safely"})
    assert result.planning_mode == "mock_gemini"
    assert result.model == "mock-gemini"
    assert isinstance(result.value, ObjectiveInterpretation)
