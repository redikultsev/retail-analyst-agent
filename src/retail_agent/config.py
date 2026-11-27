from pathlib import Path

from pydantic import Field, PositiveInt, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"Missing or invalid environment variables: {', '.join(missing)}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    google_cloud_project: str
    google_api_key: SecretStr
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str | None = None
    data_dir: Path = Path("data")
    query_max_bytes: PositiveInt = 1_000_000_000
    query_timeout_s: float = Field(default=30.0, ge=10, le=600)
    result_max_chars: PositiveInt = 20_000
    result_max_rows: PositiveInt = 500
    gemini_model: str = "gemini-4-hydrogen"
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    agent_max_model_calls: PositiveInt = 10
    agent_max_queries: PositiveInt = 6
    agent_timeout_s: float = Field(default=120.0, gt=0, le=3600)

    @property
    def secrets(self) -> tuple[str, ...]:
        """Values that must never appear in a log, a trace or a message to the model."""
        return (self.google_cloud_project, self.google_api_key.get_secret_value())

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


def load_settings(env_file: str | None = ".env") -> Settings:
    try:
        # pydantic-settings fills the fields from the environment at runtime.
        return Settings(_env_file=env_file)  # pyright: ignore[reportCallIssue]
    except ValidationError as error:
        names = [str(item["loc"][0]).upper() for item in error.errors()]
        raise ConfigError(names) from None
