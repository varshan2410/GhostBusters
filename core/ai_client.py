"""Optional, structured AI provider boundary.

The provider can propose typed data, but it never receives executable tools and
never performs workflow mutations itself.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.models import AgentNextAction, ObjectiveInterpretation
from app.settings import Settings, settings


T = TypeVar("T", bound=BaseModel)


class AIClientError(Exception):
    """Sanitized provider failure with a stable category."""

    def __init__(self, category: str, safe_message: str, *, model: str | None = None) -> None:
        super().__init__(safe_message)
        self.category = category
        self.safe_message = safe_message
        self.model = model


@dataclass(frozen=True, slots=True)
class AICallResult:
    value: BaseModel
    model: str
    planning_mode: str
    latency_ms: int
    usage_metadata: dict[str, Any]


class StructuredAIClient(Protocol):
    def interpret_objective(self, payload: dict[str, Any]) -> AICallResult: ...

    def propose_next_action(self, payload: dict[str, Any]) -> AICallResult: ...


def _safe_category(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None)
    message = str(exc).lower()
    if status == 429 or "rate limit" in message or "resource exhausted" in message:
        return "rate_limited"
    if status in {401, 403} or "permission" in message or "forbidden" in message:
        return "permission_denied"
    if status == 404 or "not found" in message or "unsupported model" in message:
        return "model_unavailable"
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if isinstance(exc, (ValidationError, ValueError, TypeError, json.JSONDecodeError)):
        return "schema_validation_failed"
    return "provider_error"


class GeminiAIClient:
    """Thin official google-genai client with model fallback."""

    def __init__(self, configuration: Settings = settings) -> None:
        self.configuration = configuration
        self._client: Any | None = None
        self._types: Any | None = None
        self.active_model: str | None = None
        self.active_mode: str | None = None

    def _load_client(self) -> None:
        if self._client is not None:
            return
        if not self.configuration.gemini_api_key:
            raise AIClientError("missing_api_key", "Gemini API key is not configured.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise AIClientError("sdk_unavailable", "The google-genai SDK is unavailable.") from exc
        try:
            self._client = genai.Client(
                api_key=self.configuration.gemini_api_key,
                http_options=types.HttpOptions(
                    api_version=self.configuration.gemini_api_version,
                    timeout=int(self.configuration.gemini_timeout_seconds * 1000),
                ),
            )
            self._types = types
        except Exception as exc:
            raise AIClientError(_safe_category(exc), "Gemini client configuration failed.") from exc

    def _generate(self, model: str, schema: type[T], prompt: str) -> AICallResult:
        self._load_client()
        assert self._client is not None and self._types is not None
        started = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=model,
                contents=prompt,
                config=self._types.GenerateContentConfig(
                    temperature=self.configuration.gemini_temperature,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, schema):
                value = parsed
            elif isinstance(parsed, dict):
                value = schema.model_validate(parsed)
            else:
                text = getattr(response, "text", None)
                if not text:
                    raise ValueError("empty structured response")
                value = schema.model_validate_json(text)
        except Exception as exc:
            category = _safe_category(exc)
            raise AIClientError(category, "Gemini returned an unusable response.", model=model) from exc
        return AICallResult(
            value=value,
            model=model,
            planning_mode="gemini_primary" if model == self.configuration.gemini_model else "gemini_fallback_model",
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            usage_metadata={},
        )

    def _call(self, schema: type[T], prompt: str) -> AICallResult:
        models = [self.active_model] if self.active_model else [self.configuration.gemini_model]
        if not self.active_model:
            models.append(self.configuration.gemini_fallback_model)
        last_error: AIClientError | None = None
        for index, model in enumerate(dict.fromkeys(models)):
            if not model:
                continue
            try:
                result = self._generate(model, schema, prompt)
                self.active_model = result.model
                self.active_mode = result.planning_mode
                return result
            except AIClientError as exc:
                last_error = exc
                can_try_fallback = exc.category in {"model_unavailable", "permission_denied"}
                if index == 0 and can_try_fallback:
                    continue
                raise
        raise last_error or AIClientError("model_unavailable", "No Gemini model is configured.")

    def interpret_objective(self, payload: dict[str, Any]) -> AICallResult:
        prompt = json.dumps({"task": "interpret_objective", "input": payload}, sort_keys=True)
        return self._call(ObjectiveInterpretation, prompt)

    def propose_next_action(self, payload: dict[str, Any]) -> AICallResult:
        prompt = json.dumps({"task": "propose_next_action", "input": payload}, sort_keys=True)
        return self._call(AgentNextAction, prompt)


class MockGeminiClient:
    """Offline provider for demonstrations and tests; never claims real Gemini."""

    def _result(self, value: BaseModel, purpose: str) -> AICallResult:
        return AICallResult(value=value, model="mock-gemini", planning_mode="mock_gemini", latency_ms=0, usage_metadata={"provider": "mock", "purpose": purpose})

    def interpret_objective(self, payload: dict[str, Any]) -> AICallResult:
        objective = str(payload.get("objective", "")).strip()
        lowered = objective.lower()
        if any(term in lowered for term in ("safe", "risk", "production", "protect")):
            objective_type = "safety_review"
        elif any(term in lowered for term in ("refresh", "current", "recent")):
            objective_type = "evidence_refresh"
        elif any(term in lowered for term in ("explain", "understand")):
            objective_type = "explain_change"
        elif any(term in lowered for term in ("cost", "save", "rightsize", "spend")):
            objective_type = "cost_optimization"
        else:
            objective_type = "unsupported"
        return self._result(
            ObjectiveInterpretation(
                original_objective=objective,
                objective_type=objective_type,
                normalized_goal=objective or "Review this infrastructure change safely.",
                constraints=["No direct infrastructure mutation", "Human approval is required for remediation"],
                assumptions=["Prepared Terraform fixture is authoritative for the demo"],
                ambiguities=[],
                plain_language_summary=f"Mock Gemini classified this as a {objective_type.replace('_', ' ')} investigation.",
            ),
            "interpret_objective",
        )

    def propose_next_action(self, payload: dict[str, Any]) -> AICallResult:
        available = list(payload.get("available_tools", []))
        executed = set(payload.get("executed_tools", []))
        mandatory = list(payload.get("mandatory_tools", []))
        objective_type = payload.get("objective_type")
        preferred_order = {
            "cost_optimization": ["pricing", "utilization", "dependencies", "jira", "git_activity"],
            "safety_review": ["dependencies", "utilization", "jira", "git_activity", "pricing"],
            "evidence_refresh": ["utilization", "pricing", "dependencies", "jira", "git_activity"],
            "explain_change": ["jira", "git_activity", "pricing", "utilization", "dependencies"],
        }.get(objective_type, mandatory or available)
        candidates = [name for name in preferred_order if name in available and name not in executed]
        if candidates:
            tool = candidates[0]
            reasons = {
                "pricing": "Cost impact needs authoritative pricing evidence.",
                "utilization": "Rightsizing needs historical utilization evidence.",
                "dependencies": "Remediation safety requires downstream dependency evidence.",
                "jira": "Project purpose and delivery status need business context.",
                "git_activity": "Recent repository activity can validate project status.",
            }
            return self._result(AgentNextAction(action="call_tool", tool_name=tool, reason=reasons.get(tool, "This registered evidence source is relevant."), question_being_answered=f"What can {tool} tell us?", expected_information=f"Usable {tool} evidence." , confidence=0.9), "propose_next_action")
        if payload.get("conflicts") or payload.get("unresolved_questions"):
            return self._result(AgentNextAction(action="request_human_context", reason="Evidence is complete enough to expose a genuine ambiguity for review.", question_being_answered="Is the proposed change safe in the current business context?", expected_information="Owner context that resolves the remaining ambiguity.", human_question="Can the owner confirm the workload context and whether this change is safe to apply?", confidence=0.76), "propose_next_action")
        return self._result(AgentNextAction(action="finish_investigation", reason="The mandatory evidence sources have been checked.", question_being_answered="Is evidence collection complete?", expected_information="No further mandatory evidence is missing.", confidence=0.88), "propose_next_action")


def build_ai_client(configuration: Settings = settings) -> StructuredAIClient | None:
    if not configuration.ai_enabled:
        return None
    if configuration.ai_provider.lower() == "mock":
        return MockGeminiClient()
    if configuration.ai_provider.lower() == "gemini":
        return GeminiAIClient(configuration)
    return None
