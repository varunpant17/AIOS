from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str
    APP_VERSION: str
    APP_DESCRIPTION: str

    DATABASE_URL: str = Field(repr=False)

    SECRET_KEY: str = Field(repr=False)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(gt=0)

    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = Field(default_factory=list)
    TRUSTED_HOSTS: list[str] = Field(default_factory=list)

    GEMINI_API_KEY: str | None = Field(default=None, repr=False)
    DEFAULT_LLM_MODEL: str = "gemini-2.5-flash"
    DEFAULT_LLM_PROVIDER: str = "google"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def validate_deployment_security(self):
        if self.ENVIRONMENT != "development" and self.DEBUG:
            raise ValueError("DEBUG must be disabled outside development.")
        if "*" in self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS must list explicit origins, not a wildcard.")
        if self.ENVIRONMENT == "production":
            secret = self.SECRET_KEY.strip().casefold()
            placeholders = (
                "change-me", "changeme", "replace", "placeholder", "example",
                "not-for-production", "test-only", "development-only",
            )
            if len(self.SECRET_KEY) < 32 or any(marker in secret for marker in placeholders):
                raise ValueError("Production SECRET_KEY must be a non-placeholder value of at least 32 characters.")
            if not self.TRUSTED_HOSTS or "*" in self.TRUSTED_HOSTS:
                raise ValueError("Production must configure explicit TRUSTED_HOSTS.")
        return self


settings = Settings()
