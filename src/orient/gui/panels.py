"""What appears beside the prose, chosen by the writer and vetted here.

The writer decides. It has read the measurements, it knows whether the day happened in the gap or
across the session, whether a result is three days out, and who the reader is — and none of that
reaches this module. A layout hard-coded per asset class meant guessing all of it in advance, and
guessing wrong in the ways this file used to enumerate: an eleven-sector board under a Bitcoin
summary, a gold price beside a memory chipmaker, five headline tiles whether or not five figures
were worth leading on.

What stays here is a gate rather than a policy. A panel is rendered when the writer asked for it
*and* the data behind it exists, and dropped silently otherwise. That is what keeps the request a
request: asking for holdings on a single company, or an earnings history on a currency pair, costs
nothing and yields nothing.

The one thing the writer may never do is supply a number. Every renderer reads from the stored
snapshot, so a figure on a chart is a figure something measured. A panel argument carrying data
would be a hole straight through the grounding check, which exists precisely because the prose is
not allowed to invent figures either.
"""

from collections.abc import Mapping, Sequence
from typing import Final

from orient.domain import vocabulary
from orient.domain.models import Signals, Summary

ORDER: Final = vocabulary.PANELS


def available(summary: Summary) -> tuple[str, ...]:
    """Every panel this summary holds the data for, whatever the writer asked for."""
    ready: Final = summary.drawable
    return tuple(name for name in ORDER if name in ready)


def for_section(heading: str, summary: Summary) -> tuple[str, ...]:
    """The panels the writer placed under one heading, minus any with nothing to draw.

    Empty is an ordinary answer. A section whose prose needs no figure should have none, and the
    writer being able to say so is the point of letting it choose.
    """
    ready: Final = set(available(summary))
    placed: Final = [panel.name for panel in summary.layout if panel.section == heading and panel.name in ready]
    return tuple(sorted(dict.fromkeys(placed), key=ORDER.index))


def headline(chosen: Sequence[str], measured: Sequence[str]) -> tuple[str, ...]:
    """Which headline figures to show: the writer's picks, or the standing five when it named none.

    Matched on the measurement's own name, because that is the only name the writer ever sees.
    Matching on the reader-facing label instead meant a writer that asked for `close` and
    `volume_multiple_20d` matched nothing and was shown everything, which is the opposite of what
    it asked for and looks exactly like the feature not working.

    Falling back to every figure the page can draw would print sixteen tiles across a reading
    column, so the fallback is the five that describe any instrument on any day. That is also what
    a summary written before the tiles were choosable keeps showing.
    """
    named: Final = {figure.rsplit(".", 1)[-1].strip().lower() for figure in chosen}
    wanted: Final = [figure for figure in measured if figure.lower() in named]
    if wanted:
        return tuple(wanted)
    return tuple(figure for figure in measured if figure in vocabulary.DEFAULT_TILES)


def meanings(summary: Summary) -> Mapping[str, str]:
    """What each label on this page says when a reader hovers it.

    Keyed by the words on the page, because that is what the writer defines: it explains "trading
    activity", not `volume_multiple_20d`. The standing wording stands in wherever it explained
    nothing.
    """
    standing: Final[dict[str, str]] = {
        term.label: term.meaning for term in (*vocabulary.HEADLINE.values(), *vocabulary.BACKDROP.values())
    }
    return standing | {entry.term.strip(): entry.meaning for entry in summary.glossary}


def headline_quote(snapshot: Signals) -> str:
    """What the leading tile calls the price, which is not "closed at" for everything.

    A currency pair does not close and a cryptocurrency never stops, so calling either a close is
    the kind of small wrongness that costs a reader confidence in the figures beside it.
    """
    match snapshot.asset_class:
        case "currency":
            return "Rate on the day"
        case "crypto":
            return "Last price"
        case _:
            return "Closed at"
