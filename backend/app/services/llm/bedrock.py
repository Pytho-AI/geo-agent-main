"""
AWS Bedrock LLM provider.

Supports multiple models via Amazon Bedrock Converse API.
"""

import base64
from typing import List, Optional, AsyncIterator, Dict, Any

import boto3
from botocore.config import Config

from app.services.llm.base import (
    LLMClient,
    Message,
    LLMResponse,
    Tool,
    ToolCall,
)


class BedrockClient(LLMClient):
    """
    AWS Bedrock client using the Converse API.
    
    Supports Claude, Llama, Mistral, and other Bedrock models
    through the unified Converse API.
    """
    
    def __init__(
        self,
        model_id: str = "us.meta.llama4-maverick-17b-instruct-v1:0",
        region: str = "us-east-1",
    ):
        """
        Initialize Bedrock client.
        
        Args:
            model_id: Bedrock model identifier
            region: AWS region
        """
        self._model_id = model_id
        self._region = region
        
        # Configure boto3 client with retries
        config = Config(
            region_name=region,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        self._client = boto3.client("bedrock-runtime", config=config)
    
    @property
    def model_name(self) -> str:
        return self._model_id
    
    def _format_messages_converse(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert Message objects to Bedrock Converse API format.

        Handles both plain-text and multimodal (text + image) content.
        """
        formatted = []
        for m in messages:
            if isinstance(m.content, str):
                content_blocks = [{"text": m.content}]
            else:
                content_blocks = []
                for block in m.content:
                    if block.get("type") == "text":
                        content_blocks.append({"text": block["text"]})
                    elif block.get("type") == "image":
                        src = block["source"]
                        fmt = src.get("media_type", "image/png").split("/")[-1]
                        content_blocks.append({
                            "image": {
                                "format": fmt,
                                "source": {
                                    "bytes": base64.b64decode(src["data"])
                                },
                            }
                        })
            formatted.append({"role": m.role, "content": content_blocks})
        return formatted
    
    def _format_tools_converse(self, tools: List[Tool]) -> Dict[str, Any]:
        """Convert Tool objects to Bedrock Converse toolConfig format."""
        tool_list = []
        for t in tools:
            tool_list.append({
                "toolSpec": {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": {
                        "json": t.parameters
                    }
                }
            })
        return {"tools": tool_list}
    
    async def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stop: Optional[List[str]] = None,
    ) -> LLMResponse:
        """Simple text completion."""
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
        """Chat completion using Bedrock Converse API."""
        
        # Build request parameters
        params = {
            "modelId": self._model_id,
            "messages": self._format_messages_converse(messages),
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            }
        }
        
        if system:
            params["system"] = [{"text": system}]
        
        if tools:
            params["toolConfig"] = self._format_tools_converse(tools)
        
        if stop:
            params["inferenceConfig"]["stopSequences"] = stop
        
        # Use Converse API
        response = self._client.converse(**params)
        
        # Parse response
        output = response.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])
        
        # Extract text content and tool calls
        content_text = ""
        tool_calls = []
        
        for block in content_blocks:
            if "text" in block:
                content_text += block["text"]
            elif "toolUse" in block:
                tool_use = block["toolUse"]
                tool_calls.append(
                    ToolCall(
                        id=tool_use.get("toolUseId", ""),
                        name=tool_use.get("name", ""),
                        arguments=tool_use.get("input", {}),
                    )
                )
        
        # Get usage stats
        usage = response.get("usage", {})
        
        return LLMResponse(
            content=content_text,
            model=self._model_id,
            usage={
                "prompt_tokens": usage.get("inputTokens", 0),
                "completion_tokens": usage.get("outputTokens", 0),
            },
            tool_calls=tool_calls,
            stop_reason=response.get("stopReason"),
            raw=response,
        )
    
    async def stream(
        self,
        messages: List[Message],
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Streaming chat completion using Bedrock ConverseStream API."""
        
        params = {
            "modelId": self._model_id,
            "messages": self._format_messages_converse(messages),
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            }
        }
        
        if system:
            params["system"] = [{"text": system}]
        
        # Use streaming Converse API
        response = self._client.converse_stream(**params)
        
        # Stream response chunks
        for event in response.get("stream", []):
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    yield delta["text"]
