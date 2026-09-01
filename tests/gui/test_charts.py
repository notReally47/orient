"""The visuals, built from a stored snapshot alone.

Two rules run through these. A missing measurement costs its own panel and nothing else, so a
summary written when a vendor surface was down still opens. And nothing reaches a reader in the
trade's shorthand: a panel labelled `XLK` or `10s2s` is unreadable to the audience the beginner
level exists for, so what gets asserted is the plain wording as much as the numbers.
"""

from datetime import date, timedelta
from typing import Final, cast

from orient.domain import vocabulary
from orient.domain.models import (
    Bar,
    Breadth,
    CalendarEntry,
    CalendarKind,
    CrossAsset,
    EarningsReaction,
    Holding,
    Relative,
    Returns,
    SectorMove,
    SessionShape,
    Signals,
    TrendDistance,
)
from orient.gui import charts

SYMBOL: Final = "^GSPC"
SESSION: Final = date(2026, 8, 13)


def _series_at(option: charts.Option, index: int) -> dict[str, object]:
    """One series out of an option dict, which ECharts defines as untyped JSON."""
    listed: Final = cast("list[dict[str, object]]", option["series"])
    return listed[index]


def _at(option: charts.Option, key: str) -> dict[str, object]:
    return cast("dict[str, object]", option[key])


def _colour(bar: dict[str, object]) -> object:
    return cast("dict[str, object]", bar["itemStyle"])["color"]


def _series(count: int, start: float = 7000.0) -> tuple[tuple[date, float], ...]:
    return tuple((SESSION - timedelta(days=count - index), start + index * 3.5) for index in range(count))


def _sectors() -> tuple[SectorMove, ...]:
    return (
        SectorMove(symbol="XLC", name="Communication Services", change_percent=0.0207),
        SectorMove(symbol="XLRE", name="Real Estate", change_percent=0.0142),
        SectorMove(symbol="XLB", name="Materials", change_percent=-0.0051),
    )


def _signals(**overrides: object) -> Signals:
    base: Final[dict[str, object]] = {
        "symbol": SYMBOL,
        "session_date": SESSION,
        "close": 7798.99,
        "returns": Returns(one_day=0.0065, year_to_date=0.1393),
        "trend": TrendDistance(from_50_day=0.0388, from_200_day=0.1031),
    }
    return Signals.model_validate({**base, **overrides})


def test_a_price_chart_names_its_lines_in_words_rather_than_in_shorthand() -> None:
    option: Final = charts.price(_series(220))

    assert option is not None
    assert [_series_at(option, index)["name"] for index in range(3)] == [
        "Price",
        "50-day average",
        "200-day average",
    ]


def test_a_price_chart_opens_on_the_recent_span_and_can_be_dragged_back() -> None:
    """A year of daily bars is unreadable at full width, and refetching to see more is a wait."""
    option: Final = charts.price(_series(252))

    assert option is not None
    zooms: Final = cast("list[dict[str, object]]", option["dataZoom"])
    assert [zoom["type"] for zoom in zooms] == ["inside", "slider"]
    assert cast("int", zooms[0]["start"]) > 0
    assert zooms[0]["end"] == 100


def test_an_average_is_null_until_its_window_is_full() -> None:
    """A fifty-day line drawn from three days is a wrong number, not a short one."""
    option: Final = charts.price(_series(60))

    assert option is not None
    fifty: Final = cast("list[float | None]", _series_at(option, 1)["data"])
    assert fifty[0] is None
    assert fifty[48] is None
    assert fifty[49] is not None


def test_a_series_too_short_to_plot_draws_nothing() -> None:
    assert charts.price(()) is None
    assert charts.price(_series(1)) is None


def test_sectors_are_named_rather_than_tickered() -> None:
    """`XLC` is the vendor's word for it. Nobody reading a beginner summary knows that word."""
    option: Final = charts.sectors(_sectors())

    assert option is not None
    assert _at(option, "yAxis")["data"] == ["Materials", "Real Estate", "Communication Services"]


def test_sectors_are_ordered_weakest_first_and_coloured_by_direction() -> None:
    option: Final = charts.sectors(_sectors())

    assert option is not None
    bars: Final = cast("list[dict[str, object]]", _series_at(option, 0)["data"])
    assert [bar["value"] for bar in bars] == [-0.51, 1.42, 2.07]
    assert _colour(bars[0]) == charts.DOWN
    assert _colour(bars[-1]) == charts.UP


