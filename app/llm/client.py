"""Minimal client for OpenAI-compatible Chat Completions APIs.

Uses httpx directly (no vendor SDK) so any compatible endpoint works: OpenAI, Azure
OpenAI-compatible gateways, Groq, Together, OpenRouter, vLLM, Ollama, and others.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import httpx

from app.config import Settings
from app.security import redact_secrets

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cost_usd += other.cost_usd
        self.calls += other.calls


@dataclass
class LLMReply:
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


class LLMClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._http = httpx.Client(
            base_url=settings.llm_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.llm_timeout_s, connect=10.0),
            headers={"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"},
            transport=transport,
        )

    @property
    def model(self) -> str:
        return self.settings.llm_model

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        json_mode: bool = False,
        retries: int = 1,
    ) -> LLMReply:
        body: dict = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = self._http.post("/chat/completions", json=body)
                if resp.status_code == 400 and json_mode and "response_format" in resp.text:
                    body.pop("response_format", None)  # endpoint doesn't support JSON mode
                    resp = self._http.post("/chat/completions", json=body)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if resp.status_code >= 400:
                    raise LLMError(f"LLM API returned HTTP {resp.status_code}: {redact_secrets(resp.text[:300])}")
                return self._parse(resp.json())
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
        raise LLMError(f"LLM request failed: {type(last_exc).__name__}")

    def _parse(self, data: dict) -> LLMReply:
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Malformed LLM response") from exc
        u = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(u.get("prompt_tokens", 0)),
            completion_tokens=int(u.get("completion_tokens", 0)),
            calls=1,
        )
        usage.cost_usd = (
            usage.prompt_tokens * self.settings.llm_price_input_per_mtok
            + usage.completion_tokens * self.settings.llm_price_output_per_mtok
        ) / 1e6
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = None
            calls.append({"name": fn.get("name"), "arguments": args})
        return LLMReply(content=msg.get("content") or "", tool_calls=calls, usage=usage)


def parse_json_object(text: str) -> dict | None:
    """Extract the first JSON object from model output (tolerates code fences / prose)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
