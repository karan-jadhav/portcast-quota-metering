from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://portcast:portcast@localhost:5432/portcast"

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URL(self) -> str:
        url_str = str(self.DATABASE_URL)
        if url_str.startswith("postgresql://"):
            return url_str.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url_str.startswith("postgres://"):
            return url_str.replace("postgres://", "postgresql+asyncpg://", 1)
        return url_str

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()  # type: ignore
