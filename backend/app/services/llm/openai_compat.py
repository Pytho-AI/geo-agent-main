"""
OpenAI-compatible LLM provider — ONE client for both deployment shapes.

Both inference targets speak the OpenAI Chat Completions protocol, so the
per-deployment difference is pure configuration (base_url + model +
credential), never code:

  cloud/staging — AWS Bedrock's `bedrock-mantle` OpenAI-compatible
      endpoint serving Gemma 4 (`google.gemma-4-26b-a4b`). Auth is a
      short-lived bearer minted from the ambient AWS credentials via
      aws-bedrock-token-generator (same pattern as pytho-agent
      ai/agent/src/llm_clients.py, where the June 2026 cost actuals
      live). Tokens expire within 12 h; this client re-mints when the
      cached one passes _MANTLE_TOKEN_MAX_AGE_SECONDS.

  edge (spark) — the GB10 vllm serving the same model family
      (nvidia/Gemma-4-26B-A4B-NVFP4 at http://172.17.0.1:18000/v1 —
      the same host-bridge convention PYTHO_RENDER_CDP uses). No auth.
      `enable_thinking` rides chat_template_kwargs exactly like
      pytho-app utils/llm.py; it is only sent when the deployment sets
      LLM_ENABLE_THINKING, because mantle does not accept the knob.

The NL chat pipeline (services/nl/agent.py) is a SINGLE bounded call
returning JSON it parses itself — no response_format, no tool loop — so
this client deliberately implements just the base protocol.
"""

import logging
import time
from typing import List, Optional, AsyncIterator, Dict, Any
import json

import httpx

from app.services.llm.base import (
    LLMClient,
    Message,
    LLMResponse,
    Tool,
    ToolCall,
)

logger = logging.getLogger(__name__)
# Every model call is traced here (prompt summary, usage, the model's
# THINKING when the provider returns it, and the output) so extraction
# bugs can be debugged from the reasoning, not guessed at. Lands in the
# backend log. NOTE: Bedrock/mantle's Chat Completions endpoint does not
# return reasoning tokens (only its Responses endpoint does); vLLM (edge)
# returns them as reasoning_content, which is where the trace has teeth.
_trace = logging.getLogger("app.llm.trace")

# The Responses API's real output ceiling (probed: 131072 accepted,
# 262144 rejected). Sent on every call because OMITTING it applies a
# stingy ~8192 default that reasoning=high exhausts before emitting the
# answer — measured: omit -> incomplete=max_output_tokens, 0 output;
# 131072 -> complete. Not an arbitrary cap: it is the model's full limit,
# and the model still stops when the answer is done.
_RESPONSES_MAX_OUTPUT = 131072

# Re-mint the mantle bearer well inside its <=12 h expiry (mirrors
# ai/agent/src/llm_clients.py).
_MANTLE_TOKEN_MAX_AGE_SECONDS = 36000


def _is_mantle(base_url: str) -> bool:
    return "bedrock-mantle" in (base_url or "")


