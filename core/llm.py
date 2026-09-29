"""LLM access: streaming, retries with jittered backoff, model failover, per-model credentials,
prompt-cache markers, and a uniform Completion result."""
from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from core.secrets import get_llm_key
from core.settings import Settings

log = logging.getLogger("harness.llm")
# use the price/model map bundled with LiteLLM instead of fetching it over the network on import
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
_sleep = asyncio.sleep  # patched in tests


class LLMError(RuntimeError):
    pass


class ContextOverflow(LLMError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class Completion:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> float | None:
        from core.cost import cost_usd

        return cost_usd(self.model, self.prompt_tokens, self.completion_tokens)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _usage(usage: Any) -> tuple[int, int]:
    if not usage:
        return 0, 0
    total = _get(usage, "total_tokens", 0) or 0
    prompt = _get(usage, "prompt_tokens", None)
    completion = _get(usage, "completion_tokens", None)
    if isinstance(prompt, int) and isinstance(completion, int):
        return prompt, completion
    return int(total), 0


def _parse_full(resp: Any, model: str) -> Completion:
    message = _get(_get(resp, "choices")[0], "message")
    calls = []
    for tc in _get(message, "tool_calls", None) or []:
        fn = _get(tc, "function")
        calls.append(ToolCall(_get(tc, "id"), _get(fn, "name"), _get(fn, "arguments", "") or ""))
    prompt, completion = _usage(_get(resp, "usage", None))
    content = _get(message, "content", None)
    return Completion(content if isinstance(content, str) or content is None else str(content),
                      calls, prompt, completion, model)


async def _parse_stream(stream: Any, model: str, on_delta: Callable[[str], Any] | None) -> Completion:
    text: list[str] = []
    calls: dict[int, dict[str, str]] = {}
    usage = None
    async for chunk in stream:
        u = _get(chunk, "usage", None)
        if u:
            usage = u
        choices = _get(chunk, "choices", None) or []
        if not choices:
            continue
        delta = _get(choices[0], "delta", None)
        if delta is None:
            continue
        piece = _get(delta, "content", None)
        if piece:
            text.append(piece)
            if on_delta:
                r = on_delta(piece)
                if asyncio.iscoroutine(r):
                    await r
        for tc in _get(delta, "tool_calls", None) or []:
            slot = calls.setdefault(_get(tc, "index", 0) or 0, {"id": "", "name": "", "arguments": ""})
            if _get(tc, "id", None):
                slot["id"] = _get(tc, "id")
            fn = _get(tc, "function", None)
            if fn is not None:
                if _get(fn, "name", None):
                    slot["name"] += _get(fn, "name")
                if _get(fn, "arguments", None):
                    slot["arguments"] += _get(fn, "arguments")
    prompt, completion = _usage(usage)
    tool_calls = [ToolCall(c["id"] or f"call_{i}", c["name"], c["arguments"])
                  for i, c in sorted(calls.items())]
    return Completion("".join(text) or None, tool_calls, prompt, completion, model)


def apply_cache_markers(messages: list[dict], model: str) -> list[dict]:
    """Anthropic prompt caching: mark the (stable) system prompt as cacheable."""
    if "claude" not in model.lower() and not model.lower().startswith("anthropic/"):
        return messages
    out = [dict(m) for m in messages]
    if out and out[0].get("role") == "system" and isinstance(out[0].get("content"), str):
        out[0]["content"] = [{"type": "text", "text": out[0]["content"],
                              "cache_control": {"type": "ephemeral"}}]
    return out


def _is_retryable(error: Exception) -> bool:
    import litellm

    retryable = tuple(getattr(litellm, n) for n in
                      ("RateLimitError", "APIConnectionError", "Timeout", "ServiceUnavailableError",
                       "InternalServerError") if hasattr(litellm, n))
    if isinstance(error, retryable):
        return True
    status = getattr(error, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


async def complete(
    models: list[str],
    messages: list[dict],
    tools: list[dict] | None,
    settings: Settings,
    *,
    on_delta: Callable[[str], Any] | None = None,
) -> Completion:
    import litellm

    last: Exception | None = None
    for model in models:
        for attempt in range(max(settings.llm_retries, 1)):
            kwargs: dict[str, Any] = {
                "model": model, "messages": apply_cache_markers(messages, model),
                "timeout": settings.llm_timeout,
            }
            key = get_llm_key(model)
            if key:
                kwargs["api_key"] = key
            if tools:
                kwargs["tools"], kwargs["tool_choice"] = tools, "auto"
            if settings.stream:
                kwargs["stream"], kwargs["stream_options"] = True, {"include_usage": True}
            try:
                resp = await litellm.acompletion(**kwargs)
                if hasattr(resp, "__aiter__"):
                    return await _parse_stream(resp, model, on_delta)
                return _parse_full(resp, model)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                if isinstance(error, getattr(litellm, "ContextWindowExceededError", ())):
                    raise ContextOverflow(str(error)) from error
                last = error
                if not _is_retryable(error):
                    break  # try the next model; a bad request will not improve on retry
                delay = min(2 ** attempt, 30) + random.random()
                log.warning("LLM call failed (%s), retrying in %.1fs: %s", model, delay, error)
                await _sleep(delay)
        log.warning("model %s exhausted, failing over", model)
    raise LLMError(f"All models failed: {last}")


async def simple_completion(prompt: str, settings: Settings, model: str | None = None,
                            system: str | None = None) -> str:
    """One-shot helper for advisor, summariser and dreamer calls."""
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    stream_off = Settings(**{**settings.__dict__, "stream": False})
    result = await complete([model or settings.model, *settings.fallback_models], messages, None, stream_off)
    return result.content or ""
