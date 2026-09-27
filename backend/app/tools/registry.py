from app.tools.base_tool import BaseTool
from app.tools.exceptions import DuplicateToolError, ToolNotFoundError
from app.tools.types import ToolDefinition


class ToolRegistry:
    """Explicit in-process catalog of statically registered tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        definition = tool.definition
        if definition.name in self._tools:
            raise DuplicateToolError(
                f"Tool '{definition.name}' is already registered."
            )
        self._tools[definition.name] = tool

    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool '{name}' is not registered.") from exc

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def list_definitions(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]
