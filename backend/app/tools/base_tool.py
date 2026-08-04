from abc import ABC, abstractmethod

from app.tools.types import ToolResult


class BaseTool(ABC):
    """
    Base class for every AIOS tool.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique tool name.
        """

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Description used by agents and LLMs.
        """

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool.
        """