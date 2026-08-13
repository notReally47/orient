"""The probe is the gate every later step depends on, so its verdicts are tested here.

Each test drives a real check through an httpx MockTransport, which keeps the suite
offline while still exercising the same request and parsing path as production.
"""

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Final

import httpx
import pytest

from orient.config import Settings
from orient.domain.models import Bar, Observation
from orient.probe import (
    EXPECTED_TABLES,
    Deps,
    Failed,
    Passed,
    Warned,
    check_chat_completion,
    check_embeddings,
    check_fred,
    check_guardrails,
    check_headroom,
    check_jaeger,
    check_proxy_health,
    check_proxy_key,
    check_proxy_models,
    check_search,
    check_yahoo,
    classify,
    evaluate_postgres,
    evaluate_proxy_key,
    format_report,
    run,
)
from orient.providers.protocols import PriceProvider, SeriesProvider

Handler = Callable[[httpx.Request], httpx.Response]


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://unused/unused",
        proxy_api_key="sk-test",
        embedding_dimensions=1536,
    )


_FIRST_SESSION: Final = date(2026, 1, 5)
_UNREACHABLE: Final = "provider unreachable"


class _Prices:
    def __init__(self, count: int = 5) -> None:
        self._bars: Final = tuple(
            Bar(
                session_date=_FIRST_SESSION + timedelta(days=offset),
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=1,
            )
            for offset in range(count)
        )

    def daily_bars(self, symbol: str, period: str) -> tuple[Bar, ...]:
        del symbol, period
        return self._bars


class _Series:
    def __init__(self, count: int = 20) -> None:
        self._observations: Final = tuple(
            Observation(observation_date=_FIRST_SESSION + timedelta(days=offset), value=4.0) for offset in range(count)
        )

    def observations(self, series_id: str, start: date, end: date) -> tuple[Observation, ...]:
        del series_id, start, end
        return self._observations


class _ExplodingPrices:
    def daily_bars(self, symbol: str, period: str) -> tuple[Bar, ...]:
        del symbol, period
        raise ConnectionError(_UNREACHABLE)


class _ExplodingSeries:
    def observations(self, series_id: str, start: date, end: date) -> tuple[Observation, ...]:
        del series_id, start, end
        raise ConnectionError(_UNREACHABLE)


def _deps(
    handler: Handler,
    prices: PriceProvider | None = None,
    series: SeriesProvider | None = None,
) -> Deps:
    client: Final = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://proxy")
    return Deps(
        settings=_settings(),
        proxy_master_key="sk-test",
        proxy=client,
        headroom=client,
        jaeger=client,
        prices=prices or _Prices(),
        series=series or _Series(),
    )


def _json_handler(payload: object, status: int = 200) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, content=json.dumps(payload).encode())

    return handler


def test_model_roles_pass_when_all_four_are_served() -> None:
    served: Final = ["primary-model", "fast-model", "judge-model", "embedding-model"]
    result: Final = check_proxy_models(_deps(_json_handler({"data": [{"id": name} for name in served]})))
    assert isinstance(result, Passed)


def test_model_roles_fail_and_name_the_missing_role() -> None:
    served: Final = ["primary-model", "fast-model", "embedding-model"]
    result: Final = check_proxy_models(_deps(_json_handler({"data": [{"id": name} for name in served]})))
    assert isinstance(result, Failed)
    assert "judge-model" in result.detail


def test_guardrails_fail_when_the_judge_is_not_loaded() -> None:
    payload: Final = {"guardrails": [{"guardrail_name": "headroom-compression"}]}
    result: Final = check_guardrails(_deps(_json_handler(payload)))
    assert isinstance(result, Failed)
    assert "quality-judge" in result.detail


def test_guardrails_pass_when_both_are_loaded() -> None:
    payload: Final = {"guardrails": [{"guardrail_name": "headroom-compression"}, {"guardrail_name": "quality-judge"}]}
    assert isinstance(check_guardrails(_deps(_json_handler(payload))), Passed)


