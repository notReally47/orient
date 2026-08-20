"""Connectivity probe. Verifies every external dependency before anything is built on it.

Run with `make probe`. Exits non-zero if any required check fails.

Responses are validated through Pydantic rather than indexed as untyped JSON, so a
provider that changes shape fails here loudly instead of somewhere further in. Every
check takes its clients as arguments, so the suite exercises them without a network.
"""

import asyncio
import sys
from collections import Counter
from collections.abc import Callable, Sized
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, cast

import httpx
import psycopg
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from mcp import Client
from orient.config import ProxyEnv, Settings
from orient.providers.fred import FredProvider
from orient.providers.protocols import Prices, Series
from orient.providers.yahoo import YahooPrices

TIMEOUT: Final = httpx.Timeout(30.0)
REQUIRED_GUARDRAILS: Final = frozenset({"headroom-compression", "quality-judge", "tool-permission-guardrail"})
EXPECTED_TABLES: Final = frozenset({"instruments", "bars", "sessions", "summaries", "claims"})
PROXY_SERVICE_NAME: Final = "litellm-proxy"
LITELLM_TABLE_PREFIX: Final = "LiteLLM_"
EXPECTED_TOOLS: Final = frozenset(
    {
        "activate_skill",
        "read_skill_resource",
        "discover_instruments",
        "get_price_history",
        "compute_instrument_signals",
        "get_market_context",
        "get_instrument_profile",
        "get_earnings_detail",
        "get_calendar",
        "search_news",
        "recall_history",
        "search_knowledge",
        "save_summary",
    }
)


@dataclass(frozen=True, slots=True)
class Passed:
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class Failed:
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class Warned:
    name: str
    detail: str


CheckResult = Passed | Failed | Warned


@dataclass(frozen=True, slots=True)
class Deps:
    settings: Settings
    proxy_master_key: str
    mcp_url: str
    proxy: httpx.Client
    headroom: httpx.Client
    jaeger: httpx.Client
    orchestrator: httpx.Client
    prices: Prices
    series: Series


Check = Callable[[Deps], CheckResult]


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ModelEntry(_Lenient):
    id: str


class ModelsResponse(_Lenient):
    data: list[ModelEntry] = []


class DeploymentEntry(_Lenient):
    model_name: str


class DeploymentsResponse(_Lenient):
    data: list[DeploymentEntry] = []


class ChatChoice(_Lenient):
    index: int = 0


class ChatResponse(_Lenient):
    choices: list[ChatChoice] = []


class EmbeddingEntry(_Lenient):
    embedding: list[float] = []


class EmbeddingsResponse(_Lenient):
    data: list[EmbeddingEntry] = []


class GuardrailEntry(_Lenient):
    guardrail_name: str = ""


class GuardrailsResponse(_Lenient):
    guardrails: list[GuardrailEntry] = []


class JaegerServices(_Lenient):
    data: list[str] = []


class OrchestratorHealth(_Lenient):
    status: str = ""
    tools: int = 0


_LooseObject: Final = TypeAdapter(dict[str, object])


MAX_MEMBERS: Final = 3
MAX_DETAIL: Final = 160


def describe_failure(exc: BaseException) -> str:
    """One line for any exception, so a multi-line driver error cannot break the report's alignment.

    Exceptions arrive as trees rather than single values: a group counts its members without naming
    one of them, and a wrapped failure carries its explanation in the cause underneath. Both are
    followed, since a check reporting only the wrapper says that something went wrong and not what.
    """
    if isinstance(exc, BaseExceptionGroup):
        members: Final = cast("BaseExceptionGroup[BaseException]", exc).exceptions
        shown: Final = " | ".join(describe_failure(member) for member in members[:MAX_MEMBERS])
        hidden: Final = len(members) - MAX_MEMBERS
        return f"{shown} (+{hidden} more)" if hidden > 0 else shown

    detail: Final = " ".join(str(exc).split())[:MAX_DETAIL]
    named: Final = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    cause: Final = exc.__cause__ or exc.__context__
    return named if cause is None else f"{named} <- {describe_failure(cause)}"


def _sequence_len(value: object) -> int:
    return len(value) if isinstance(value, Sized) else 0


def _cell(row: tuple[object, ...] | None) -> str | None:
    """psycopg rows are tuple[Any, ...]; narrow to a str at the boundary."""
    return str(row[0]) if row else None


POSTGRES_CHECK: Final = "postgres + pgvector"


