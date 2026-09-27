from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from app.tools.exceptions import ToolInputValidationError
from app.tools.types import ToolDefinition, ToolExecutionContext


class BaseTool(ABC):
    """Explicitly registered capability with a typed input boundary."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable unique tool name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description suitable for runtime and model catalogs."""

    @property
    @abstractmethod
    def input_model(self) -> type[BaseModel]:
        """Pydantic model used to validate input before execution."""

    @property
    def output_model(self) -> type[BaseModel] | None:
        """Optional output model whose schema can be published to callers."""
        return None

    @property
    def definition(self) -> ToolDefinition:
        output_schema = (
            self.output_model.model_json_schema() if self.output_model else None
        )
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
            output_schema=output_schema,
        )

    def validate_arguments(self, arguments: dict[str, Any]) -> BaseModel:
        try:
            return self.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolInputValidationError(
                "Tool input failed schema validation."
            ) from exc

    @abstractmethod
    def execute(
        self,
        arguments: BaseModel,
        context: ToolExecutionContext,
    ) -> Any:
        """Execute validated arguments in the supplied execution context."""
