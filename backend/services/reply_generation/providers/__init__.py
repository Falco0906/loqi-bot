"""LLM provider implementations.

Providers are auto-discovered by provider_registry._auto_register().
No manual imports needed — just add a class that extends LLMProvider.
"""

from services.reply_generation.providers.openai_provider import OpenAIProvider
from services.reply_generation.providers.anthropic_provider import AnthropicProvider

try:
    from services.reply_generation.providers.gemini_provider import GeminiProvider
except ImportError:
    GeminiProvider = None

try:
    from services.reply_generation.providers.deepseek_provider import DeepSeekProvider
except ImportError:
    DeepSeekProvider = None


__all__ = [
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "DeepSeekProvider",
]