class OpenAICompatClient(LLMClient):
    """Chat Completions client for mantle (cloud) and vllm (edge)."""

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "",
        aws_region: str = "us-east-1",
        enable_thinking: Optional[bool] = None,
        image_soft_tokens: int = 0,
    ):
        if not base_url:
            raise ValueError(
                "openai_compatible provider requires LLM_BASE_URL "
                "(mantle endpoint on cloud, vllm /v1 on the edge)"
            )
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._static_api_key = api_key
        self._aws_region = aws_region
        self._enable_thinking = enable_thinking
        # Gemma-4 vision token budget. HONORED ONLY on vllm (edge), sent
        # as mm_processor_kwargs on image requests. Bedrock/mantle pins
        # the budget at ~280 regardless (empirically: prompt_tokens flat
        # at 283 across max_soft_tokens 70→1120 AND across 1148px→2400px
        # renders), so the knob is never sent there.
        self._image_soft_tokens = image_soft_tokens
        self._bearer: Optional[str] = None
        self._bearer_minted_at: float = 0.0
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            # These are reasoning+vision Responses calls over all of a
            # scenario's pages at once (define_ao / extract_oob) — they
            # legitimately run 180-280s with reasoning=high. 180s was too
            # tight and truncated define_ao mid-response with a ReadTimeout;
            # give read/write a generous ceiling, keep connect short.
            timeout=httpx.Timeout(600.0, connect=10.0),
        )

    @property
    def model_name(self) -> str:
        return self._model

    # ------------------------------------------------------------------
    # auth
    # ------------------------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        if self._static_api_key:
            return {"Authorization": f"Bearer {self._static_api_key}"}
        if _is_mantle(self._base_url):
            age = time.time() - self._bearer_minted_at
            if self._bearer is None or age > _MANTLE_TOKEN_MAX_AGE_SECONDS:
                from aws_bedrock_token_generator import provide_token

                self._bearer = provide_token(region=self._aws_region)
                self._bearer_minted_at = time.time()
                logger.info("Minted bedrock-mantle bearer (region=%s)", self._aws_region)
            return {"Authorization": f"Bearer {self._bearer}"}
        # Local vllm accepts unauthenticated requests.
        return {}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_openai_messages(
        messages: List[Message],
        system: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            if isinstance(m.content, str):
                out.append({"role": m.role, "content": m.content})
            else:
                blocks: List[Dict[str, Any]] = []
                for block in m.content:
                    if block.get("type") == "text":
                        blocks.append({"type": "text", "text": block["text"]})
                    elif block.get("type") == "image":
                        src = block.get("source", {})
                        blocks.append({
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    f"data:{src.get('media_type', 'image/png')};"
                                    f"base64,{src.get('data', '')}"
                                )
                            },
                        })
                out.append({"role": m.role, "content": blocks})
        return out

    def _payload(
        self,
        messages: List[Message],
        system: Optional[str],
        max_tokens: int,
        temperature: float,
        stop: Optional[List[str]] = None,
        stream: bool = False,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": self._to_openai_messages(messages, system),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if stop:
            payload["stop"] = stop
        # Thinking is a PER-CALL decision (mandatory for complex tasks),
        # not a global switch. On vLLM it rides chat_template_kwargs and
        # comes back as reasoning_content; per-call reasoning forces it on
        # regardless of the deployment default. (On mantle a reasoning
        # call goes through the Responses API instead — see chat().)
        think = self._enable_thinking
        if reasoning_effort is not None and not _is_mantle(self._base_url):
            think = True
        if think is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": think}
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        # Raise the gemma-4 vision token budget for image requests — but
        # only on vllm (the edge), which honors it; mantle ignores it.
        if (self._image_soft_tokens and not _is_mantle(self._base_url)
                and self._has_image(messages)):
            payload["mm_processor_kwargs"] = {"max_soft_tokens": self._image_soft_tokens}
        return payload

    @staticmethod
    def _has_image(messages: List[Message]) -> bool:
        for m in messages:
            if isinstance(m.content, list) and any(
                    b.get("type") == "image" for b in m.content):
                return True
        return False

    @staticmethod
    def _strip_reasoning(message: Dict[str, Any]) -> str:
        """The final answer, never the reasoning trace.

        vllm's gemma template surfaces thinking as `reasoning_content`
        alongside `content`; the NL pipeline parses JSON out of the
        answer, so the trace must never leak into it.
        """
        return message.get("content") or ""

    @staticmethod
    def _extract_reasoning(message: Dict[str, Any]) -> str:
        return message.get("reasoning_content") or message.get("reasoning") or ""

    def _trace_call(self, messages: List[Message], content: str,
                    reasoning: str, usage: Dict[str, Any]) -> None:
        """Log the full call — prompt, thinking, output — for debugging."""
        try:
            last_user = ""
            for m in reversed(messages):
                if m.role != "user":
                    continue
                last_user = m.content if isinstance(m.content, str) else " ".join(
                    b.get("text", "") for b in m.content if b.get("type") == "text")
                break
            _trace.info(
                "LLM call model=%s images=%s pt=%s ct=%s\n"
                "  PROMPT: %s\n  THINKING: %s\n  OUTPUT: %s",
                self._model, self._has_image(messages),
                usage.get("prompt_tokens"), usage.get("completion_tokens"),
                (last_user or "")[:800],
                reasoning if reasoning else "(no reasoning emitted for this call)",
                (content or "")[:4000])
        except Exception:  # tracing must never break a call
            logger.debug("llm trace failed", exc_info=True)

    # ------------------------------------------------------------------
    # interface
    # ------------------------------------------------------------------

    async def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stop: Optional[List[str]] = None,
    ) -> LLMResponse:
        return await self.chat(
            [Message(role="user", content=prompt)],
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
        )

    async def chat(
        self,
        messages: List[Message],
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[List[Tool]] = None,
        stop: Optional[List[str]] = None,
        reasoning_effort: Optional[str] = None,
    ) -> LLMResponse:
        # ONE path for the model no matter where it is served. Both mantle
        # (cloud) and vllm (edge) speak the OpenAI RESPONSES API, and it is
        # the endpoint that returns the reasoning trace. Chat Completions
        # is a chatbot API that hides the thinking on mantle; using it on
        # one deployment and Responses on the other is exactly how cloud
        # and edge silently diverge and break.
        return await self._responses_chat(
            messages, system, max_tokens, temperature, reasoning_effort,
            tools=tools)

    async def _responses_chat(
        self, messages: List[Message], system: Optional[str],
        max_tokens: int, temperature: float,
        reasoning_effort: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
    ) -> LLMResponse:
        """THE model call — OpenAI Responses API, used for both mantle
        and vllm (one path, no cloud/edge divergence). It returns the
        reasoning as its own output item, unlike Chat Completions. Images
        ride as input_image; the thinking is traced alongside the answer.
        reasoning_effort None => no reasoning requested (still answers).

        Tools are the Responses API's native function tools: `tools` on
        the request, `function_call` output items back (surfaced as
        LLMResponse.tool_calls), and the caller answers with role="tool"
        messages that serialize as `function_call_output` items."""
        items = self._responses_items(messages, system)
        # max_output_tokens = the model's REAL MAX (131072; the API
        # rejects 256K and, if the field is OMITTED, applies a stingy
        # default that reasoning=high blows through before it ever emits
        # the JSON — that silently produced 0 entities). So this is the
        # full ceiling, not an arbitrary cap; the model still stops when
        # the answer is done. The Responses API has no `max_tokens` field
        # (verified 400 "Unknown parameter"), and gemma-4 rejects
        # `temperature` (reasoning model) — neither is sent.
        body = {"model": self._model, "input": items,
                "max_output_tokens": _RESPONSES_MAX_OUTPUT}
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        if tools:
            body["tools"] = [{"type": "function", "name": t.name,
                              "description": t.description,
                              "parameters": t.parameters} for t in tools]
        resp = await self._client.post("/responses", json=body, headers=self._auth_headers())
        resp.raise_for_status()
        return self._parse_responses_data(resp.json(), messages)

    def _responses_items(self, messages: List[Message],
                         system: Optional[str]) -> List[Dict[str, Any]]:
        """Messages -> Responses API input items (shared by the blocking
        and streaming calls)."""
        items: List[Dict[str, Any]] = []
        if system:
            items.append({"role": "system", "content": [{"type": "input_text", "text": system}]})
        for m in messages:
            if m.role == "tool":
                items.append({"type": "function_call_output",
                              "call_id": m.tool_call_id or "",
                              "output": m.content if isinstance(m.content, str)
                              else json.dumps(m.content)})
                continue
            if m.role == "assistant" and m.tool_calls:
                # Round-trip the model's own function_call items so the
                # follow-up turn sees what it asked for.
                for tc in m.tool_calls:
                    items.append({"type": "function_call", "call_id": tc.id,
                                  "name": tc.name,
                                  "arguments": json.dumps(tc.arguments)})
                if not m.content:
                    continue
            # The Responses API types content by DIRECTION: an assistant
            # history message is echoed model output and must be
            # output_text — input_text under role=assistant is a 400
            # (surfaced the first time a caller sent conversation
            # history: every follow-up question errored).
            text_type = ("output_text" if m.role == "assistant"
                         else "input_text")
            if isinstance(m.content, str):
                content = [{"type": text_type, "text": m.content}]
            else:
                content = []
                for b in m.content:
                    if b.get("type") == "text":
                        content.append({"type": text_type, "text": b.get("text", "")})
                    elif b.get("type") == "image":
                        src = b.get("source", {})
                        content.append({"type": "input_image", "image_url":
                            f"data:{src.get('media_type', 'image/jpeg')};base64,{src.get('data', '')}"})
            items.append({"role": m.role, "content": content})
        return items

    def _parse_responses_data(
            self, data: Dict[str, Any], messages: List[Message]) -> LLMResponse:
        """A completed Responses API payload -> LLMResponse (shared by the
        blocking call and the stream's `response.completed` event)."""
        content, reasoning = "", ""
        tool_calls: List[ToolCall] = []
        for o in data.get("output") or []:
            texts = "\n".join(c.get("text", "") for c in (o.get("content") or []) if c.get("text"))
            if o.get("type") == "reasoning":
                reasoning = texts or reasoning
            elif o.get("type") == "message":
                content = texts or content
            elif o.get("type") == "function_call":
                try:
                    args = json.loads(o.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": o.get("arguments")}
                tool_calls.append(ToolCall(
                    id=o.get("call_id") or o.get("id") or "",
                    name=o.get("name") or "", arguments=args))
        u = data.get("usage") or {}
        usage = {"prompt_tokens": u.get("input_tokens", 0),
                 "completion_tokens": u.get("output_tokens", 0)}
        self._trace_call(messages, content, reasoning, usage)
        return LLMResponse(content=content, model=data.get("model", self._model),
                           usage=usage, stop_reason=data.get("status"),
                           tool_calls=tool_calls,
                           raw=data, reasoning=reasoning or None)

    async def chat_stream(
        self,
        messages: List[Message],
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[List[Tool]] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[Any]:
        """chat() as a stream: yields ("delta", text) as answer tokens
        arrive, then exactly one ("response", LLMResponse) carrying the
        complete turn — content, tool_calls, usage — identical to what
        chat() returns, so an agent loop treats streamed and blocking
        turns the same. If the deployment rejects Responses streaming,
        falls back to the blocking call (one delta, then the response):
        degraded latency, never a broken chat."""
        items = self._responses_items(messages, system)
        body: Dict[str, Any] = {"model": self._model, "input": items,
                                "max_output_tokens": _RESPONSES_MAX_OUTPUT,
                                "stream": True}
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        if tools:
            body["tools"] = [{"type": "function", "name": t.name,
                              "description": t.description,
                              "parameters": t.parameters} for t in tools]
        final: Optional[LLMResponse] = None
        pieces: List[str] = []
        try:
            async with self._client.stream(
                    "POST", "/responses", json=body,
                    headers=self._auth_headers()) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[len("data:"):].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        ev = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    etype = ev.get("type") or ""
                    if etype == "response.output_text.delta":
                        text = ev.get("delta") or ""
                        if text:
                            pieces.append(text)
                            yield ("delta", text)
                    elif "reasoning" in etype and etype.endswith(".delta"):
                        # Reasoning tokens are never answer content, but
                        # their arrival is a liveness signal the caller
                        # can surface ("the model is thinking").
                        text = ev.get("delta") or ""
                        if text:
                            yield ("reasoning", text)
                    elif etype == "response.completed":
                        final = self._parse_responses_data(
                            ev.get("response") or {}, messages)
                    elif etype in ("response.failed", "error"):
                        raise RuntimeError(
                            f"responses stream error: {json.dumps(ev)[:500]}")
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            # Streaming unsupported/unreachable on this deployment —
            # blocking call, same contract.
            logger.warning("responses stream unavailable (%s); "
                           "falling back to blocking call", exc)
            final = await self._responses_chat(
                messages, system, max_tokens, temperature,
                reasoning_effort, tools=tools)
            if final.content:
                yield ("delta", final.content)
        if final is None:
            # Stream ended without a completed event: stand the turn up
            # from what actually arrived rather than dropping it.
            final = LLMResponse(content="".join(pieces), model=self._model,
                                usage={}, stop_reason="incomplete",
                                tool_calls=[], raw={})
        yield ("response", final)

    async def stream(
        self,
        messages: List[Message],
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, system, max_tokens, temperature, stream=True)
        async with self._client.stream(
            "POST", "/chat/completions", json=payload, headers=self._auth_headers()
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if chunk == "[DONE]":
                    break
                delta = (
                    (json.loads(chunk).get("choices") or [{}])[0].get("delta") or {}
                )
                text = delta.get("content") or ""
                if text:
                    yield text
