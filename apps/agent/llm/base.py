"""LLM client interface — har provider isko implement karta hai."""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class LLMClient(ABC):
    name: str = "base"
    model: str = "unknown"

    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel] | None = None,
        role: str = "",
    ) -> tuple[str, dict]:
        """→ (response_text, usage)

        usage = {"prompt_tokens": int, "completion_tokens": int, "cost_inr": float}
        response_model diya toh structured JSON text return kare (schema-valid).
        """
        ...
