"""Real LLM via LiteLLM — provider-agnostic (Gemini / Claude / GPT / Ollama...).

Env vars:
  LLM_MODEL      e.g. "gemini/gemini-2.0-flash" | "claude/claude-3-5-haiku-latest" | "ollama/llama3.1"
  LLM_API_KEY    provider ki API key
  LLM_API_BASE   optional — custom endpoint / local proxy

pip install litellm
"""
from __future__ import annotations

import json

from apps.agent.llm.base import LLMClient

USD_TO_INR = 83.0  # approx — cost display ke liye


class LiteLLMClient(LLMClient):
    name = "litellm"

    def __init__(self, model: str, api_key: str | None = None,
                 api_base: str | None = None, **kwargs):
        import litellm  # lazy import — optional dependency
        self.litellm = litellm
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.kwargs = kwargs

    def complete(self, system_prompt: str, user_prompt: str,
                 response_model: type | None = None, role: str = "") -> tuple[str, dict]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs = dict(self.kwargs)
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        if response_model is not None:
            # Structured output: JSON mode + schema in system prompt + Pydantic validation (pipeline mein)
            schema = json.dumps(response_model.model_json_schema())
            messages[0]["content"] = (
                system_prompt
                + "\n\n--- STRICT OUTPUT FORMAT ---\n"
                  "Respond with VALID JSON ONLY, matching this exact schema "
                  "(no markdown, no commentary):\n" + schema
            )
            kwargs["response_format"] = {"type": "json_object"}

        resp = self.litellm.completion(model=self.model, messages=messages, **kwargs)
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        try:
            cost_usd = float(self.litellm.completion_cost(resp))
        except Exception:
            cost_usd = 0.0
        return text, {
            "prompt_tokens": int(usage.prompt_tokens),
            "completion_tokens": int(usage.completion_tokens),
            "cost_inr": round(cost_usd * USD_TO_INR, 4),
        }
