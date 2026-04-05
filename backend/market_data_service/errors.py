"""Market data service error types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ERROR_RATE_LIMITED = "rate_limited"
ERROR_EMPTY_DATA = "empty_data"
ERROR_SYMBOL_NOT_FOUND = "symbol_not_found"
ERROR_INVALID_RESPONSE = "invalid_response"
ERROR_PROVIDER_UNAVAILABLE = "provider_unavailable"
ERROR_COOLDOWN = "cooldown"
ERROR_ALL_PROVIDERS_FAILED = "all_providers_failed"


@dataclass
class ProviderFailure(RuntimeError):
    """Structured provider error for fallback, retry, and API responses."""

    message: str
    code: str = ERROR_PROVIDER_UNAVAILABLE
    provider: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = True

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "code": self.code,
            "provider": self.provider,
            "retryable": self.retryable,
            "details": self.details,
        }
