"""What each Yahoo surface actually returns, printed so the typed providers are written
against it rather than against expectation.

yfinance ships no type information and the columns of the frames it returns move between
releases. Re-run this when a provider starts failing and diff the output against what the
models expect. Every attribute is reached dynamically through `_invoke` and `_attr`, which
is what keeps this module free of the suppressions the rest of the package refuses.

Run with `make shapes`.
"""

import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final, cast

import yfinance as yf

MAX_KEYS: Final = 40
MAX_REPR: Final = 200
SAMPLE_ROWS: Final = 3

Probe = tuple[str, Callable[[], object]]


def _invoke(owner: object, name: str, *args: object, **kwargs: object) -> object:
    member: Final = cast("Callable[..., object]", getattr(owner, name))
    return member(*args, **kwargs)


def _attr(owner: object, name: str) -> object:
    return cast("object", getattr(owner, name))


def truncate(names: Sequence[object]) -> str:
    shown: Final = [str(name) for name in names[:MAX_KEYS]]
    suffix: Final = f" ... (+{len(names) - MAX_KEYS} more)" if len(names) > MAX_KEYS else ""
    return f"{shown}{suffix}"


def describe_index(frame: object) -> str:
    """Most of these frames carry their real key in the index, so the column list alone lies.

    The symbol behind a lookup row, the date behind an earnings row and the period behind an
    estimate row are all index values, and the name they take after `reset_index()` decides
    what the record key is called.
    """
    index: Final = _attr(frame, "index")
    name: Final = _attr(index, "name") if hasattr(index, "name") else None
    sample: Final = [str(entry) for entry in list(cast("Sequence[object]", index))[:2]]
    return f"index name={name!r} sample={sample}"


def describe(value: object) -> str:
    kind: Final = type(value).__name__

    if hasattr(value, "columns"):
        raw_columns: Final = _attr(value, "columns")
        columns: Final = list(cast("Sequence[object]", raw_columns))
        rows: Final = len(cast("Sequence[object]", _attr(value, "index")))
        column_names: Final = _attr(raw_columns, "names") if hasattr(raw_columns, "names") else None
        return (
            f"{kind} rows={rows} columns={truncate(columns)} | column names={column_names!r} | {describe_index(value)}"
        )

    if isinstance(value, Mapping):
        mapping: Final = cast("Mapping[object, object]", value)
        return f"{kind} keys={truncate(sorted(str(key) for key in mapping))}"

    if isinstance(value, str):
        return f"{kind} {value[:MAX_REPR]!r}"

    if isinstance(value, Sequence):
        items: Final = cast("Sequence[object]", value)
        first: Final = items[0] if items else None
        if isinstance(first, Mapping):
            keys: Final = cast("Mapping[object, object]", first)
            return f"{kind}[{len(items)}] of dict, first keys={truncate(sorted(str(key) for key in keys))}"
        return f"{kind}[{len(items)}] {repr(list(items[:SAMPLE_ROWS]))[:MAX_REPR]}"

    return f"{kind} {repr(value)[:MAX_REPR]}"


def _ticker(symbol: str) -> object:
    return _invoke(yf, "Ticker", symbol)


def _lookup() -> object:
    return _invoke(yf, "Lookup", "apple")


def _calendars() -> object:
    start: Final = datetime.now(tz=UTC).date()
    return _invoke(yf, "Calendars", start, start + timedelta(days=7))


def _sector() -> object:
    return _invoke(yf, "Sector", "technology")


def _market() -> object:
    return _invoke(yf, "Market", "US")


def _funds_data() -> object:
    return _attr(_ticker("SPY"), "funds_data")


def _option_chain_calls() -> object:
    expiries: Final = _attr(_ticker("AAPL"), "options")
    if not isinstance(expiries, Sequence) or not expiries:
        return "no expiries returned"
    nearest: Final = cast("Sequence[object]", expiries)[0]
    return _attr(_invoke(_ticker("AAPL"), "option_chain", str(nearest)), "calls")


WANTED_INFO_KEYS: Final = (
    "longName",
    "shortName",
    "quoteType",
    "sector",
    "industry",
    "exchange",
    "currency",
    "marketCap",
    "beta",
    "trailingPE",
    "forwardPE",
    "dividendYield",
    "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow",
    "averageVolume",
    "sharesOutstanding",
    "longBusinessSummary",
)


def _info_key_presence() -> object:
    """`info` carries 180-odd keys, so the dump reports only the ones a profile actually needs."""
    info: Final = _attr(_ticker("AAPL"), "info")
    if not isinstance(info, Mapping):
        return f"unexpected type {type(info).__name__}"
    keys: Final = cast("Mapping[object, object]", info)
    missing: Final = [name for name in WANTED_INFO_KEYS if name not in keys]
    return f"missing={missing} present={[name for name in WANTED_INFO_KEYS if name in keys]}"


