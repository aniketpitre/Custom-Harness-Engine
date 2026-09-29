"""USD cost of model calls: LiteLLM's bundled price map, overridable per model.

Prices come from `HARNESS_PRICES` (JSON), then `prices:` in settings.yaml, then LiteLLM's map. Both overrides
use USD per million tokens: {"my/model": {"input": 0.5, "output": 1.5}}. Local models (ollama, lm_studio,
vllm, llamafile) cost nothing. Anything else without a price is counted as *unpriced*, never silently as free,
so the budget check and reports can say so.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache

log = logging.getLogger("harness.cost")
LOCAL_PREFIXES = ("ollama", "ollama_chat", "lm_studio", "hosted_vllm", "vllm", "llamafile", "local")


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * self.input_per_mtok + completion_tokens * self.output_per_mtok) / 1_000_000


def _overrides() -> dict[str, Price]:
    raw: dict = {}
    try:
        from core.settings import _file_config

        raw.update(_file_config().get("prices") or {})
    except Exception:  # noqa: BLE001
        pass
    env = os.environ.get("HARNESS_PRICES")
    if env:
        try:
            raw.update(json.loads(env))
        except ValueError:
            log.warning("HARNESS_PRICES is not valid JSON; ignored")
    out = {}
    for model, p in raw.items():
        try:
            out[str(model)] = Price(float(p["input"]), float(p["output"]))
        except (KeyError, TypeError, ValueError):
            log.warning("price for %s must look like {input: .., output: ..}; ignored", model)
    return out


def is_local(model: str) -> bool:
    return model.split("/", 1)[0].lower() in LOCAL_PREFIXES


def price_for(model: str) -> Price | None:
    """Per-million-token price for `model`, or None when nobody knows it."""
    override = _overrides().get(model)
    if override:
        return override
    if is_local(model):
        return Price(0.0, 0.0)
    return _catalog_price(model)


@lru_cache(maxsize=256)
def _catalog_price(model: str) -> Price | None:
    """Look the model up in LiteLLM's bundled map: exact name, then without each provider prefix."""
    try:
        from litellm import model_cost
    except Exception:  # noqa: BLE001
        return None
    parts = model.split("/")
    for name in ["/".join(parts[i:]) for i in range(len(parts))]:
        info = model_cost.get(name)
        if info and (info.get("input_cost_per_token") is not None or info.get("output_cost_per_token") is not None):
            return Price(float(info.get("input_cost_per_token") or 0) * 1_000_000,
                         float(info.get("output_cost_per_token") or 0) * 1_000_000)
    return None


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Cost of one call, or None when the model has no known price."""
    price = price_for(model)
    return None if price is None else round(price.cost(prompt_tokens, completion_tokens), 8)


def fmt(amount: float | None) -> str:
    if amount is None:
        return "n/a"
    if amount == 0:
        return "$0"
    return f"${amount:.4f}" if amount < 1 else f"${amount:,.2f}"
