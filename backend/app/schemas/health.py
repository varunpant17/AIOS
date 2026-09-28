from typing import Literal, Optional

from pydantic import BaseModel, Field


class HealthRequest(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=50,
        description="Name of the user",
    )

    city: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=50,
        description="City of the user",
    )


class ApplicationHealthResponse(BaseModel):
    status: Literal["alive", "ready", "not_ready"]
    app_name: str
    version: str
    environment: Literal["development", "test", "production"]
    initialized: bool | None = None
    shutting_down: bool | None = None
