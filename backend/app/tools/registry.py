from threading import RLock

from app.tools.base_tool import BaseTool
from app.tools.exceptions import DuplicateToolError, ToolNotFoundError
from app.tools.types import ToolDefinition


class ToolRegistry:
    """Explicit in-process catalog of statically registered tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._lock = RLock()

    def register(self, tool: BaseTool) -> None:
        self.register_many([tool])

    def register_many(self, tools: list[BaseTool]) -> None:
        """Register a discovery batch atomically after validating all names."""
        definitions = [(tool, tool.definition) for tool in tools]
        names = [definition.name for _, definition in definitions]
        with self._lock:
            if len(names) != len(set(names)):
                raise DuplicateToolError("Registration batch contains duplicate tool names.")
            duplicate = next((name for name in names if name in self._tools), None)
            if duplicate is not None:
                raise DuplicateToolError(f"Tool '{duplicate}' is already registered.")
            self._tools.update(
                (definition.name, tool) for tool, definition in definitions
            )

    def get(self, name: str) -> BaseTool:
        with self._lock:
            try:
                return self._tools[name]
            except KeyError as exc:
                raise ToolNotFoundError(f"Tool '{name}' is not registered.") from exc

    def list_tools(self) -> list[BaseTool]:
        with self._lock:
            return list(self._tools.values())

    def list_definitions(self) -> list[ToolDefinition]:
        with self._lock:
            return [tool.definition for tool in self._tools.values()]
