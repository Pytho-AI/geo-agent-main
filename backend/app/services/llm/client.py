"""
LLM client factory.

Provides a unified way to get an LLM client based on configuration.
"""

from functools import lru_cache
from typing import Optional

from app.config import get_settings
from app.services.llm.base import LLMClient


@lru_cache
def get_llm_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMClient:
    """
    Get an LLM client based on configuration.
    
    Args:
        provider: Override provider ("bedrock", "openai"). Defaults to config.
        model: Override model ID. Defaults to config.
        
    Returns:
        LLMClient instance
        
    Raises:
        ValueError: If provider is not supported
        
    Example:
        # Use default from config
        client = get_llm_client()
        
        # Override provider
        client = get_llm_client(provider="openai", model="gpt-4o")
    """
    settings = get_settings()
    
    provider = provider or settings.llm_provider
    model = model or settings.llm_model
    
    if provider == "openai_compatible":
        from app.services.llm.openai_compat import OpenAICompatClient
        # Empty string = knob absent (never sent on the wire — mantle
        # rejects unknown fields); anything truthy-shaped enables it.
        thinking_raw = (settings.llm_enable_thinking or "").strip().lower()
        enable_thinking = (
            None if not thinking_raw
            else thinking_raw in ("1", "true", "yes", "on")
        )
        return OpenAICompatClient(
            model=model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            aws_region=settings.aws_region,
            enable_thinking=enable_thinking,
            image_soft_tokens=settings.llm_image_soft_tokens,
        )

    elif provider == "bedrock":
        from app.services.llm.bedrock import BedrockClient
        return BedrockClient(
            model_id=model,
            region=settings.aws_region,
        )

    elif provider == "ollama":
        from app.services.llm.ollama import OllamaClient
        return OllamaClient(
            model=model or "llama3.2",
            base_url=settings.ollama_base_url,
        )

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported: openai_compatible, bedrock, ollama"
        )


def clear_client_cache():
    """Clear the cached LLM client (useful for testing)."""
    get_llm_client.cache_clear()
