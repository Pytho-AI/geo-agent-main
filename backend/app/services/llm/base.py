"""
Base classes and protocols for LLM providers.

To add a new provider:
1. Create a new file (e.g., anthropic.py)
2. Implement the LLMClient protocol
3. Register in client.py get_llm_client()
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, AsyncIterator, Union


@dataclass
class Message:
    """A chat message.

    Content can be a plain string for text-only messages, or a list of
    content blocks for multimodal messages (text + images).

    Multimodal content block format:
        {"type": "text", "text": "..."}
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}

    Tool traffic: an assistant message that requested tools carries them
    in `tool_calls`; the results come back as role="tool" messages whose
    `tool_call_id` names the call they answer and whose content is the
    tool's output (JSON text).
    """
    role: str  # "system", "user", "assistant", "tool"
    content: Union[str, List[Dict[str, Any]]]
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List["ToolCall"]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "content": self.content}


@dataclass
class ToolCall:
    """A tool/function call from the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM completion."""
    content: str
    model: str
    usage: Dict[str, int] = field(default_factory=dict)  # prompt_tokens, completion_tokens
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop_reason: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None  # Raw provider response
    reasoning: Optional[str] = None  # the model's thinking trace, when the provider returns it


@dataclass
class Tool:
    """Tool/function definition for the LLM."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema


class LLMClient(ABC):
    """
    Abstract base class for LLM providers.
    
    All providers must implement these methods.
    """
    
    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stop: Optional[List[str]] = None,
    ) -> LLMResponse:
        """
        Simple text completion.
        
        Args:
            prompt: The user prompt
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
            stop: Stop sequences
            
        Returns:
            LLMResponse with generated content
        """
        pass
    
    @abstractmethod
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
        """
        Chat completion with message history.
        
        Args:
            messages: List of Message objects
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
            tools: Optional list of tools the model can call
            stop: Stop sequences
            
        Returns:
            LLMResponse with generated content and optional tool_calls
        """
        pass
    
    @abstractmethod
    async def stream(
        self,
        messages: List[Message],
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """
        Streaming chat completion.
        
        Args:
            messages: List of Message objects
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
            
        Yields:
            Text chunks as they're generated
        """
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier."""
        pass
