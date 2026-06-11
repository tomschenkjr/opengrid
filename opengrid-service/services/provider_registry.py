"""
Provider registry — loads config/providers.yaml and instantiates MCP providers.
Call load() at startup; then use get() or all_providers() throughout the app.
"""

from pathlib import Path

import yaml

from providers.mcp_http import McpHttpProvider

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "providers.yaml"
_providers: dict[str, McpHttpProvider] = {}
_ALIASES = {
    # Historical provider id retained only so older classifier output still
    # resolves to the Chicago Marine Knowledge service.
    "noaa-marine": "chicago-marine-knowledge",
}


def load() -> None:
    global _providers
    if not _CONFIG_PATH.exists():
        return
    with open(_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f) or {}
    for p in cfg.get("providers", []):
        if p.get("type") == "mcp_http":
            provider = McpHttpProvider(p)
            _providers[provider.provider_id] = provider
            print(f"[provider_registry] Registered MCP provider: {provider.provider_id}")


def get(provider_id: str) -> McpHttpProvider | None:
    return _providers.get(provider_id) or _providers.get(_ALIASES.get(provider_id, ""))


def all_providers() -> list[McpHttpProvider]:
    return list(_providers.values())


def describe_all() -> str:
    """Return a combined description string for injection into the AI system prompt."""
    if not _providers:
        return ""
    return "\n\n".join(p.describe() for p in _providers.values())
