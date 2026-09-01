This is the page your summary is written into. You choose what appears on it, and the reader sees
your words beside measurements the system formats. Nothing here is drawn unless you ask for it.
`references/visuals.md` says which of it to ask for.

## Citing a figure

**Never type a number into the prose. Name the measurement instead.**

```
The close leaves it {{drawdown_from_52_week_high}} below its year high of {{high_52_week}}.
```

reads as

> The close leaves it 25.22% below its year high of 1,254.81

A cited figure is the measurement, so it cannot be mistyped, mis-rounded, or written in the wrong
units. You do not decide how it looks: a rate arrives as a percentage, a price in the currency's
own precision, a multiple with an `x`. Write `{{close}}`, never `938.40`, and never both.

You may cite any measurement `compute_instrument_signals` returned, by its own name. Nested ones
answer to either form, so `{{shape.gap}}` and `{{gap}}` are the same request. Dates, counts and
anything that is not a measurement are typed normally and checked as they always were.

A change is written with its sign. Where your own words already give the direction, add `:plain`
to drop it: `{{above_52_week_low:plain}} above its low` reads "21.51% above its low", not
"+21.51% above its low". Use it after rose, fell, gained, lost, climbed, slipped, up, down, above,
below, ahead of, behind. Keep the sign where the sentence is neutral, as in "a move of
`{{one_day}}`".

`check_summary` tells you if you named something that does not exist. Call it while you write.

## The headline figures

Any of these may go in `tiles`. Naming none falls back to close, year to date, distance from the
year average, realised volatility and volume, which is rarely the right five for a given session.

| name | shown as |
| --- | --- |
| `close` | Closed at |
| `one_day` | On the day |
| `one_week` | Over the week |
| `one_month` | Over the month |
| `three_month` | Over three months |
| `year_to_date` | This year |
| `from_50_day` | Against its ten-week average |
| `from_200_day` | Against its year average |
| `two_hundred_day_slope` | Where the trend is pointing |
| `realised_volatility_20d` | How much it swung |
| `volume_multiple_20d` | Trading activity |
| `drawdown_from_52_week_high` | Below its year high |
| `above_52_week_low` | Above its year low |
| `gap_share_of_move` | How much happened overnight |
| `close_location` | Where it finished |
| `up_down_volume_60d` | Which side the volume was on |

## What the page labels for you

Each panel is named in `layout` with the section heading it sits under, and it arrives carrying
its own labels. A sentence explaining a label the reader is looking at is a sentence spent twice.

The `backdrop` panel labels its own readings: **Expected swings**, **10-year borrowing cost**,
**2-year borrowing cost**, **Ten-year minus two-year**, **Risky-borrower premium**, and where the
instrument warrants them **US dollar**, **Gold** and **Crude oil**.

The price chart labels its own lines: **Close**, **50-day average**, **200-day average**. So a
sentence explaining what a moving average is duplicates a label beside it.

## The glossary

`glossary` is where terms get explained. Every entry appears twice: on the first mention of that
word in the prose, and in a list beneath the summary for a reader who is not hovering anything.

**This is instead of explaining terms in the prose, not as well as.** A summary that stops to
define every figure spends a third of its words on definitions and reads like a textbook. Use the
term, move on, and put the explanation here.

Define the page's own labels here too when this instrument makes one mean something particular:
"trading activity" on a mega-cap and on a thinly traded trust are different facts.
