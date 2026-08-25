"""The LLM degradation chain (fifth edition §2.8): Mantle and local
Gemma 4 are the SAME openai_compatible client at two base URLs —
failover is a health-memoized (base_url, model) tuple swap; only the
Claude rung swaps provider class (bedrock), and it exists in the
CONNECTED case only. Per-call failover with a cooldown; the serving
tier is returned and logged per writer step."""
import asyncio
import logging
import os
import time

from app.config import get_settings

log = logging.getLogger(__name__)

_COOLDOWN_S = 120
_unhealthy_until: dict[str, float] = {}


def _rungs():
    s = get_settings()
    rungs = [("primary", "openai_compatible", s.llm_base_url,
              s.llm_model)]
    fb_base = os.environ.get("LLM_FALLBACK_BASE_URL", "")
    if fb_base:
        rungs.append(("fallback", "openai_compatible", fb_base,
                      os.environ.get("LLM_FALLBACK_MODEL",
                                     s.llm_model)))
    claude = os.environ.get("LLM_CLAUDE_MODEL", "")
    if claude:
        rungs.append(("claude", "bedrock", "", claude))
    return rungs


def _client_for(provider, base_url, model):
    if provider == "openai_compatible":
        from app.services.llm.openai_compat import OpenAICompatClient
        s = get_settings()
        thinking_raw = (s.llm_enable_thinking or "").strip().lower()
        return OpenAICompatClient(
            model=model, base_url=base_url, api_key=s.llm_api_key,
            aws_region=s.aws_region,
            enable_thinking=(None if not thinking_raw else
                             thinking_raw in ("1", "true", "yes", "on")),
            image_soft_tokens=s.llm_image_soft_tokens)
    from app.services.llm.bedrock import BedrockClient
    return BedrockClient(model_id=model,
                         region=get_settings().aws_region)


async def complete(prompt: str, system: str, max_tokens: int = 4096,
                   temperature: float = 0.2) -> tuple[str, str]:
    """Returns (content, tier). Walks the chain; a rung that raises is
    marked unhealthy for the cooldown and the next rung serves. All
    rungs exhausted -> the last error propagates (llm_failure)."""
    now = time.time()
    last_err = None
    for tier, provider, base_url, model in _rungs():
        if _unhealthy_until.get(tier, 0) > now:
            continue
        client = _client_for(provider, base_url, model)
        # A writer step must never ride the transport's 600s ceiling —
        # a hung call blocks the whole generation. Bound each step.
        # TWO attempts per rung: transient hangs (observed live on
        # Mantle) deserve one same-rung retry before the rung cools
        # down and the chain moves on.
        for attempt in (1, 2):
            try:
                resp = await asyncio.wait_for(
                    client.complete(
                        prompt, system=system, max_tokens=max_tokens,
                        temperature=temperature),
                    timeout=float(os.environ.get(
                        "WRITER_STEP_TIMEOUT_S", "180")))
                return resp.content, tier
            except Exception as e:
                last_err = e
                log.warning("LLM rung %s attempt %d failed (%s)",
                            tier, attempt, e)
                if attempt == 1:
                    # A throttled gateway holds connections rather
                    # than 429ing; give it room before the retry.
                    await asyncio.sleep(15)
        _unhealthy_until[tier] = now + _COOLDOWN_S
        log.warning("LLM rung %s exhausted; cooling down %ss",
                    tier, _COOLDOWN_S)
    raise last_err or RuntimeError("no LLM rungs configured")