def test_every_sector_is_drawn_rather_than_the_strongest_few() -> None:
    """Five missing from the middle makes a session look more polarised than it was."""
    whole: Final = tuple(
        SectorMove(symbol=f"XL{letter}", name=f"Sector {letter}", change_percent=index / 1000)
        for index, letter in enumerate("ABCDEFGHIJK")
    )

    option: Final = charts.sectors(whole)

    assert option is not None
    assert len(cast("list[object]", _at(option, "yAxis")["data"])) == len(whole)


def test_a_sector_with_no_measured_move_is_left_out_rather_than_drawn_at_zero() -> None:
    option: Final = charts.sectors((SectorMove(symbol="XLK", name="Technology", change_percent=None),))

    assert option is None


def test_sector_bars_are_absent_when_the_backdrop_was_never_measured() -> None:
    """Summaries stored before the backdrop was kept still have to open."""
    assert charts.sectors(()) is None


def test_how_the_market_split_is_a_sentence_rather_than_a_chart() -> None:
    """Two counts do not need a figure, and the prose says the same thing in the same words."""
    split: Final = charts.rose_and_fell(Breadth.over({"XLC": 0.02, "XLRE": 0.01, "XLB": -0.005}))

    assert split == "2 of 3 sectors rose, 1 fell"


def test_no_split_is_reported_when_nothing_was_counted() -> None:
    assert charts.rose_and_fell(None) is None


def test_the_backdrop_is_grouped_by_the_question_each_part_answers() -> None:
    """Eight identical cards leave the reader to rank them. Three groups answer three questions."""
    groups: Final = charts.conditions(
        CrossAsset(vix=14.63, yield_10y=4.63, yield_2y=4.15, dollar_index=99.96, gold=4363.6)
    )

    assert [group.heading for group in groups] == [
        "How nervous the market was",
        "What it cost to borrow",
        "Everywhere else",
    ]


def test_a_group_states_where_its_reading_sits_rather_than_only_what_it_is() -> None:
    nerves: Final = charts.conditions(CrossAsset(vix=14.63))[0]

    assert "Below twenty is usually called calm" in nerves.note
    assert "14.63" in nerves.note


def test_an_inverted_curve_is_named_as_unusual() -> None:
    """The shape is the point of the pair, and it is a fact about the two numbers beside it."""
    borrowing: Final = charts.conditions(CrossAsset(yield_10y=4.10, yield_2y=4.60))[0]

    assert "inverted" in borrowing.note


def test_backdrop_readings_are_labelled_in_words_and_carry_their_meaning() -> None:
    groups: Final = charts.conditions(CrossAsset(vix=14.63, yield_10y=4.63, yield_2y=4.15))

    labels: Final = [reading.label for group in groups for reading in group.readings]
    assert "Expected swings" in labels
    assert "Ten-year minus two-year" in labels
    assert all(reading.meaning for group in groups for reading in group.readings)


def test_a_reading_explains_the_shorthand_without_leading_with_it() -> None:
    """A reader who knows the term should find it; one who does not should not meet it first."""
    groups: Final = charts.conditions(CrossAsset(yield_10y=4.63, yield_2y=4.15))
    spread: Final = next(r for g in groups for r in g.readings if "Ten-year" in r.label)

    assert "10s2s" in spread.meaning


def test_a_group_with_nothing_measured_is_left_out() -> None:
    groups: Final = charts.conditions(CrossAsset(vix=14.63))

    assert [group.heading for group in groups] == ["How nervous the market was"]


def test_no_backdrop_at_all_is_no_groups() -> None:
    assert charts.conditions(None) == ()


def _event(kind: CalendarKind, label: str, day: int, symbol: str | None = None) -> CalendarEntry:
    return CalendarEntry(kind=kind, label=label, occurs_at=date(2026, 8, day), symbol=symbol)


def test_the_week_ahead_is_grouped_by_day_and_kind() -> None:
    """A raw week runs to forty-odd rows, most of them splits nobody here has heard of."""
    ahead: Final = charts.diary(
        (
            _event("earnings", "NVIDIA Corporation", 26),
            _event("earnings", "HP Inc.", 26),
            _event("split", "Wing's Foot Inc", 28),
        )
    )

    assert [day.when.day for day in ahead] == [26, 28]
    assert [line.kind for day in ahead for line in day.lines] == ["Results", "Share splits"]
    assert ahead[0].lines[0].summary == "NVIDIA Corporation, HP Inc."


