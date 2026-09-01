"""Model invariants that a persisted snapshot depends on."""

from datetime import date
from typing import Final
from uuid import uuid4

import pytest
from pydantic import ValidationError

from orient.domain.models import (
    SIGNALS_VERSION,
    Claim,
    ClaimKind,
    CrossAsset,
    Returns,
    SectorMove,
    Signals,
    TrendDistance,
)


def test_the_curve_spread_is_derived_from_the_two_yields() -> None:
    assert CrossAsset(yield_10y=4.25, yield_2y=3.75).spread_10s2s == pytest.approx(0.5)


@pytest.mark.parametrize("cross", [CrossAsset(yield_10y=4.25), CrossAsset(yield_2y=3.75), CrossAsset()])
def test_the_curve_spread_is_none_unless_both_yields_are_present(cross: CrossAsset) -> None:
    assert cross.spread_10s2s is None


def test_the_curve_spread_survives_serialisation() -> None:
    """Signals are stored as jsonb and re-read months later, so a derived field must be written out."""
    assert CrossAsset(yield_10y=4.25, yield_2y=3.75).model_dump()["spread_10s2s"] == pytest.approx(0.5)


def test_a_supplied_spread_cannot_disagree_with_the_yields() -> None:
    """Derived on the way in, so a caller passing a stale figure gets the right one back."""
    assert CrossAsset(yield_10y=4.25, yield_2y=3.75, spread_10s2s=99.0).spread_10s2s == pytest.approx(0.5)


def test_a_snapshot_carrying_cross_asset_data_can_be_read_back() -> None:
    """A stored summary that cannot be re-validated is worse than one never stored: it fails on the
    read, long after the run that produced it, with the data already committed.
    """
    signals: Final = Signals(
        symbol="^GSPC",
        session_date=date(2026, 8, 12),
        close=6000.0,
        returns=Returns(),
        trend=TrendDistance(),
        cross_asset=CrossAsset(yield_10y=4.25, yield_2y=3.75),
    )
    restored: Final = Signals.model_validate(signals.model_dump(mode="json"))
    assert restored == signals


def test_a_signals_snapshot_cannot_be_mutated_after_the_fact() -> None:
    signals: Final = Signals(
        symbol="^GSPC",
        session_date=date(2026, 8, 12),
        close=100.0,
        returns=Returns(),
        trend=TrendDistance(),
    )
    with pytest.raises(ValidationError):
        signals.close = 200.0  # pyright: ignore[reportAttributeAccessIssue]  # the point of the test


def test_an_unknown_field_is_rejected_rather_than_silently_kept() -> None:
    with pytest.raises(ValidationError):
        _ = TrendDistance(from_20_day=0.1)  # pyright: ignore[reportCallIssue]  # the point of the test


def _claim(kind: ClaimKind, target_date: date | None) -> Claim:
    return Claim(
        id=uuid4(),
        summary_id=uuid4(),
        subject_symbol="^GSPC",
        session_date=date(2026, 8, 12),
        kind=kind,
        statement="Volatility should compress into the print.",
        target_date=target_date,
    )


def test_an_expectation_without_a_target_date_is_rejected() -> None:
    """Mirrors the table CHECK, so an unresolvable expectation fails before it reaches Postgres."""
    with pytest.raises(ValidationError, match="target_date"):
        _ = _claim("expectation", None)


@pytest.mark.parametrize("kind", ["attribution", "anomaly"])
def test_other_claim_kinds_need_no_target_date(kind: ClaimKind) -> None:
    assert _claim(kind, None).target_date is None


def test_a_derived_rate_is_rounded_to_two_decimals_of_a_percentage() -> None:
    """A sixteen digit float is four digits of fact and twelve of arithmetic noise, and the
    writer copies whatever it is handed straight into the prose."""
    returns: Final = Returns(one_day=0.0065161301380911585, year_to_date=0.13928715716529116)

    assert returns.one_day == 0.0065
    assert returns.year_to_date == 0.1393