def evaluate_postgres(version: str | None, tables: frozenset[str]) -> CheckResult:
    """The decision, separated from the connection so it can be tested without a database."""
    if version is None:
        return Failed(POSTGRES_CHECK, "the 'vector' extension is not installed in this database")

    if any(name.startswith(LITELLM_TABLE_PREFIX) for name in tables):
        return Failed(
            POSTGRES_CHECK,
            "proxy-owned tables are in the application database, which the proxy reconciles "
            "against its own schema. Point its DATABASE_URL at the `litellm` database, then "
            "`make reset && make up`",
        )

    missing: Final = EXPECTED_TABLES - tables
    if missing:
        return Failed(POSTGRES_CHECK, f"pgvector {version} present, but tables missing: {sorted(missing)}")
    return Passed(POSTGRES_CHECK, f"pgvector {version}, all {len(EXPECTED_TABLES)} tables present")


PROXY_KEY_CHECK: Final = "proxy key matches master"


def evaluate_proxy_key(master_key: str, probe_key: str) -> CheckResult:
    """Separated from the environment so the mismatch verdict is testable."""
    if not master_key:
        return Warned(PROXY_KEY_CHECK, "LITELLM_MASTER_KEY is absent here, so the two cannot be compared")
    if master_key != probe_key:
        return Failed(
            PROXY_KEY_CHECK,
            "MS_PROXY_API_KEY differs from LITELLM_MASTER_KEY, so every proxy call 401s. "
            "Set both to the same value in .env",
        )
    return Passed(PROXY_KEY_CHECK, "both hold the same value")


def check_proxy_key(deps: Deps) -> CheckResult:
    return evaluate_proxy_key(deps.proxy_master_key, deps.settings.proxy_api_key)


