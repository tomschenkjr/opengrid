from typing import Protocol, Any


class DataProvider(Protocol):
    provider_id: str

    async def call_tool(self, tool_name: str, args: dict) -> Any: ...
    def describe(self) -> str: ...
