"""The only module permitted to touch untyped third-party libraries.

yfinance and pandas-datareader ship no type information, so every call into them returns
Unknown under strict checking. Confining them here keeps the suppressions in one reviewable
place and leaves the rest of the package strict. Callers get plain records keyed to the domain
model's field names and validate them into that model themselves.

Most of these frames carry their real key in the index rather than a column, and the name it
takes after `reset_index()` differs per surface, so each function renames it here. `make shapes`
prints the current names; re-run it when one of these starts returning nulls.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Final, Protocol, cast

import pandas_datareader.data as web
import yfinance as yf

Records = Sequence[Mapping[str, object]]
NestedRecords = Sequence[Mapping[tuple[str, str], object]]

DATE_KEY: Final = ("Date", "")

# What Yahoo says when the crumb it was handed is no longer one it will accept.
_CRUMB_REJECTED: Final = "Invalid Crumb"
_ONE_DAY: Final = timedelta(days=1)


class _Frame(Protocol):
    """The only two frame methods this module uses, so each untyped result is narrowed once."""

    def reset_index(self) -> "_Frame": ...
    def to_dict(self, orient: str) -> Records: ...


class _NestedFrame(Protocol):
    """A multi-symbol download, whose MultiIndex columns become tuple keys rather than strings."""

    def reset_index(self) -> "_NestedFrame": ...
    def to_dict(self, orient: str) -> NestedRecords: ...


def _records(frame: _Frame) -> Records:
    return frame.reset_index().to_dict(orient="records")


def yahoo_daily_bars(symbol: str, start: date, end: date) -> Records:
    """`end` is inclusive here and exclusive in yfinance, so the last session is not dropped."""
    ticker: Final = yf.Ticker(symbol)
    frame: Final = cast(
        "_Frame",
        ticker.history(start=start, end=end + _ONE_DAY),  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {
            "session_date": row.get("Date", row.get("Datetime")),
            "open": row.get("Open"),
            "high": row.get("High"),
            "low": row.get("Low"),
            "close": row.get("Close"),
            "volume": row.get("Volume"),
        }
        for row in _records(frame)
    )


def yahoo_multi_bars(symbols: Sequence[str], start: date, end: date) -> Mapping[str, Records]:
    """One download for many symbols. Columns come back as (field, symbol) pairs even for one."""
    frame: Final = cast(
        "_NestedFrame",
        yf.download(  # pyright: ignore[reportUnknownMemberType]  # no stubs
            list(symbols),
            start=start,
            end=end + _ONE_DAY,
            progress=False,
        ),
    )
    rows: Final = frame.reset_index().to_dict(orient="records")
    return {
        symbol: tuple(
            {
                "session_date": row.get(DATE_KEY),
                "open": row.get(("Open", symbol)),
                "high": row.get(("High", symbol)),
                "low": row.get(("Low", symbol)),
                "close": row.get(("Close", symbol)),
                "volume": row.get(("Volume", symbol)),
            }
            for row in rows
        )
        for symbol in symbols
    }


def yahoo_lookup(query: str, kind: str, count: int) -> Records:
    lookup: Final = yf.Lookup(query)
    frame: Final = cast(
        "_Frame",
        getattr(lookup, f"get_{kind}")(count=count),  # pyright: ignore[reportUnknownMemberType, reportAny]  # no stubs
    )
    return tuple(
        {
            "symbol": row.get("symbol"),
            "name": row.get("shortName"),
            "quote_type": row.get("quoteType"),
            "exchange": row.get("exchange"),
            "industry": row.get("industryName"),
            "price": row.get("regularMarketPrice"),
            "change_percent": row.get("regularMarketPercentChange"),
        }
        for row in _records(frame)
    )


def yahoo_search(query: str, count: int) -> Records:
    quotes: Final = cast(
        "Records",
        yf.Search(query, max_results=count).quotes,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {
            "symbol": row.get("symbol"),
            "name": row.get("longname", row.get("shortname")),
            "quote_type": row.get("quoteType"),
            "exchange": row.get("exchange"),
            "industry": row.get("industry"),
            "sector": row.get("sector"),
        }
        for row in quotes
    )


def yahoo_screen(key: str, count: int) -> Records:
    result: Final = cast(
        "Mapping[str, object]",
        yf.screen(key, count=count),  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    quotes: Final = cast("Records", result.get("quotes") or ())
    return tuple(
        {
            "symbol": row.get("symbol"),
            "name": row.get("shortName", row.get("displayName")),
            "quote_type": row.get("quoteType"),
            "exchange": row.get("fullExchangeName", row.get("exchange")),
            "price": row.get("regularMarketPrice"),
            "change_percent": row.get("regularMarketChangePercent"),
        }
        for row in quotes
    )


def yahoo_info(symbol: str) -> Mapping[str, object]:
    return cast(
        "Mapping[str, object]",
        yf.Ticker(symbol).info,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )


def yahoo_fund_holdings(symbol: str) -> Records:
    frame: Final = cast(
        "_Frame",
        yf.Ticker(symbol).funds_data.top_holdings,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {"symbol": row.get("Symbol"), "name": row.get("Name"), "weight": row.get("Holding Percent")}
        for row in _records(frame)
    )


def yahoo_fund_sector_weights(symbol: str) -> Mapping[str, object]:
    return cast(
        "Mapping[str, object]",
        yf.Ticker(symbol).funds_data.sector_weightings,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )


def market_status_fields(status: Mapping[str, object] | None) -> Mapping[str, object]:
    """The status payload, named. Separate from the call so a test can drive the real shape.

    The zone arrives nested beside its offset, and the bounds arrive as datetimes rather than as
    the clock strings they resemble. yfinance answers `None` for a region its endpoint will not
    serve, and for a parse failure in one it will, so an absent status is an empty session.
    """
    if status is None:
        return {}

    zone: Final = status.get("timezone")
    return {
        "name": status.get("name"),
        "status": status.get("status"),
        "opens_at": status.get("open"),
        "closes_at": status.get("close"),
        "timezone": cast("Mapping[str, object]", zone).get("short") if isinstance(zone, Mapping) else zone,
    }


def yahoo_market_status(region: str) -> Mapping[str, object] | None:
    return cast(
        "Mapping[str, object] | None",
        yf.Market(region).status,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )


def yahoo_earnings_dates(symbol: str) -> Records:
    frame: Final = cast(
        "_Frame",
        yf.Ticker(symbol).earnings_dates,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {
            "event_date": row.get("Earnings Date"),
            "eps_estimate": row.get("EPS Estimate"),
            "reported_eps": row.get("Reported EPS"),
            "surprise_percent": row.get("Surprise(%)"),
        }
        for row in _records(frame)
    )


def yahoo_earnings_estimate(symbol: str) -> Records:
    frame: Final = cast(
        "_Frame",
        yf.Ticker(symbol).earnings_estimate,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {
            "period": row.get("period"),
            "average": row.get("avg"),
            "low": row.get("low"),
            "high": row.get("high"),
            "year_ago_eps": row.get("yearAgoEps"),
            "analysts": row.get("numberOfAnalysts"),
            "growth": row.get("growth"),
        }
        for row in _records(frame)
    )


def yahoo_eps_trend(symbol: str) -> Records:
    frame: Final = cast(
        "_Frame",
        yf.Ticker(symbol).eps_trend,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {
            "period": row.get("period"),
            "current": row.get("current"),
            "days_ago_7": row.get("7daysAgo"),
            "days_ago_30": row.get("30daysAgo"),
            "days_ago_60": row.get("60daysAgo"),
            "days_ago_90": row.get("90daysAgo"),
        }
        for row in _records(frame)
    )


def yahoo_eps_revisions(symbol: str) -> Records:
    """Note `downLast7Days` capitalises the D while the other three do not."""
    frame: Final = cast(
        "_Frame",
        yf.Ticker(symbol).eps_revisions,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {
            "period": row.get("period"),
            "up_last_7_days": row.get("upLast7days"),
            "up_last_30_days": row.get("upLast30days"),
            "down_last_7_days": row.get("downLast7Days"),
            "down_last_30_days": row.get("downLast30days"),
        }
        for row in _records(frame)
    )


def yahoo_price_targets(symbol: str) -> Mapping[str, object]:
    return cast(
        "Mapping[str, object]",
        yf.Ticker(symbol).analyst_price_targets,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )


def yahoo_rating_actions(symbol: str) -> Records:
    frame: Final = cast(
        "_Frame",
        yf.Ticker(symbol).upgrades_downgrades,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {
            "graded_at": row.get("GradeDate"),
            "firm": row.get("Firm"),
            "to_grade": row.get("ToGrade"),
            "from_grade": row.get("FromGrade"),
            "action": row.get("Action"),
        }
        for row in _records(frame)
    )


def yahoo_option_expiries(symbol: str) -> Sequence[str]:
    return cast(
        "Sequence[str]",
        yf.Ticker(symbol).options,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )


def yahoo_option_calls(symbol: str, expiry: str) -> Records:
    frame: Final = cast(
        "_Frame",
        yf.Ticker(symbol).option_chain(expiry).calls,  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {
            "strike": row.get("strike"),
            "last_price": row.get("lastPrice"),
            "implied_volatility": row.get("impliedVolatility"),
            "in_the_money": row.get("inTheMoney"),
        }
        for row in _records(frame)
    )


def _calendar_frame(start: date, end: date, surface: str) -> "_Frame":
    """One calendar surface, re-minting Yahoo's crumb if the cached one has been rejected.

    Yahoo guards the calendar endpoints with a crumb token fetched once and held on a
    process-wide singleton. yfinance reuses it for the life of the process and clears it only
    when login state changes, so a crumb Yahoo later rejects is never replaced: a long-running
    server answers "Invalid Crumb" for every calendar call from the first failure until it is
    restarted, while the price endpoints, which need no crumb, keep working.

    Dropping the cached token and asking once more turns that permanent outage back into the
    transient one it actually is.
    """
    try:
        return cast("_Frame", getattr(yf.Calendars(start, end), surface))  # pyright: ignore[reportAny]  # no stubs
    except Exception as exc:
        if _CRUMB_REJECTED not in str(exc):
            raise
        # The singleton exposes no way to invalidate the token it is holding.
        yf.data.YfData()._crumb = None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        return cast("_Frame", getattr(yf.Calendars(start, end), surface))  # pyright: ignore[reportAny]  # no stubs


def yahoo_earnings_calendar(start: date, end: date) -> Records:
    frame: Final = _calendar_frame(start, end, "earnings_calendar")
    return tuple(
        {
            "symbol": row.get("Symbol"),
            "company": row.get("Company"),
            "event_name": row.get("Event Name"),
            "starts_at": row.get("Event Start Date"),
            "timing": row.get("Timing"),
            "eps_estimate": row.get("EPS Estimate"),
        }
        for row in _records(frame)
    )


def yahoo_economic_calendar(start: date, end: date) -> Records:
    frame: Final = _calendar_frame(start, end, "economic_events_calendar")
    return tuple(
        {
            "event": row.get("Event"),
            "region": row.get("Region"),
            "event_time": row.get("Event Time"),
            "period": row.get("For"),
            "actual": row.get("Actual"),
            "expected": row.get("Expected"),
            "previous": row.get("Last"),
        }
        for row in _records(frame)
    )


def yahoo_ipo_calendar(start: date, end: date) -> Records:
    frame: Final = _calendar_frame(start, end, "ipo_info_calendar")
    return tuple(
        {
            "symbol": row.get("Symbol"),
            "company": row.get("Company"),
            "exchange": row.get("Exchange"),
            "event_date": row.get("Date"),
            "price": row.get("Price"),
            "currency": row.get("Currency"),
        }
        for row in _records(frame)
    )


def yahoo_splits_calendar(start: date, end: date) -> Records:
    frame: Final = _calendar_frame(start, end, "splits_calendar")
    return tuple(
        {
            "symbol": row.get("Symbol"),
            "company": row.get("Company"),
            "payable_on": row.get("Payable On"),
            "old_share_worth": row.get("Old Share Worth"),
            "share_worth": row.get("Share Worth"),
        }
        for row in _records(frame)
    )


def fred_observations(series_id: str, start: date, end: date) -> Records:
    frame: Final = cast(
        "_Frame",
        web.DataReader(series_id, "fred", start, end),  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {"observation_date": row.get("DATE", row.get("index")), "value": row.get(series_id)} for row in _records(frame)
    )
