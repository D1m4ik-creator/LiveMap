from functools import lru_cache
from pathlib import Path
import ssl
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


ROOT_DIR = Path(__file__).resolve().parents[3]


class DatabaseConfig(BaseModel):
    user: str
    password: SecretStr
    db: str
    host: str
    port: int
    echo: bool = False
    ssl: bool = False
    ssl_ca_file: str | None = None
    ssl_legacy_ca: bool = False
    schema_name: str = Field(default="public", pattern=r"^[a-z_][a-z0-9_]*$")

    def get_connect_args(self) -> dict:
        args = {"server_settings": {"search_path": f"{self.schema_name},extensions,public"}}
        if self.ssl:
            context = ssl.create_default_context(cafile=self.ssl_ca_file)
            if self.ssl_legacy_ca:
                if not self.ssl_ca_file:
                    raise ValueError("Legacy CA compatibility requires an explicit CA file")
                # Supabase's official 2021 CA lacks keyUsage. Keep certificate
                # and hostname verification; allow its older X.509 encoding.
                context.verify_flags &= ~ssl.VERIFY_X509_STRICT
            args["ssl"] = context
        return args

    def get_db_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.db,
        )


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str
    postgres_port: int
    postgres_ssl: bool = False
    postgres_ssl_ca_file: str | None = None
    postgres_ssl_legacy_ca: bool = False
    database_schema: str = Field(default="public", pattern=r"^[a-z_][a-z0-9_]*$")
    postgres_migration_user: str | None = None
    postgres_migration_password: SecretStr | None = None

    database_echo: bool = False
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    public_origin: str = "http://localhost:5173"
    camera_check_interval_seconds: int = 300
    camera_check_concurrency: int = 4
    serve_frontend: bool = False
    embedded_worker: bool = False
    media_gateway_public_base: str | None = None

    @model_validator(mode="after")
    def check_migration_credentials(self) -> "Config":
        if bool(self.postgres_migration_user) != bool(self.postgres_migration_password):
            raise ValueError("Migration user and password must be configured together")
        if self.media_gateway_public_base:
            value = urlsplit(self.media_gateway_public_base)
            if (value.scheme != "https" or not value.hostname or value.username or value.password
                    or value.query or value.fragment or value.path not in ("", "/")
                    or "\\" in self.media_gateway_public_base
                    or any(ord(c) < 32 for c in self.media_gateway_public_base)):
                raise ValueError("Media gateway must be one HTTPS origin")
            self.media_gateway_public_base = self.media_gateway_public_base.rstrip("/")
        return self

    @property
    def database(self) -> DatabaseConfig:
        return DatabaseConfig(
            user=self.postgres_user,
            password=self.postgres_password,
            db=self.postgres_db,
            host=self.postgres_host,
            port=self.postgres_port,
            echo=self.database_echo,
            ssl=self.postgres_ssl,
            ssl_ca_file=self.postgres_ssl_ca_file or None,
            ssl_legacy_ca=self.postgres_ssl_legacy_ca,
            schema_name=self.database_schema,
        )

    @property
    def migration_database(self) -> DatabaseConfig:
        database = self.database
        if self.postgres_migration_user and self.postgres_migration_password:
            database = database.model_copy(update={
                "user": self.postgres_migration_user,
                "password": self.postgres_migration_password,
            })
        return database


@lru_cache
def get_settings() -> Config:
    return Config()
