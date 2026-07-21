"""Central retry, timeout classification, and exponential-backoff support."""

from __future__ import annotations

import random
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Generic, TypeVar

import httpx
from pydantic import ValidationError

from app.models import ExternalCallEvent, ExternalCallExecutionResult
from app.settings import settings


T = TypeVar("T")
RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}
AUTHENTICATION_HTTP_STATUSES = {401, 403}


class ExternalCallError(Exception):
    """A safe, classified external-provider failure."""

    def __init__(
        self,
        safe_message: str,
        *,
        category: str,
        retryable: bool,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.category = category
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


class InvalidEvidenceResponseError(ExternalCallError):
    def __init__(self) -> None:
        super().__init__(
            "The evidence provider returned an invalid response.",
            category="invalid_response_schema",
            retryable=False,
        )


class InvalidExternalConfigurationError(ExternalCallError):
    def __init__(self) -> None:
        super().__init__(
            "The external provider configuration is invalid.",
            category="invalid_configuration",
            retryable=False,
        )


@dataclass(frozen=True, slots=True)
class RetryConfig:
    enabled: bool = True
    max_attempts: int = 3
    initial_delay_seconds: float = 0.25
    multiplier: float = 2.0
    max_delay_seconds: float = 2.0
    jitter_seconds: float = 0.10
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.multiplier < 1:
            raise ValueError("retry multiplier must be at least 1")
        if self.jitter_seconds < 0:
            raise ValueError("retry jitter cannot be negative")
        if self.timeout_seconds <= 0:
            raise ValueError("external call timeout must be positive")

    @classmethod
    def from_settings(cls) -> "RetryConfig":
        return cls(
            enabled=settings.external_retry_enabled,
            max_attempts=settings.external_retry_max_attempts,
            initial_delay_seconds=settings.external_retry_initial_delay_seconds,
            multiplier=settings.external_retry_multiplier,
            max_delay_seconds=settings.external_retry_max_delay_seconds,
            jitter_seconds=settings.external_retry_jitter_seconds,
            timeout_seconds=settings.external_call_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class ClassifiedFailure:
    category: str
    retryable: bool
    safe_message: str
    failure_type: str
    retry_after_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class RetryExecution(Generic[T]):
    value: T | None
    result: ExternalCallExecutionResult


class RetryExecutor:
    """Execute idempotent external reads with bounded, observable retries."""

    def __init__(
        self,
        config: RetryConfig | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        random_value: Callable[[], float] = random.random,
        cancelled: Callable[[], bool] | None = None,
        retryable_exceptions: tuple[type[BaseException], ...] = (),
        non_retryable_exceptions: tuple[type[BaseException], ...] = (),
    ) -> None:
        self.config = config or RetryConfig.from_settings()
        self.sleep = sleep
        self.monotonic = monotonic
        self.random_value = random_value
        self.cancelled = cancelled or (lambda: False)
        self.retryable_exceptions = retryable_exceptions
        self.non_retryable_exceptions = non_retryable_exceptions

    def execute(
        self,
        tool_name: str,
        operation: Callable[[], T],
        *,
        idempotent: bool = True,
    ) -> RetryExecution[T]:
        maximum_attempts = self.config.max_attempts if self.config.enabled and idempotent else 1
        events: list[ExternalCallEvent] = []
        overall_started = self.monotonic()
        last_failure: ClassifiedFailure | None = None

        for attempt in range(1, maximum_attempts + 1):
            if self.cancelled():
                last_failure = ClassifiedFailure(
                    category="cancelled",
                    retryable=False,
                    safe_message=f"{tool_name} call was cancelled safely.",
                    failure_type="Cancelled",
                )
                events.append(self._failure_event("external_call_failed", attempt, maximum_attempts, last_failure, 0))
                break

            attempt_started = self.monotonic()
            events.append(
                ExternalCallEvent(
                    event_type="external_call_started",
                    attempt=attempt,
                    maximum_attempts=maximum_attempts,
                )
            )
            try:
                value = operation()
                attempt_elapsed = self.monotonic() - attempt_started
                if attempt_elapsed > self.config.timeout_seconds:
                    raise TimeoutError(f"{tool_name} exceeded its configured timeout")
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                last_failure = self.classify(exc, tool_name)
                elapsed_ms = self._milliseconds(self.monotonic() - attempt_started)
                events.append(
                    self._failure_event(
                        "external_call_failed", attempt, maximum_attempts, last_failure, elapsed_ms
                    )
                )
                should_retry = last_failure.retryable and attempt < maximum_attempts
                if not should_retry:
                    break
                delay = self._retry_delay(attempt, last_failure.retry_after_seconds)
                events.append(
                    ExternalCallEvent(
                        event_type="external_call_retry_scheduled",
                        attempt=attempt,
                        maximum_attempts=maximum_attempts,
                        failure_category=last_failure.category,
                        retryable=True,
                        retry_delay_seconds=delay,
                        elapsed_ms=elapsed_ms,
                        details={"rate_limited": last_failure.category == "rate_limited"},
                    )
                )
                if self.cancelled():
                    last_failure = ClassifiedFailure(
                        category="cancelled",
                        retryable=False,
                        safe_message=f"{tool_name} retry was cancelled safely.",
                        failure_type="Cancelled",
                    )
                    break
                self.sleep(delay)
                continue

            elapsed_ms = self._milliseconds(self.monotonic() - overall_started)
            events.append(
                ExternalCallEvent(
                    event_type="external_call_succeeded",
                    attempt=attempt,
                    maximum_attempts=maximum_attempts,
                    retryable=False,
                    elapsed_ms=elapsed_ms,
                )
            )
            return RetryExecution(
                value=value,
                result=ExternalCallExecutionResult(
                    tool_name=tool_name,
                    success=True,
                    attempts=attempt,
                    retry_exhausted=False,
                    retryable=False,
                    elapsed_ms=elapsed_ms,
                    safe_message=f"{tool_name} succeeded after {attempt} attempt(s).",
                    events=events,
                ),
            )

        assert last_failure is not None
        elapsed_ms = self._milliseconds(self.monotonic() - overall_started)
        exhausted = last_failure.retryable and maximum_attempts > 1
        events.append(
            ExternalCallEvent(
                event_type="external_call_exhausted",
                attempt=min(maximum_attempts, len([e for e in events if e.event_type == "external_call_started"])),
                maximum_attempts=maximum_attempts,
                failure_category=last_failure.category,
                retryable=last_failure.retryable,
                elapsed_ms=elapsed_ms,
            )
        )
        return RetryExecution(
            value=None,
            result=ExternalCallExecutionResult(
                tool_name=tool_name,
                success=False,
                attempts=len([event for event in events if event.event_type == "external_call_started"]),
                retry_exhausted=exhausted,
                failure_category=last_failure.category,
                retryable=last_failure.retryable,
                final_failure_type=last_failure.failure_type,
                elapsed_ms=elapsed_ms,
                safe_message=(
                    f"{tool_name} remained unavailable after "
                    f"{len([event for event in events if event.event_type == 'external_call_started'])} attempt(s)."
                ),
                events=events,
            ),
        )

    def classify(self, exc: BaseException, tool_name: str) -> ClassifiedFailure:
        if isinstance(exc, ExternalCallError):
            return ClassifiedFailure(
                exc.category,
                exc.retryable,
                exc.safe_message,
                type(exc).__name__,
                exc.retry_after_seconds,
            )
        if self.non_retryable_exceptions and isinstance(exc, self.non_retryable_exceptions):
            return self._permanent(tool_name, exc, "non_retryable_error")
        if self.retryable_exceptions and isinstance(exc, self.retryable_exceptions):
            return self._temporary(tool_name, exc, "temporary_provider_error")
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            retry_after = self._parse_retry_after(exc.response.headers.get("Retry-After"))
            return self._http_failure(tool_name, exc, status, retry_after)
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            retry_after = self._parse_retry_after(getattr(exc, "retry_after", None))
            return self._http_failure(tool_name, exc, status, retry_after)
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            return self._temporary(tool_name, exc, "timeout")
        if isinstance(exc, (ConnectionError, socket.gaierror, httpx.NetworkError)):
            return self._temporary(tool_name, exc, "temporary_network_failure")
        if isinstance(exc, (ValidationError, ValueError, TypeError)):
            return self._permanent(tool_name, exc, "invalid_response_schema")
        return self._permanent(tool_name, exc, "provider_error")

    def _http_failure(
        self,
        tool_name: str,
        exc: BaseException,
        status: int,
        retry_after: float | None,
    ) -> ClassifiedFailure:
        if status == 429:
            return ClassifiedFailure(
                "rate_limited", True, f"{tool_name} was rate limited.",
                type(exc).__name__, retry_after,
            )
        if status in RETRYABLE_HTTP_STATUSES:
            category = "timeout" if status == 408 else "temporary_service_unavailable"
            return ClassifiedFailure(
                category, True, f"{tool_name} returned temporary HTTP {status}.",
                type(exc).__name__, retry_after,
            )
        if status == 401:
            return ClassifiedFailure(
                "authentication_failure", False,
                f"{tool_name} authentication failed.", type(exc).__name__,
            )
        if status == 403:
            return ClassifiedFailure(
                "authorization_failure", False,
                f"{tool_name} authorization failed.", type(exc).__name__,
            )
        if status == 404:
            category = "resource_not_found"
        elif status == 400:
            category = "invalid_request"
        else:
            category = "permanent_http_error"
        return ClassifiedFailure(
            category, False, f"{tool_name} returned non-retryable HTTP {status}.",
            type(exc).__name__,
        )

    def _retry_delay(self, attempt: int, retry_after: float | None) -> float:
        base_delay = (
            retry_after
            if retry_after is not None
            else self.config.initial_delay_seconds * self.config.multiplier ** (attempt - 1)
        )
        jitter = self.config.jitter_seconds * self.random_value()
        return min(max(0.0, base_delay) + jitter, self.config.max_delay_seconds)

    @staticmethod
    def _parse_retry_after(value: object) -> float | None:
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(str(value))
                return max(0.0, parsed.timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                return None

    @staticmethod
    def _failure_event(
        event_type: str,
        attempt: int,
        maximum_attempts: int,
        failure: ClassifiedFailure,
        elapsed_ms: int,
    ) -> ExternalCallEvent:
        return ExternalCallEvent(
            event_type=event_type,  # type: ignore[arg-type]
            attempt=attempt,
            maximum_attempts=maximum_attempts,
            failure_category=failure.category,
            retryable=failure.retryable,
            elapsed_ms=elapsed_ms,
        )

    @staticmethod
    def _temporary(tool_name: str, exc: BaseException, category: str) -> ClassifiedFailure:
        return ClassifiedFailure(
            category, True, f"{tool_name} is temporarily unavailable.", type(exc).__name__
        )

    @staticmethod
    def _permanent(tool_name: str, exc: BaseException, category: str) -> ClassifiedFailure:
        return ClassifiedFailure(
            category, False, f"{tool_name} returned a non-retryable failure.", type(exc).__name__
        )

    @staticmethod
    def _milliseconds(seconds: float) -> int:
        return max(0, int(seconds * 1000))


default_retry_executor = RetryExecutor()