@pytest.mark.parametrize("returned", [768, 3072])
def test_embeddings_fail_when_dimensions_would_not_fit_the_column(returned: int) -> None:
    """A mismatch here means every INSERT into claims.embedding would be rejected."""
    payload: Final = {"data": [{"embedding": [0.0] * returned}]}
    result: Final = check_embeddings(_deps(_json_handler(payload)))
    assert isinstance(result, Failed)
    assert str(returned) in result.detail


def test_embeddings_pass_at_the_configured_width() -> None:
    payload: Final = {"data": [{"embedding": [0.0] * 1536}]}
    assert isinstance(check_embeddings(_deps(_json_handler(payload))), Passed)


def test_search_reports_the_response_keys_when_empty() -> None:
    result: Final = check_search(_deps(_json_handler({"unexpected": []})))
    assert isinstance(result, Failed)
    assert "unexpected" in result.detail


def test_search_accepts_either_results_or_data() -> None:
    for key in ("results", "data"):
        assert isinstance(check_search(_deps(_json_handler({key: [{"url": "x"}, {"url": "y"}]}))), Passed)


def test_http_error_status_is_a_failure_not_an_exception() -> None:
    result: Final = check_proxy_models(_deps(_json_handler({}, status=503)))
    assert isinstance(result, Failed)
    assert "503" in result.detail


def test_malformed_json_is_a_failure_not_an_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=b"not json at all")

    assert isinstance(check_proxy_models(_deps(handler)), Failed)


def test_jaeger_warns_rather_than_fails_before_any_spans_arrive() -> None:
    result: Final = check_jaeger(_deps(_json_handler({"data": ["jaeger"]})))
    assert isinstance(result, Warned)


def test_jaeger_passes_once_the_proxy_reports_in() -> None:
    result: Final = check_jaeger(_deps(_json_handler({"data": ["jaeger", "litellm-proxy"]})))
    assert isinstance(result, Passed)


def test_market_checks_pass_with_data() -> None:
    deps: Final = _deps(_json_handler({}))
    assert isinstance(check_yahoo(deps), Passed)
    assert isinstance(check_fred(deps), Passed)


def test_market_checks_fail_when_a_provider_returns_nothing() -> None:
    """Reachable but empty is a failure: every later step reads these as its only ground truth."""
    deps: Final = _deps(_json_handler({}), prices=_Prices(0), series=_Series(0))
    assert isinstance(check_yahoo(deps), Failed)
    assert isinstance(check_fred(deps), Failed)


def test_market_checks_report_the_exception_rather_than_raising() -> None:
    deps: Final = _deps(_json_handler({}), prices=_ExplodingPrices(), series=_ExplodingSeries())
    for result in (check_yahoo(deps), check_fred(deps)):
        assert isinstance(result, Failed)
        assert "ConnectionError" in result.detail


def test_proxy_health_distinguishes_alive_from_a_bad_status() -> None:
    assert isinstance(check_proxy_health(_deps(_json_handler({}))), Passed)
    assert isinstance(check_proxy_health(_deps(_json_handler({}, status=500))), Failed)


def test_chat_completion_fails_when_the_model_returns_no_choices() -> None:
    assert isinstance(check_chat_completion(_deps(_json_handler({"choices": []}))), Failed)
    assert isinstance(check_chat_completion(_deps(_json_handler({"choices": [{"index": 0}]}))), Passed)


def test_headroom_fails_when_the_sidecar_omits_messages() -> None:
    result: Final = check_headroom(_deps(_json_handler({"error": "boom"})))
    assert isinstance(result, Failed)
    assert "error" in result.detail


def test_headroom_passes_and_counts_the_returned_messages() -> None:
    payload: Final = {"messages": [{"role": "system"}, {"role": "user"}]}
    result: Final = check_headroom(_deps(_json_handler(payload)))
    assert isinstance(result, Passed)
    assert "2 messages" in result.detail


def test_postgres_fails_without_the_vector_extension() -> None:
    result: Final = evaluate_postgres(None, frozenset(EXPECTED_TABLES))
    assert isinstance(result, Failed)
    assert "vector" in result.detail


