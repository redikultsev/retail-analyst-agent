from pydantic import SecretStr, ValidationError
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
