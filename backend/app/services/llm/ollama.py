"""
Ollama LLM provider for offline/local inference.

Uses the Ollama REST API (compatible with any model pulled locally).
"""

import json
import logging
from typing import List, Optional, AsyncIterator, Dict, Any

import httpx

from app.services.llm.base import (
    LLMClient,
    Message,
    LLMResponse,
    Tool,
    ToolCall,
)

logger = logging.getLogger(__name__)


class OllamaClient(LLMClient):
    """
    Ollama client using the /api/chat endpoint.

    Requires a running Ollama instance (e.g. on host.docker.internal:11434).
    """

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
    ):
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    @property
    def model_name(self) -> str:
        return self._model

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_ollama_messages(
        messages: List[Message],
        system: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Convert Message objects to Ollama chat format.

        Handles multimodal content by extracting images into Ollama's
        `images` array (list of base64 strings) at the message level.
        """
        out: List[Dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            if isinstance(m.content, str):
                out.append({"role": m.role, "content": m.content})
            else:
                text_parts = []
                images = []
                for block in m.content:
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "image":
                        images.append(block["source"]["data"])
                msg: Dict[str, Any] = {
                    "role": m.role,
                    "content": "\n".join(text_parts),
                }
                if images:
                    msg["images"] = images
                out.append(msg)
        return out

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
        messages = [Message(role="user", content=prompt)]
        return await self.chat(
            messages,
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
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": self._to_ollama_messages(messages, system),
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if stop:
            payload["options"]["stop"] = stop

        resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        msg = data.get("message", {})
        content = msg.get("content", "")

        return LLMResponse(
            content=content,
            model=self._model,
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
            stop_reason=data.get("done_reason"),
            raw=data,
        )

    async def stream(
        self,
        messages: List[Message],
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": self._to_ollama_messages(messages, system),
            "stream": True,
            "think": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        async with self._client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                msg = chunk.get("message", {})
                text = msg.get("content", "")
                if text:
                    yield text