def test_two_kinds_on_one_day_share_that_day_rather_than_splitting_it() -> None:
    """A card per day, not a card per kind. The reader is planning a week, not reading a database."""
    ahead: Final = charts.diary((_event("earnings", "NVIDIA Corporation", 26), _event("split", "Wing's Foot", 26)))

    assert len(ahead) == 1
    assert [line.kind for line in ahead[0].lines] == ["Results", "Share splits"]


def test_a_repeated_event_is_listed_once() -> None:
    ahead: Final = charts.diary((_event("earnings", "NVIDIA Corporation", 26),) * 3)

    assert ahead[0].lines[0].summary == "NVIDIA Corporation"


def test_every_name_on_a_day_is_written_out() -> None:
    """A reader scanning for one company cannot find it behind "and 8 more"."""
    ahead: Final = charts.diary(tuple(_event("split", f"Company {n}", 28) for n in range(12)))

    assert len(ahead[0].lines[0].named) == 12
    assert "more" not in ahead[0].lines[0].summary
    assert "Company 11" in ahead[0].lines[0].summary


def test_the_instruments_own_event_survives_the_cut_and_is_marked() -> None:
    """In a week of forty companies this is the one row the reader came for, so it leads the line
    rather than sitting wherever the vendor happened to put it."""
    crowd: Final = tuple(_event("earnings", f"Company {n}", 28) for n in range(12))
    ahead: Final = charts.diary((*crowd, _event("earnings", "Micron Technology", 28, "MU")), "MU")

    line: Final = ahead[0].lines[0]
    assert line.mine
    assert line.named[0] == "Micron Technology"
    assert ahead[0].mine


def test_a_week_with_nothing_of_the_instruments_own_marks_nothing() -> None:
    ahead: Final = charts.diary((_event("earnings", "NVIDIA Corporation", 26, "NVDA"),), "MU")

    assert not ahead[0].mine


def test_a_day_says_how_far_off_it_is_rather_than_leaving_the_reader_to_count() -> None:
    """ "Thu 27 Aug" and "tomorrow" are the same fact, and only one says whether there is time."""
    ahead: Final = charts.diary(
        (_event("earnings", "Today Inc", 26), _event("earnings", "Soon Inc", 27), _event("split", "Later Inc", 30)),
        since=date(2026, 8, 26),
    )

    assert [day.when_said for day in ahead] == ["today", "tomorrow", "in 4 days"]


def test_distance_is_measured_from_the_session_not_from_the_first_thing_scheduled() -> None:
    """A quiet week whose first event is Friday must not report Friday as today."""
    ahead: Final = charts.diary((_event("earnings", "Friday Inc", 28),), since=date(2026, 8, 25))

    assert ahead[0].when_said == "in 3 days"


def test_an_undated_event_is_left_out_rather_than_filed_under_nothing() -> None:
    ahead: Final = charts.diary((CalendarEntry(kind="ipo", label="Unscheduled", occurs_at=None),))

    assert ahead == ()


def test_the_headline_leads_with_the_close_and_the_day() -> None:
    rows: Final = charts.headline(_signals())

    assert (rows[0].label, rows[0].value, rows[0].change) == ("Closed at", "7,798.99", "+0.65%")
    assert all(tile.meaning for tile in rows)


def test_a_currency_pair_is_quoted_rather_than_closed() -> None:
    """A rate does not close, and calling it a close is the kind of small wrongness that erodes
    trust in everything beside it."""
    rows: Final = charts.headline(_signals(), quote="Rate on the day")

    assert rows[0].label == "Rate on the day"


def test_a_price_keeps_the_precision_it_was_stored_with() -> None:
    """Two decimal places would print a currency pair at 1.17 and lose the pips that matter."""
    rows: Final = charts.headline(_signals(close=1.17324))

    assert rows[0].value == "1.17324"


def test_headline_labels_say_what_they_mean_rather_than_naming_a_window() -> None:
    labels: Final = [tile.label for tile in charts.headline(_signals(realised_volatility_20d=0.1397))]

    assert "How much it swung" in labels
    assert not any("20d" in label for label in labels)


def test_a_headline_only_shows_what_was_measured() -> None:
    """Every figure degrades on its own, so a sparse snapshot renders fewer tiles, not blank ones."""
    rows: Final = charts.headline(_signals(returns=Returns(), trend=TrendDistance()))

    assert [tile.label for tile in rows] == ["Closed at"]


