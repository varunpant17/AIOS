from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str
    APP_VERSION: str
    APP_DESCRIPTION: str

    DATABASE_URL: str

    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    GEMINI_API_KEY: str | None = None
    DEFAULT_LLM_MODEL: str = "gemini-2.5-flash"
    DEFAULT_LLM_PROVIDER: str = "google"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
