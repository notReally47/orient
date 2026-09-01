"""The gate between what the writer asked to draw and what there is data to draw.

The writer decides what appears. These do not test that judgement — it is a judgement, and it
belongs to a model with the session in front of it. What they test is the contract around it: a
request is honoured only when the measurement behind it exists, an impossible request costs
nothing, and the same summary renders the same way every time it is reopened.
"""

import ast
from datetime import date
from pathlib import Path
from typing import Final
from uuid import UUID

from orient.domain import vocabulary
from orient.domain.models import (
    AssetClass,
    CalendarEntry,
    CrossAsset,
    EarningsReaction,
    Holding,
    Panel,
    Relative,
    Returns,
    Section,
    SectorMove,
    SessionShape,
    Signals,
    Summary,
    Term,
    TrendDistance,
)
from orient.gui import panels

SESSION: Final = date(2026, 8, 24)
MOVED: Final = "What moved, and why"


def _summary(  # noqa: PLR0913  # one optional field per measurement a panel can gate on
    symbol: str = "MU",
    asset_class: AssetClass = "equity",
    *,
    layout: tuple[Panel, ...] = (),
    tiles: tuple[str, ...] = (),
    holdings: tuple[Holding, ...] = (),
    reactions: tuple[EarningsReaction, ...] = (),
    calendar: tuple[CalendarEntry, ...] = (),
    glossary: tuple[Term, ...] = (),
    sectors: tuple[SectorMove, ...] = (),
    relative: Relative | None = None,
    shape: SessionShape | None = None,
    cross_asset: CrossAsset | None = None,
) -> Summary:
    return Summary(
        id=UUID(int=1),
        symbol=symbol,
        session_date=SESSION,
        level="beginner",
        status="ok",
        thesis="It moved",
        sections=(Section(heading=MOVED, body="It moved."),),
        layout=layout,
        tiles=tiles,
        holdings=holdings,
        reactions=reactions,
        calendar=calendar,
        glossary=glossary,
        signals_snapshot=Signals(
            symbol=symbol,
            asset_class=asset_class,
            currency="USD",
            session_date=SESSION,
            close=100.0,
            returns=Returns(one_day=0.02),
            trend=TrendDistance(),
            sectors=sectors,
            relative=relative,
            shape=shape,
            cross_asset=cross_asset,
        ),
    )


def _at(name: str, section: str = MOVED) -> Panel:
    return Panel(name=name, section=section)


def _compared() -> Relative:
    return Relative(benchmark="SPY", benchmark_return=0.01, excess_over_benchmark=0.01)


def test_nothing_is_drawn_that_the_writer_did_not_ask_for() -> None:
    """The old page drew every panel it had data for, which is how a Bitcoin summary came to carry
    a chart of eleven US equity sectors."""
    rich: Final = _summary(
        sectors=(SectorMove(symbol="XLK", name="Technology", change_percent=0.01),),
        relative=_compared(),
        cross_asset=CrossAsset(vix=15.0),
    )

    assert panels.for_section(MOVED, rich) == ()


def test_a_requested_panel_is_drawn_when_the_measurement_behind_it_exists() -> None:
    company: Final = _summary(layout=(_at("against"),), relative=_compared())

    assert panels.for_section(MOVED, company) == ("against",)


def test_a_request_for_something_never_measured_is_dropped_rather_than_refused() -> None:
    """Asking is cheap, and being wrong about it should cost the reader nothing."""
    pair: Final = _summary("EURUSD=X", "currency", layout=(_at("reactions"), _at("holdings")))

    assert panels.for_section(MOVED, pair) == ()


def test_a_panel_placed_under_one_heading_does_not_appear_under_another() -> None:
    company: Final = _summary(
        layout=(_at("shape", "Reading the signals"),),
        shape=SessionShape(gap=0.02, intraday=0.004),
    )

    assert panels.for_section(MOVED, company) == ()
    assert panels.for_section("Reading the signals", company) == ("shape",)


