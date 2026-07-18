from __future__ import annotations
from typing import Optional
from services.reply_generation.provider_base import LLMProvider


_registry: dict[str, type[LLMProvider]] = {}
_instances: dict[str, LLMProvider] = {}


def register_provider(name: str, provider_class: type[LLMProvider]) -> None:
    """Register an LLM provider class by name."""
    _registry[name] = provider_class


def list_providers() -> list[str]:
    """List all registered provider names."""
    return list(_registry.keys())


def get_provider(name: str) -> Optional[LLMProvider]:
    """Get or create a provider instance by name."""
    if name not in _instances:
        cls = _registry.get(name)
        if not cls:
            return None
        _instances[name] = cls()
    return _instances[name]


def get_default_provider() -> Optional[LLMProvider]:
    """Get the first available (validated) provider.
    
    Checks registered providers in deterministic order.
    Unavailable providers degrade gracefully (skipped).
    """
    for name in ("openai", "anthropic", "gemini", "deepseek"):
        provider = get_provider(name)
        if provider and provider.validate_connection():
            return provider
    return None


def clear_instances() -> None:
    """Clear all cached provider instances (useful for testing)."""
    _instances.clear()


def validate_all() -> dict[str, bool]:
    """Validate all registered providers. Returns name → status map."""
    results: dict[str, bool] = {}
    for name in _registry:
        provider = get_provider(name)
        if provider:
            results[name] = provider.validate_connection()
        else:
            results[name] = False
    return results


def _auto_register() -> None:
    """Discover and register all available providers automatically.
    
    Each provider module is imported only if its dependencies are available.
    This avoids ImportError from missing optional dependencies.
    """
    providers_to_try = [
        ("openai", "services.reply_generation.providers.openai_provider", "OpenAIProvider"),
        ("anthropic", "services.reply_generation.providers.anthropic_provider", "AnthropicProvider"),
        ("gemini", "services.reply_generation.providers.gemini_provider", "GeminiProvider"),
        ("deepseek", "services.reply_generation.providers.deepseek_provider", "DeepSeekProvider"),
    ]
    for name, module_path, class_name in providers_to_try:
        if name in _registry:
            continue
        try:
            import importlib
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name, None)
            if cls is not None:
                register_provider(name, cls)
        except (ImportError, AttributeError):
            pass


_auto_register()
