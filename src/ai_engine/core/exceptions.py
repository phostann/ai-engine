"""Exceptions for structured output and self-healing mechanisms"""

from typing import Any


class StructureOutputError(Exception):
    """Base Exception for structured outputs."""


class ModelRefusalError(StructureOutputError):
    """Raised when the model refuses to respond according to policy"""

    def __init__(self, refusal_message: str):
        super().__init__(f"Model refused generation: {refusal_message}")
        self.refusal_message = refusal_message


class TokenTruncationError(StructureOutputError):
    """Raised when generation is cut off by max_tokens limit."""

    def __init__(self, raw_content: str):
        super().__init__("Model response was truncated due to max_tokens.")
        self.raw_content = raw_content


class SelfHealingExhaustedError(StructureOutputError):
    """Raised when the maximum retry attempts for self-healing are exhausted."""

    def __init__(self, attempts: int, last_errors: list[dict[str, Any]]):
        super().__init__(
            f"Self-healing failed after {attempts} attempts. Last errors: {last_errors}"
        )
        self.attempts = attempts
        self.last_errors = last_errors
