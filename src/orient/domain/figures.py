"""Measurements addressed by name, so prose cites a figure instead of transcribing one.

`{{drawdown_from_52_week_high}}` resolves to the measurement, formatted here and nowhere else. A
cited figure cannot drift from what was measured, so the writer never decides precision, units or
sign, and the checks have nothing to catch.
"""

import re
from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType
from typing import Annotated, Final, NamedTuple, cast, get_args, get_origin

from pydantic.fields import FieldInfo

from orient.domain.models import LEVEL, LEVEL_PLACES, RATE, SHARE, Frozen, Signals
from orient.domain.vocabulary import Shown

REFERENCE: Final = re.compile(r"\{\{\s*([a-z0-9_.]+)\s*(?::\s*(plain))?\s*\}\}", re.IGNORECASE)


_RATIOS: Final = frozenset({"up_down_volume_60d", "gap_share_of_move"})
_SHARES: Final = frozenset({"close_location"})
_YIELDS: Final = frozenset({"yield_10y", "yield_2y", "spread_10s2s", "high_yield_spread"})
_MULTIPLES: Final = frozenset({"volume_multiple_20d"})
_UNSIGNED: Final = frozenset({"realised_volatility_20d", "drawdown_from_52_week_high", "range_percent"})


class Figure(NamedTuple):
    value: float
    shown: Shown
    places: int = LEVEL_PLACES


def _units(annotation: object) -> frozenset[str]:
    """The unit tags on a type. Recursive because pydantic cannot hoist metadata out of a union,
    and almost every measurement here is optional."""
    args: Final = cast("tuple[object, ...]", get_args(annotation))
    if get_origin(annotation) is Annotated:
        return frozenset(arg for arg in args[1:] if isinstance(arg, str))
    return frozenset(unit for arg in args for unit in _units(arg))


_BY_NAME: Final[Mapping[str, Shown]] = MappingProxyType(
    {
        **dict.fromkeys(_RATIOS, "ratio"),
        **dict.fromkeys(_SHARES, "share"),
        **dict.fromkeys(_YIELDS, "yield"),
        **dict.fromkeys(_MULTIPLES, "multiple"),
        **dict.fromkeys(_UNSIGNED, "percent"),
    }
)


def _kind(name: str, field: FieldInfo) -> Shown:
    """The unit a figure is written in, from its name where its type cannot say."""
    named: Final = _BY_NAME.get(name)
    if named is not None:
        return named
    tagged: Final = cast("tuple[object, ...]", tuple(field.metadata))
    units: Final = _units(field.annotation) | frozenset(m for m in tagged if isinstance(m, str))
    if LEVEL in units:
        return "level"
    return "change" if units & {RATE, SHARE} else "plain"


def _walk(model: Frozen, prefix: str = "") -> Iterator[tuple[str, Figure]]:
    for name, field in type(model).model_fields.items():
        value = cast("object", getattr(model, name))
        path = f"{prefix}{name}"
        if isinstance(value, Frozen):
            yield from _walk(value, f"{path}.")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            yield path, Figure(float(value), _kind(name, field))


def _quoted_to(close: float) -> int:
    """How finely this instrument is priced, read off its close.

    Magnitude cannot answer this: a currency pair at 1.17324 and a fifty-dollar stock sit in the
    same band and want five decimals and two. Every other price of the instrument follows the
    close, which is the one figure the vendor quotes without float noise.
    """
    written_out: Final = f"{close:f}".rstrip("0")
    return max(LEVEL_PLACES, len(written_out.partition(".")[2]))


def addressable(signals: Signals) -> Mapping[str, Figure]:
    """Every measurement in this session, by the name the writer knows it by. Nested figures
    answer to both their path and their bare field name."""
    places: Final = _quoted_to(signals.close)
    walked: Final = {
        path: figure._replace(places=places) if figure.shown == "level" and "." not in path else figure
        for path, figure in _walk(signals)
    }
    bare: Final = {path.rsplit(".", 1)[-1]: figure for path, figure in walked.items()}
    return {**bare, **walked}


_WRITTEN: Final[Mapping[Shown, Callable[[Figure], str]]] = MappingProxyType(
    {
        "level": lambda f: f"{f.value:,.{f.places}f}",
        "yield": lambda f: f"{f.value:,.2f}%",
        "change": lambda f: f"{f.value:+.2%}",
        "percent": lambda f: f"{abs(f.value):.2%}",
        "share": lambda f: f"{f.value:.0%}",
        "multiple": lambda f: f"{f.value:.2f}x",
        "ratio": lambda f: f"{f.value:.2f}",
        "plain": lambda f: f"{f.value:,.2f}",
    }
)


def written(figure: Figure) -> str:
    return _WRITTEN[figure.shown](figure)


def named(prose: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(found.group(1) for found in REFERENCE.finditer(prose)))


def unknown(prose: str, figures: Mapping[str, Figure]) -> tuple[str, ...]:
    return tuple(name for name in named(prose) if name not in figures)


def render(prose: str, figures: Mapping[str, Figure]) -> str:
    """The prose as a reader meets it. An unresolved name is left as written, so a summary stored
    against measurements that have since changed still reads."""

    def resolve(found: re.Match[str]) -> str:
        name: Final = found.group(1)
        if name not in figures:
            return found.group(0)
        figure: Final = figures[name]
        return written(figure._replace(shown="percent") if found.group(2) and figure.shown == "change" else figure)

    return REFERENCE.sub(resolve, prose)