def test_two_figures_under_one_heading_are_ordered_the_same_way_every_time() -> None:
    """A layout is stored and reopened, so the page must not shuffle between renders."""
    company: Final = _summary(
        layout=(_at("shape"), _at("against"), _at("price")),
        relative=_compared(),
        shape=SessionShape(gap=0.02, intraday=0.004),
    )

    assert panels.for_section(MOVED, company) == ("price", "against", "shape")


def test_asking_for_the_same_figure_twice_draws_it_once() -> None:
    assert panels.for_section(MOVED, _summary(layout=(_at("price"), _at("price")))) == ("price",)


def test_what_is_available_is_a_fact_about_the_data_not_about_the_request() -> None:
    stocked: Final = _summary(
        holdings=(Holding(symbol="NVDA", weight=0.07),),
        reactions=(EarningsReaction(reported_on=SESSION, next_session_move=-0.07),),
        cross_asset=CrossAsset(vix=15.0),
    )

    assert set(panels.available(_summary())) == {"price", "candles"}
    assert {"holdings", "reactions", "backdrop"} <= set(panels.available(stocked))


def test_the_headline_shows_what_the_writer_led_with() -> None:
    measured: Final = ("close", "year_to_date", "realised_volatility_20d")

    assert panels.headline(("year_to_date",), measured) == ("year_to_date",)


def test_a_figure_named_inside_the_group_it_was_read_from_is_the_same_request() -> None:
    """`returns.year_to_date` is how the measurement appears in the tool result, and asking for it
    by the path it was read at is not a different ask from naming the field."""
    assert panels.headline(("returns.year_to_date",), ("close", "year_to_date")) == ("year_to_date",)


def test_naming_no_headline_figures_falls_back_to_the_standing_few() -> None:
    """Not to everything. The menu is long so a session can be led with what it turned on, and a
    page showing all sixteen has made that choice meaningless."""
    measured: Final = ("close", "one_week", "year_to_date", "close_location")

    assert panels.headline((), measured) == ("close", "year_to_date")


def test_a_headline_figure_that_was_never_measured_is_not_invented() -> None:
    assert panels.headline(("gap_share_of_move",), ("close",)) == ("close",)


def test_the_writers_wording_replaces_the_standing_wording_only_where_it_wrote_any() -> None:
    """Keyed by the words on the page. The writer explains "trading activity", which is what the
    reader is looking at, not `volume_multiple_20d`, which they never see."""
    written: Final = _summary(
        glossary=(Term(term="Trading activity", meaning="Quiet for a name this heavily traded."),)
    )

    said: Final = panels.meanings(written)

    assert said["Trading activity"] == "Quiet for a name this heavily traded."
    assert said["Closed at"] == vocabulary.HEADLINE["close"].meaning
    assert said["Expected swings"] == vocabulary.BACKDROP["vix"].meaning


def test_the_gate_knows_about_every_panel_the_writer_may_ask_for() -> None:
    """`drawable` decides whether a requested panel has data behind it. A name the writer can put
    in `layout` and this map has never heard of is a panel that is silently never drawn."""
    assert set(_summary().drawable) <= set(vocabulary.PANELS)
    assert set(panels.ORDER) == set(vocabulary.PANELS)


def test_every_panel_the_writer_may_ask_for_has_a_branch_that_draws_it() -> None:
    """The tool accepts the name and the gate reports it drawable, and then nothing renders it.
    Read off the dispatch itself rather than a second list, which would only drift in step."""
    tree: Final = ast.parse(Path("src/orient/gui/flow/summary.py").read_text(encoding="utf-8"))
    dispatch: Final = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_visual"
    )
    statement: Final = next(node for node in dispatch.body if isinstance(node, ast.Match))
    handled: Final = {
        case.pattern.value.value
        for case in statement.cases
        if isinstance(case.pattern, ast.MatchValue) and isinstance(case.pattern.value, ast.Constant)
    }

    assert handled == set(vocabulary.PANELS)