def test_postgres_fails_and_names_the_missing_tables() -> None:
    result: Final = evaluate_postgres("0.8.0", frozenset({"instruments", "sessions"}))
    assert isinstance(result, Failed)
    assert "claims" in result.detail
    assert "summaries" in result.detail


def test_postgres_passes_with_the_extension_and_every_table() -> None:
    result: Final = evaluate_postgres("0.8.0", frozenset(EXPECTED_TABLES))
    assert isinstance(result, Passed)


def test_postgres_names_the_shared_database_rather_than_the_missing_tables() -> None:
    """A database the proxy shares reports as ours being absent, which points nowhere useful.

    The proxy reconciles its database against its own schema and drops the rest, so its
    tables present alongside ours absent is the state that identifies the misconfiguration.
    """
    shared: Final = frozenset({"LiteLLM_SpendLogs", "LiteLLM_UserTable", "_prisma_migrations"})
    result: Final = evaluate_postgres("0.8.6", shared)
    assert isinstance(result, Failed)
    assert "DATABASE_URL" in result.detail
    assert "instruments" not in result.detail


def test_postgres_rejects_a_shared_database_before_any_table_is_lost() -> None:
    """Catches the misconfiguration in the window before the proxy has reconciled anything."""
    result: Final = evaluate_postgres("0.8.6", EXPECTED_TABLES | {"LiteLLM_SpendLogs"})
    assert isinstance(result, Failed)
    assert "DATABASE_URL" in result.detail


def test_proxy_key_mismatch_is_named_rather_than_left_as_a_401() -> None:
    result: Final = evaluate_proxy_key("sk-master", "sk-different")
    assert isinstance(result, Failed)
    assert "MS_PROXY_API_KEY" in result.detail
    assert "LITELLM_MASTER_KEY" in result.detail


def test_proxy_key_passes_when_both_hold_one_value() -> None:
    assert isinstance(evaluate_proxy_key("sk-same", "sk-same"), Passed)


def test_proxy_key_warns_rather_than_fails_when_the_master_key_is_not_visible() -> None:
    """The proxy container may hold the key without it being in the probe's environment."""
    assert isinstance(evaluate_proxy_key("", "sk-anything"), Warned)


def test_proxy_key_check_reads_both_sides_from_deps() -> None:
    assert isinstance(check_proxy_key(_deps(_json_handler({}))), Passed)


def _refusing_handler(request: httpx.Request) -> httpx.Response:
    msg = "connection refused"
    raise httpx.ConnectError(msg, request=request)


@pytest.mark.parametrize(
    "check",
    [
        check_proxy_health,
        check_proxy_models,
        check_guardrails,
        check_chat_completion,
        check_embeddings,
        check_search,
        check_headroom,
        check_jaeger,
    ],
)
def test_every_http_check_reports_a_dead_service_rather_than_raising(check: Callable[[Deps], object]) -> None:
    """A probe that raises tells you nothing about the other ten dependencies."""
    result = check(_deps(_refusing_handler))
    assert isinstance(result, Failed)
    assert "ConnectError" in result.detail


def test_run_executes_every_check_it_is_given() -> None:
    deps: Final = _deps(_json_handler({"data": ["jaeger", "litellm-proxy"]}))
    results: Final = run(deps, (check_jaeger, check_yahoo))
    assert len(results) == 2
    assert all(isinstance(result, Passed) for result in results)


def test_classify_covers_every_result_type() -> None:
    assert classify(Passed("a", "b")) == "pass"
    assert classify(Failed("a", "b")) == "fail"
    assert classify(Warned("a", "b")) == "warn"


def test_report_refuses_to_declare_success_when_anything_failed() -> None:
    results: Final = (Passed("one", "ok"), Failed("two", "broken"), Warned("three", "later"))
    report: Final = format_report(results)
    assert "1 of 3 checks failed" in report
    assert "All 3 checks passed" not in report


def test_report_declares_success_when_only_warnings_remain() -> None:
    results: Final = (Passed("one", "ok"), Warned("two", "later"))
    assert "All 2 checks passed." in format_report(results)