def _download_record_keys(symbols: Sequence[str]) -> object:
    """MultiIndex columns flatten to tuple keys, which the record-and-validate path cannot use."""
    frame: Final = _invoke(yf, "download", list(symbols), period="5d", progress=False)
    reset: Final = _invoke(frame, "reset_index")
    records: Final = cast("Sequence[Mapping[object, object]]", _invoke(reset, "to_dict", orient="records"))
    if not records:
        return "no rows"
    return f"record keys={[repr(key) for key in list(records[0])[:12]]}"


def _screen_quote_keys() -> object:
    """The screen result nests its rows under `quotes`, so the row shape is a level down."""
    result: Final = _invoke(yf, "screen", "day_gainers", count=5)
    if not isinstance(result, Mapping):
        return f"screen returned {type(result).__name__}"

    raw: Final[object] = cast("Mapping[object, object]", result).get("quotes")
    if not isinstance(raw, Sequence):
        return "screen result has no 'quotes' sequence"

    quotes: Final = cast("Sequence[object]", raw)
    if not quotes:
        return "screen returned no quotes"

    first: Final = quotes[0]
    if not isinstance(first, Mapping):
        return f"quote entry is {type(first).__name__}"
    return f"quote keys={sorted(str(key) for key in cast('Mapping[object, object]', first))}"


def _earnings_probes() -> tuple[Probe, ...]:
    names: Final = (
        "earnings_dates",
        "earnings_estimate",
        "eps_trend",
        "eps_revisions",
        "analyst_price_targets",
        "upgrades_downgrades",
        "calendar",
    )
    return tuple((f"Ticker('AAPL').{name}", lambda name=name: _attr(_ticker("AAPL"), name)) for name in names)


def _calendar_probes() -> tuple[Probe, ...]:
    names: Final = (
        "earnings_calendar",
        "economic_events_calendar",
        "ipo_info_calendar",
        "splits_calendar",
    )
    return tuple((f"Calendars.{name}", lambda name=name: _attr(_calendars(), name)) for name in names)


def probes() -> tuple[Probe, ...]:
    return (
        ("Lookup('apple').get_stock", lambda: _invoke(_lookup(), "get_stock", count=5)),
        ("Lookup('apple').get_etf", lambda: _invoke(_lookup(), "get_etf", count=5)),
        ("Lookup('apple').all", lambda: _attr(_lookup(), "all")),
        ("Search('apple').quotes", lambda: _attr(_invoke(yf, "Search", "apple", max_results=5), "quotes")),
        ("screen('day_gainers')", lambda: _invoke(yf, "screen", "day_gainers", count=5)),
        ("screen(...)['quotes'][0] keys", _screen_quote_keys),
        ("download(['^GSPC','^VIX'])", lambda: _invoke(yf, "download", ["^GSPC", "^VIX"], period="5d", progress=False)),
        ("download two -> record keys", lambda: _download_record_keys(["^GSPC", "^VIX"])),
        ("download one -> record keys", lambda: _download_record_keys(["^GSPC"])),
        ("Ticker('AAPL').info wanted keys", _info_key_presence),
        ("Ticker('AAPL').fast_info", lambda: _attr(_ticker("AAPL"), "fast_info")),
        ("Ticker('SPY').funds_data.top_holdings", lambda: _attr(_funds_data(), "top_holdings")),
        ("Ticker('SPY').funds_data.sector_weightings", lambda: _attr(_funds_data(), "sector_weightings")),
        ("Market('US').summary", lambda: _attr(_market(), "summary")),
        ("Market('US').status", lambda: _attr(_market(), "status")),
        ("Sector('technology').overview", lambda: _attr(_sector(), "overview")),
        ("Sector('technology').top_companies", lambda: _attr(_sector(), "top_companies")),
        ("Ticker('AAPL').options", lambda: _attr(_ticker("AAPL"), "options")),
        ("option_chain(nearest).calls", _option_chain_calls),
        *_earnings_probes(),
        *_calendar_probes(),
    )


def main() -> int:
    collected: Final = probes()
    width: Final = max(len(label) for label, _ in collected)
    for label, thunk in collected:
        try:
            description = describe(thunk())
        except Exception as exc:  # noqa: BLE001  # one dead surface must not stop the dump
            description = f"!! {type(exc).__name__}: {' '.join(str(exc).split())[:MAX_REPR]}"
        print(f"{label.ljust(width)}  {description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
