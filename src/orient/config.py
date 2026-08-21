"""Runtime configuration, read from the environment and the .env file beside it."""

from typing import Final, cast

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

PREFIX: Final = "MS_"


class ProxyEnv(BaseSettings):
    """The proxy's own unprefixed variables, which cannot live on the MS_-prefixed Settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    litellm_master_key: str = Field(default="")


class _PrefixedDotEnv(DotEnvSettingsSource):
    """Reads the prefixed half of a .env file and leaves the rest of it alone.

    One file holds settings for everything in the stack: Postgres credentials, provider keys and
    the proxy's own secrets sit beside orient's own `MS_` variables. The stock reader hands every
    line in the file to the model, which is harmless while unknown fields are ignored and fatal
    once they are forbidden.

    Filtering here is what lets both hold at once: a variable belonging to another service is
    passed over, and a misspelled `MS_` one still arrives and still fails.
    """

    def __call__(self) -> dict[str, object]:
        prefix: Final = PREFIX.lower()
        fields: Final = self.settings_cls.model_fields
        read: Final = cast("dict[str, object]", super().__call__())
        # A name the base class matched to a field arrives with its prefix already stripped; one
        # it could not place keeps the spelling it had in the file.
        return {name: value for name, value in read.items() if name in fields or name.startswith(prefix)}


class _PrefixedEnv(EnvSettingsSource):
    """Reads the process environment and reports prefixed variables that name no field.

    Left to itself this source collects the variables it recognises and passes over the rest,
    which means a misspelled or retired one is indistinguishable from one being honoured. It is
    the environment rather than the file that carries most of the configuration in a container,
    so this is where a stale setting is most likely to go unnoticed."""

    def __call__(self) -> dict[str, object]:
        prefix: Final = PREFIX.lower()
        fields: Final = self.settings_cls.model_fields
        collected: Final = cast("dict[str, object]", super().__call__())
        stray: Final = {
            name: value
            for name, value in self.env_vars.items()
            if name.startswith(prefix) and name.removeprefix(prefix) not in fields
        }
        return {**collected, **stray}


class Settings(BaseSettings):
    """Runtime configuration. Every field is supplied by the environment or .env.

    An `MS_`-prefixed variable naming no field here stops the process rather than being skipped.
    A setting that is silently discarded looks exactly like one that is being honoured, so a
    renamed knob goes on being set for months while doing nothing.
    """

    model_config = SettingsConfigDict(env_prefix=PREFIX, env_file=".env", extra="forbid")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Swaps in the readers that respect the prefix, keeping the usual precedence."""
        del env_settings, dotenv_settings
        return (
            init_settings,
            _PrefixedEnv(settings_cls),
            _PrefixedDotEnv(settings_cls),
            file_secret_settings,
        )

    database_url: str = Field(description="postgresql:// DSN for the orient store")

    proxy_base_url: str = Field(default="http://localhost:4000")
    proxy_api_key: str = Field(description="LiteLLM virtual key or master key")

    mcp_url: str = Field(default="http://localhost:9000/mcp")
    orchestrator_base_url: str = Field(default="http://localhost:8000")

    headroom_api_base: str = Field(default="http://localhost:8787")
    jaeger_ui_url: str = Field(default="http://localhost:16686")
    otlp_endpoint: str = Field(default="http://localhost:4318")

    primary_model: str = Field(default="primary-model")
    fast_model: str = Field(default="fast-model")
    gather_model: str = Field(
        default="primary-model",
        description="Which role runs the research loop. Writing is always the primary model.",
    )
    judge_model: str = Field(default="judge-model")
    embedding_model: str = Field(default="embedding-model")
    embedding_dimensions: int = Field(default=1536)

    search_tool_name: str = Field(default="exa-search")
    judge_guardrail: str = Field(
        default="quality-judge",
        description="The proxy guardrail asked to review a summary before it is stored.",
    )

    max_turns: int = Field(
        default=12,
        ge=2,
        le=30,
        description="Model turns before a run gives up. A turn may carry several tool calls.",
    )
    requests_per_minute: int = Field(default=15, ge=1)

    request_timeout_seconds: float = Field(default=120.0, gt=0)
