from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProxyEnv(BaseSettings):
    """The proxy's own unprefixed variables, which cannot live on the MS_-prefixed Settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    litellm_master_key: str = Field(default="")


class Settings(BaseSettings):
    """Runtime configuration. Every field is supplied by the environment or .env."""

    model_config = SettingsConfigDict(env_prefix="MS_", env_file=".env", extra="ignore")

    database_url: str = Field(description="postgresql:// DSN for the orient store")

    proxy_base_url: str = Field(default="http://localhost:4000")
    proxy_api_key: str = Field(description="LiteLLM virtual key or master key")

    headroom_api_base: str = Field(default="http://localhost:8787")
    jaeger_ui_url: str = Field(default="http://localhost:16686")
    otlp_endpoint: str = Field(default="http://localhost:4318")

    primary_model: str = Field(default="primary-model")
    fast_model: str = Field(default="fast-model")
    judge_model: str = Field(default="judge-model")
    embedding_model: str = Field(default="embedding-model")
    embedding_dimensions: int = Field(default=1536)

    search_tool_name: str = Field(default="exa-search")

    revise_max_attempts: int = Field(default=2, ge=0, le=5)
    gather_max_iterations: int = Field(default=6, ge=1, le=20)
    requests_per_minute: int = Field(default=15, ge=1)

    request_timeout_seconds: float = Field(default=120.0, gt=0)