def test_ranking_by_contribution_reorders_the_board_against_ranking_by_move() -> None:
    """The sector that travelled furthest is routinely not the one that moved the market.

    Technology falling 1.78% on a 37% weight drags four times as hard as financials rising 1.29%
    on a 12% one, and a reader shown only the two percentages ranks them the other way round.
    """
    weighted: Final = (
        SectorMove(symbol="XLK", name="Technology", change_percent=-0.0178, weight=0.374, contribution=-0.00666),
        SectorMove(symbol="XLF", name="Financials", change_percent=0.0129, weight=0.1224, contribution=0.00158),
        SectorMove(symbol="XLP", name="Consumer Staples", change_percent=0.017, weight=0.0461, contribution=0.00078),
    )

    by_move: Final = charts.sectors(weighted, charts.MOVE)
    by_share: Final = charts.sectors(weighted, charts.CONTRIBUTION)

    assert by_move is not None
    assert by_share is not None
    assert _at(by_move, "yAxis")["data"] == ["Technology", "Financials", "Consumer Staples"]
    assert _at(by_share, "yAxis")["data"] == ["Technology", "Consumer Staples", "Financials"]


def test_a_contribution_keeps_the_decimals_that_stop_it_rounding_to_nothing() -> None:
    """Contributions are fractions of a percentage point; two decimals flattens most of a board."""
    option: Final = charts.sectors(
        (SectorMove(symbol="XLP", name="Consumer Staples", change_percent=0.017, contribution=0.00078),),
        charts.CONTRIBUTION,
    )

    assert option is not None
    bars: Final = cast("list[dict[str, object]]", _series_at(option, 0)["data"])
    assert bars[0]["value"] == 0.078


def test_a_board_with_no_weights_still_draws_by_move() -> None:
    """A vendor that will not serve weights costs the second view, never the first."""
    assert charts.sectors(_sectors(), charts.CONTRIBUTION) is None
    assert charts.sectors(_sectors(), charts.MOVE) is not None


def test_the_sector_board_belongs_only_to_instruments_it_describes() -> None:
    """Eleven US equity sectors under a Bitcoin summary read as Bitcoin's own composition."""
    assert charts.sectors_describe("^GSPC")
    assert charts.sectors_describe("AAPL")
    assert charts.sectors_describe("SPY")
    assert not charts.sectors_describe("BTC-USD")
    assert not charts.sectors_describe("EURUSD=X")
    assert not charts.sectors_describe("GC=F")


def test_a_bar_label_uses_the_placeholder_that_bars_understand() -> None:
    """ECharts substitutes `{c}` on a series label and `{value}` on an axis. Crossing them prints
    the placeholder itself, which is how the sector board came to read "{value}%" beside a bar."""
    option: Final = charts.sectors(_sectors())

    assert option is not None
    label: Final = cast("dict[str, object]", _series_at(option, 0)["label"])
    assert label["formatter"] == "{c}%"
    assert _at(option, "xAxis")["axisLabel"] == {"formatter": "{value}%"}


def test_a_contribution_board_labels_its_bars_in_points_not_percent() -> None:
    weighted: Final = (
        SectorMove(symbol="XLK", name="Technology", change_percent=-0.0178, weight=0.374, contribution=-0.00666),
    )

    option: Final = charts.sectors(weighted, charts.CONTRIBUTION)

    assert option is not None
    label: Final = cast("dict[str, object]", _series_at(option, 0)["label"])
    assert label["formatter"] == "{c}pp"


def test_the_commodity_block_is_dropped_for_an_instrument_it_says_nothing_about() -> None:
    """The price of gold has no bearing on a memory chipmaker's session, and printing it under
    "reading the signals" invites a reader to look for a connection nobody claimed."""
    backdrop: Final = CrossAsset(vix=15.45, yield_10y=4.7, yield_2y=4.24, dollar_index=98.9, gold=4638.1)

    chipmaker: Final = charts.conditions(backdrop, "equity", "Technology")

    assert [group.heading for group in chipmaker] == ["How nervous the market was", "What it cost to borrow"]


def test_the_commodity_block_is_kept_where_it_is_the_story() -> None:
    backdrop: Final = CrossAsset(vix=15.45, crude_oil=82.36, gold=4638.1)

    driller: Final = charts.conditions(backdrop, "equity", "Energy")
    contract: Final = charts.conditions(backdrop, "future", None)

    assert any(group.heading == "Everywhere else" for group in driller)
    assert any(group.heading == "Everywhere else" for group in contract)


def test_an_unknown_class_is_shown_everything_rather_than_nothing() -> None:
    """Summaries written before the class was stored must not lose readings."""
    backdrop: Final = CrossAsset(vix=15.45, gold=4638.1)

    assert any(group.heading == "Everywhere else" for group in charts.conditions(backdrop))


