"""
LLM provider abstraction layer.

Supports multiple LLM backends (Bedrock, OpenAI, etc.) with a unified interface.

Usage:
    from app.services.llm import get_llm_client, LLMClient
    
    client = get_llm_client()
    response = await client.complete("What is the capital of France?")
    
    # With messages
    response = await client.chat([
        {"role": "user", "content": "Hello!"}
    ])
"""

from app.services.llm.base import LLMClient, Message, LLMResponse
from app.services.llm.client import get_llm_client

__all__ = [
    "LLMClient",
    "Message", 
    "LLMResponse",
    "get_llm_client",
]