def test_a_level_is_rounded_the_way_a_venue_quotes_it() -> None:
    signals: Final = Signals(
        symbol="^GSPC",
        session_date=date(2026, 8, 13),
        close=7798.990234375,
        returns=Returns(),
        trend=TrendDistance(),
    )

    assert signals.close == 7798.99


def test_the_curve_spread_is_rounded_rather_than_carrying_float_error() -> None:
    """4.63 minus 4.15 is 0.48, and 0.47999999999999954 is the same number spelled unusably."""
    assert CrossAsset(yield_10y=4.63, yield_2y=4.15).spread_10s2s == 0.48


@pytest.mark.parametrize(
    ("quoted", "stored"),
    [
        (7798.9912, 7798.99),
        (78335.1867, 78335.19),
        (1.173241, 1.17324),
        (0.000034219, 0.0000342190),
        (23.456789, 23.4568),
        (0.0, 0.0),
        (-1.173241, -1.17324),
    ],
)
def test_a_level_is_kept_to_the_precision_its_own_size_is_quoted_to(quoted: float, stored: float) -> None:
    """Two decimal places suits an index and destroys a currency pair. A pair at 1.17324 stored as
    1.17 leaves the writer unable to quote the rate it was handed, and the grounding check unable
    to recognise the true one."""
    signals: Final = Signals(
        symbol="X", session_date=date(2026, 8, 21), close=quoted, returns=Returns(), trend=TrendDistance()
    )

    assert signals.close == stored


def test_a_snapshot_carries_every_sector_rather_than_the_strongest_few() -> None:
    """Five sectors missing from the middle makes a session look more polarised than it was, and
    leaves the chart unable to corroborate prose that counts how many rose."""
    signals: Final = Signals(
        symbol="^GSPC",
        session_date=date(2026, 8, 21),
        close=7798.99,
        returns=Returns(),
        trend=TrendDistance(),
        sectors=(
            SectorMove(symbol="XLK", name="Technology", change_percent=0.0101),
            SectorMove(symbol="XLB", name="Materials", change_percent=-0.0051),
        ),
    )

    assert [sector.name for sector in signals.sectors] == ["Technology", "Materials"]
    assert Signals.model_validate_json(signals.model_dump_json()).sectors == signals.sectors


def test_a_snapshot_written_under_an_earlier_version_still_reads_back() -> None:
    """Revisiting is the whole point of storing a summary, so a rename here cannot break it.

    `volume_vs_20_day` became `volume_multiple_20d` when it turned out the name did not say the
    figure was a multiple and not a change. Every row already on file still spells it the old way.
    """
    stored: Final = {
        "symbol": "^GSPC",
        "session_date": "2026-08-24",
        "close": 7652.86,
        "returns": {"one_day": -0.0028},
        "trend": {"from_50_day": 0.0141},
        "volume_vs_20_day": 0.8752,
        "version": "1",
    }

    signals: Final = Signals.model_validate(stored)

    assert signals.volume_multiple_20d == 0.8752
    assert signals.version == "1"


def test_a_field_an_older_snapshot_carried_and_nothing_replaced_is_dropped() -> None:
    """A measurement that has since been removed must not cost the reader the whole summary."""
    signals: Final = Signals.model_validate(
        {
            "symbol": "^GSPC",
            "session_date": "2026-08-24",
            "close": 7652.86,
            "returns": {},
            "trend": {},
            "some_measurement_we_no_longer_take": 3.4,
            "version": "1",
        }
    )

    assert signals.close == 7652.86


def test_a_snapshot_claiming_the_current_version_is_still_validated_strictly() -> None:
    """The leniency is for rows this code wrote before a rename, never for live vendor data."""
    with pytest.raises(ValidationError):
        _ = Signals.model_validate(
            {
                "symbol": "^GSPC",
                "session_date": "2026-08-24",
                "close": 7652.86,
                "returns": {},
                "trend": {},
                "volume_vs_20_day": 0.8752,
                "version": SIGNALS_VERSION,
            }
        )
