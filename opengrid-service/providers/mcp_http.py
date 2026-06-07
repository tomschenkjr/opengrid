"""
MCP HTTP provider — uses the official `mcp` Python client library (SSE transport).
This replaces a hand-rolled SSE implementation; using the same library as the server
avoids session management bugs with the MCP SSE handshake protocol.
"""
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


async def _call_via_mcp_client(sse_url: str, tool_name: str, args: dict) -> list[dict]:
    async with sse_client(sse_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, args)
            return [
                {
                    "type": getattr(item, "type", "text"),
                    "text": getattr(item, "text", str(item)),
                }
                for item in (result.content or [])
            ]


class McpHttpProvider:
    def __init__(self, config: dict):
        self.provider_id: str = config["id"]
        self.base_url: str = config["base_url"]
        self._config = config

    async def call_tool(self, tool_name: str, args: dict) -> Any:
        sse_url = f"{self.base_url}/sse"
        return await _call_via_mcp_client(sse_url, tool_name, args)

    def describe(self) -> str:
        tools = self._config.get("tools", [])
        tool_lines = "\n".join(
            f"  - {t['name']}: {t['description']}" for t in tools
        )
        geo = self._config.get("geometry", {})
        default_zone = geo.get("default_zone", "")
        return (
            f'PROVIDER: {self._config.get("description", self.provider_id)} '
            f'(id: "{self.provider_id}")\n'
            f"Default zone: {default_zone}\n"
            f"Tools:\n{tool_lines}"
        )