def test_one_company_against_its_sector_and_the_market() -> None:
    option: Final = charts.against(
        Relative(
            benchmark="SPY",
            benchmark_return=0.0032,
            excess_over_benchmark=0.0216,
            peer="XLK",
            peer_name="Technology",
            peer_return=0.0094,
            excess_over_peer=0.0154,
        ),
        "MU",
        0.0248,
    )

    assert option is not None
    assert _at(option, "yAxis")["data"] == ["The market (SPY)", "Technology", "MU"]


def test_how_the_last_results_were_taken_reads_oldest_to_newest() -> None:
    took: Final = charts.reacted(
        (
            EarningsReaction(reported_on=date(2026, 7, 30), next_session_move=-0.0735),
            EarningsReaction(reported_on=date(2026, 4, 30), next_session_move=0.0324),
        )
    )

    assert took is not None
    assert _at(took, "xAxis")["data"] == ["Apr 2026", "Jul 2026"]


def _ohlc(count: int) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            session_date=SESSION - timedelta(days=count - index),
            open=100.0 + index,
            high=102.0 + index,
            low=99.0 + index,
            close=101.0 + index,
            volume=1_000,
        )
        for index in range(count)
    )


def test_a_candle_carries_the_four_numbers_echarts_expects_in_the_order_it_expects() -> None:
    """ECharts reads a candle as open, close, low, high. Any other order draws a plausible chart
    of the wrong sessions, which is worse than drawing nothing."""
    option: Final = charts.candles(_ohlc(80))

    assert option is not None
    first: Final = cast("list[list[float]]", _series_at(option, 0)["data"])[0]
    assert first == [100.0, 101.0, 99.0, 102.0]


def test_a_candle_chart_opens_on_the_recent_span_and_can_be_dragged_back() -> None:
    option: Final = charts.candles(_ohlc(252))

    assert option is not None
    zooms: Final = cast("list[dict[str, object]]", option["dataZoom"])
    assert [zoom["type"] for zoom in zooms] == ["inside", "slider"]
    assert cast("int", zooms[0]["start"]) > 0


def test_a_history_too_short_to_plot_draws_no_candles() -> None:
    assert charts.candles(()) is None
    assert charts.candles(_ohlc(1)) is None


def test_a_tile_is_named_for_the_measurement_the_writer_saw_not_the_words_a_reader_reads() -> None:
    """The writer picks tiles out of the signals it was handed. Keying them on the reader-facing
    wording meant a request for `close` and `volume_multiple_20d` matched nothing and silently
    fell back to showing all five."""
    figures: Final = [tile.figure for tile in charts.headline(_signals(realised_volatility_20d=0.1397))]

    assert figures[0] == "close"
    assert set(figures) <= set(vocabulary.HEADLINE_FIGURES)


def test_a_multiple_and_a_ratio_are_not_written_as_percentages() -> None:
    """0.53 written as "53%" reads as a move of that size, which is the one misreading that turns
    a quiet session into a violent one. Formatted through `figures`, the same path the prose takes,
    so a tile and the sentence under it cannot disagree."""
    tiles: Final = {
        tile.figure: tile.value
        for tile in charts.headline(
            _signals(
                volume_multiple_20d=0.53,
                realised_volatility_20d=0.9584,
                shape=SessionShape(gap=0.0204, intraday=0.0043, close_location=0.5489, gap_share_of_move=0.82),
            )
        )
    }

    assert tiles["volume_multiple_20d"] == "0.53x"
    assert tiles["realised_volatility_20d"] == "95.84%"
    assert tiles["gap_share_of_move"] == "0.82"
    assert tiles["close_location"] == "55%"


def test_the_days_move_leads_the_close_rather_than_taking_a_tile_of_its_own() -> None:
    """Both on the page would print the same figure twice, side by side."""
    tiles: Final = charts.headline(_signals())

    assert tiles[0].change == "+0.65%"
    assert "one_day" not in {tile.figure for tile in tiles}


def test_the_largest_holdings_are_drawn_largest_first() -> None:
    option: Final = charts.holdings(
        (
            Holding(symbol="AAPL", name="Apple", weight=0.07),
            Holding(symbol="NVDA", name="NVIDIA", weight=0.08),
            Holding(symbol="NOPE", name="Unweighted"),
        )
    )

    assert option is not None
    assert cast("list[str]", _at(option, "yAxis")["data"])[-1] == "NVIDIA"


def test_a_fund_whose_weights_nobody_published_draws_no_holdings() -> None:
    assert charts.holdings((Holding(symbol="NVDA", name="NVIDIA"),)) is None
    assert charts.holdings(()) is None