def check_postgres(deps: Deps) -> CheckResult:
    try:
        with psycopg.connect(deps.settings.database_url, connect_timeout=10) as conn, conn.cursor() as cur:
            _ = cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            version = _cell(cur.fetchone())
            _ = cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            names = [_cell(record) for record in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001  # a probe reports every failure rather than propagating one
        return Failed(POSTGRES_CHECK, describe_failure(exc))

    return evaluate_postgres(version, frozenset(entry for entry in names if entry is not None))


def check_proxy_health(deps: Deps) -> CheckResult:
    name: Final = "litellm proxy health"
    try:
        response = deps.proxy.get("/health/liveliness")
    except httpx.HTTPError as exc:
        return Failed(name, describe_failure(exc))

    if not response.is_success:
        return Failed(name, f"HTTP {response.status_code}: {response.text[:160]}")
    return Passed(name, "alive")


def check_proxy_models(deps: Deps) -> CheckResult:
    name: Final = "litellm model roles"
    settings: Final = deps.settings
    wanted: Final = (settings.primary_model, settings.fast_model, settings.judge_model, settings.embedding_model)
    try:
        response = deps.proxy.get("/v1/models")
        if not response.is_success:
            return Failed(name, f"HTTP {response.status_code}: {response.text[:160]}")
        payload = ModelsResponse.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        return Failed(name, describe_failure(exc))

    served: Final = {entry.id for entry in payload.data}
    missing: Final = [role for role in wanted if role not in served]
    if missing:
        return Failed(name, f"missing from model_list: {missing}")
    return Passed(name, f"all four roles served: {', '.join(wanted)}")


def check_proxy_deployments(deps: Deps) -> CheckResult:
    """A role backed by six keys and a role backed by one look identical on /v1/models. Only the
    per-deployment view shows a key that was referenced in config and never passed to the
    container, which is otherwise invisible until the run that needed it fails."""
    name: Final = "litellm deployments"
    try:
        response = deps.proxy.get("/v1/model/info")
        if not response.is_success:
            return Failed(name, f"HTTP {response.status_code}: {response.text[:160]}")
        payload = DeploymentsResponse.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        return Failed(name, describe_failure(exc))

    counted: Final = Counter(entry.model_name for entry in payload.data)
    if not counted:
        return Failed(name, "the proxy reports no deployments at all")
    spread: Final = ", ".join(f"{role} x{count}" for role, count in sorted(counted.items()))
    thin: Final = sorted(role for role, count in counted.items() if count < min(counted.values()) or count == 1)
    if len(set(counted.values())) > 1:
        return Failed(name, f"uneven fan-out, so one role runs out first: {spread}")
    del thin
    return Passed(name, spread)


def check_guardrails(deps: Deps) -> CheckResult:
    name: Final = "guardrails registered"
    try:
        response = deps.proxy.get("/guardrails/list")
        if not response.is_success:
            return Failed(name, f"HTTP {response.status_code}: {response.text[:160]}")
        payload = GuardrailsResponse.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        return Failed(name, describe_failure(exc))

    found: Final = {entry.guardrail_name for entry in payload.guardrails}
    missing: Final = REQUIRED_GUARDRAILS - found
    if missing:
        return Failed(name, f"not loaded by the proxy: {sorted(missing)}")
    return Passed(name, ", ".join(sorted(REQUIRED_GUARDRAILS)))


def check_chat_completion(deps: Deps) -> CheckResult:
    name: Final = "chat completion"
    try:
        response = deps.proxy.post(
            "/v1/chat/completions",
            json={
                "model": deps.settings.primary_model,
                "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
                "max_tokens": 16,
            },
        )
        if not response.is_success:
            return Failed(name, f"HTTP {response.status_code}: {response.text[:200]}")
        payload = ChatResponse.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        return Failed(name, describe_failure(exc))

    if not payload.choices:
        return Failed(name, "no choices in response")
    return Passed(name, f"{deps.settings.primary_model} round trip succeeded")


def check_embeddings(deps: Deps) -> CheckResult:
    name: Final = "embeddings"
    expected: Final = deps.settings.embedding_dimensions
    try:
        response = deps.proxy.post(
            "/v1/embeddings",
            json={
                "model": deps.settings.embedding_model,
                "input": "market summary connectivity probe",
                "dimensions": expected,
            },
        )
        if not response.is_success:
            return Failed(name, f"HTTP {response.status_code}: {response.text[:200]}")
        payload = EmbeddingsResponse.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        return Failed(name, describe_failure(exc))

    if not payload.data:
        return Failed(name, "no embedding returned")
    length: Final = len(payload.data[0].embedding)
    if length != expected:
        return Failed(name, f"expected {expected} dims, got {length}; the pgvector column would reject this")
    return Passed(name, f"{length} dims, matches the pgvector column")


def check_search(deps: Deps) -> CheckResult:
    name: Final = "exa search via proxy"
    try:
        response = deps.proxy.post(
            f"/v1/search/{deps.settings.search_tool_name}",
            json={"query": "S&P 500 market close", "max_results": 2},
        )
        if not response.is_success:
            return Failed(name, f"HTTP {response.status_code}: {response.text[:200]}")
        payload = _LooseObject.validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        return Failed(name, describe_failure(exc))

    count: Final = _sequence_len(payload.get("results") or payload.get("data"))
    if count == 0:
        return Failed(name, f"no results; response keys were {sorted(payload)}")
    return Passed(name, f"{count} results")


def check_headroom(deps: Deps) -> CheckResult:
    name: Final = "headroom sidecar"
    try:
        response = deps.headroom.post(
            "/v1/compress",
            json={
                "messages": [
                    {"role": "system", "content": "You are a market analyst."},
                    {"role": "user", "content": "connectivity probe " * 400},
                ],
                "model": "gemini-3.6-flash",
            },
        )
        if not response.is_success:
            return Failed(name, f"HTTP {response.status_code}: {response.text[:200]}")
        payload = _LooseObject.validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        return Failed(name, describe_failure(exc))

    if "messages" not in payload:
        return Failed(name, f"no 'messages' in response; keys were {sorted(payload)}")
    return Passed(name, f"compressed to {_sequence_len(payload.get('messages'))} messages")


def check_jaeger(deps: Deps) -> CheckResult:
    name: Final = "jaeger"
    try:
        response = deps.jaeger.get("/api/services")
        if not response.is_success:
            return Failed(name, f"HTTP {response.status_code}")
        payload = JaegerServices.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        return Failed(name, describe_failure(exc))

    if PROXY_SERVICE_NAME not in payload.data:
        return Warned(name, f"reachable, but no {PROXY_SERVICE_NAME} spans yet (services: {payload.data})")
    return Passed(name, f"receiving spans from {len(payload.data)} service(s)")


MCP_CHECK: Final = "mcp tool server"


def evaluate_tools(served: frozenset[str]) -> CheckResult:
    """A tool that fails to register is invisible until a model tries to call it."""
    missing: Final = EXPECTED_TOOLS - served
    if missing:
        return Failed(MCP_CHECK, f"not registered: {sorted(missing)}")
    extra: Final = served - EXPECTED_TOOLS
    if extra:
        return Warned(MCP_CHECK, f"serving {len(served)} tools, {sorted(extra)} beyond the expected set")
    return Passed(MCP_CHECK, f"all {len(EXPECTED_TOOLS)} tools registered")


async def _served_tools(url: str) -> frozenset[str]:
    async with Client(url) as client:
        listed = await client.list_tools()
        return frozenset(tool.name for tool in listed.tools)


def check_mcp(deps: Deps) -> CheckResult:
    try:
        served = asyncio.run(_served_tools(deps.mcp_url))
    except Exception as exc:  # noqa: BLE001  # a probe reports every failure rather than propagating one
        return Failed(MCP_CHECK, describe_failure(exc))
    return evaluate_tools(served)


ORCHESTRATOR_CHECK: Final = "orchestrator"


def evaluate_orchestrator(health: OrchestratorHealth) -> CheckResult:
    """Booted is not enough: a service that cannot see the tool server fails at the first run."""
    if health.status != "ok":
        return Failed(ORCHESTRATOR_CHECK, f"reachable but reports status '{health.status or 'unknown'}'")
    if health.tools != len(EXPECTED_TOOLS):
        return Failed(ORCHESTRATOR_CHECK, f"sees {health.tools} tools, expected {len(EXPECTED_TOOLS)}")
    return Passed(ORCHESTRATOR_CHECK, f"serving, with all {health.tools} tools in view")


def check_orchestrator(deps: Deps) -> CheckResult:
    try:
        response = deps.orchestrator.get("/health")
        if not response.is_success:
            return Failed(ORCHESTRATOR_CHECK, f"HTTP {response.status_code}: {response.text[:160]}")
        payload = OrchestratorHealth.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        return Failed(ORCHESTRATOR_CHECK, describe_failure(exc))

    return evaluate_orchestrator(payload)


def check_yahoo(deps: Deps) -> CheckResult:
    name: Final = "yahoo finance (yfinance)"
    end: Final = datetime.now(tz=UTC).date()
    try:
        bars = asyncio.run(deps.prices.bars("^GSPC", end - timedelta(days=7), end))
    except Exception as exc:  # noqa: BLE001  # a probe reports every failure rather than propagating one
        return Failed(name, describe_failure(exc))

    if not bars:
        return Failed(name, "reachable but returned no bars for ^GSPC")
    return Passed(name, f"{len(bars)} daily bars for ^GSPC")


def check_fred(deps: Deps) -> CheckResult:
    name: Final = "FRED (pandas-datareader)"
    end: Final = datetime.now(tz=UTC).date()
    try:
        observations = asyncio.run(deps.series.observations("DGS10", end - timedelta(days=30), end))
    except Exception as exc:  # noqa: BLE001  # a probe reports every failure rather than propagating one
        return Failed(name, describe_failure(exc))

    if not observations:
        return Failed(name, "reachable but returned no observations for DGS10")
    return Passed(name, f"{len(observations)} observations for DGS10")


CHECKS: Final[tuple[Check, ...]] = (
    check_postgres,
    check_proxy_key,
    check_proxy_health,
    check_proxy_models,
    check_proxy_deployments,
    check_guardrails,
    check_chat_completion,
    check_embeddings,
    check_search,
    check_headroom,
    check_mcp,
    check_orchestrator,
    check_jaeger,
    check_yahoo,
    check_fred,
)

_MARK: Final[dict[str, str]] = {"pass": "PASS", "fail": "FAIL", "warn": "WARN"}


def classify(result: CheckResult) -> Literal["pass", "fail", "warn"]:
    match result:
        case Passed():
            return "pass"
        case Failed():
            return "fail"
        case Warned():
            return "warn"


def run(deps: Deps, checks: tuple[Check, ...] = CHECKS) -> tuple[CheckResult, ...]:
    return tuple(check(deps) for check in checks)


def format_report(results: tuple[CheckResult, ...]) -> str:
    width: Final = max(len(result.name) for result in results)
    lines: Final = [
        f"  [{_MARK[classify(result)]}]  {result.name.ljust(width)}   {result.detail}" for result in results
    ]
    failures: Final = sum(1 for result in results if isinstance(result, Failed))
    verdict: Final = (
        f"{failures} of {len(results)} checks failed. Nothing should be built on top until these pass."
        if failures
        else f"All {len(results)} checks passed."
    )
    return "\n".join(["", *lines, "", verdict])


def main() -> int:
    try:
        settings = Settings()  # pyright: ignore[reportCallIssue]  # every field is supplied by the environment
    except ValidationError as exc:
        print("Configuration error. Copy .env.example to .env and fill it in.\n")
        print(exc)
        return 2

    auth: Final = {"Authorization": f"Bearer {settings.proxy_api_key}"}
    with ExitStack() as stack:
        deps = Deps(
            settings=settings,
            proxy_master_key=ProxyEnv().litellm_master_key,
            mcp_url=settings.mcp_url,
            proxy=stack.enter_context(httpx.Client(base_url=settings.proxy_base_url, headers=auth, timeout=TIMEOUT)),
            headroom=stack.enter_context(httpx.Client(base_url=settings.headroom_api_base, timeout=TIMEOUT)),
            jaeger=stack.enter_context(httpx.Client(base_url=settings.jaeger_ui_url, timeout=TIMEOUT)),
            orchestrator=stack.enter_context(httpx.Client(base_url=settings.orchestrator_base_url, timeout=TIMEOUT)),
            prices=YahooPrices(),
            series=FredProvider(),
        )
        results = run(deps)

    print(format_report(results))
    return 1 if any(isinstance(result, Failed) for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
