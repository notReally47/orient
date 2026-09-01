---
name: analysis
description: Establish what happened in a market session and why, before anything is written about it. Use when researching an instrument's session, deciding which measurements and which tools that session needs, or attributing a move to a cause rather than asserting one.
---

You are researching one instrument's session so a summary can be written about it. Nothing has
been fetched for you. Deciding what this instrument needs is the first part of the job.

Each tool says what it returns and when it is worth calling. This says how to sequence them, and
how to read what comes back.

## Work in as few turns as you can

Tool calls in the same turn run at the same time, so issue every call that does not depend on
another one together. A well-run session is four or five turns. Twelve turns of one call each is
a worse answer, not a more thorough one.

The first turn is `get_instrument_profile`, `compute_instrument_signals` and `recall_history`
together: none of them depends on the others. Hold `get_market_context`, `get_calendar` and
`get_earnings_detail` until you have read the guidance below, because that is what tells you
which of them this instrument's session is actually about. `search_news` and
`find_similar_sessions` come after the measurements, and `find_similar_sessions` is worth a second
call once the news has given you a situation worth matching against.

Each tool has a small budget of calls per run. Asking `search_news` six questions at once costs
one call; asking it six times costs six and will be refused before the sixth. Batch the questions
rather than spending the budget on round trips.

## Read the guidance for this asset class

Once the profile tells you the asset class, read `references/{asset_class}.md`, using the asset
class exactly as the profile spelled it: `references/equity.md`, `references/index.md`,
`references/future.md`, `references/currency.md`, `references/crypto.md`, `references/etf.md` or
`references/fund.md`.

That file says what this kind of instrument's session is actually about, which of the remaining
tools are worth a request, and which claims you may not make about it. An index and a currency
pair need different evidence, and the file is where that difference is written down.

## Establish whether the move was its own or the market's

Read `relative` before anything else.

A stock down 3% on a day its sector fell 2.8% has an excess of −0.2% and has not done anything
that needs a company explanation. The same stock down 3% on a day its sector rose 1% has an excess
of −4%, and that is where a news search earns its request. Quote the excess, not the impression.

Say which comparison you made. "Moved with its sector" is a finding, not the absence of one, and
`relative` being absent is also a finding: it means no benchmark applies to this instrument.

## Read the shape of the session, not only its close

The split separates days a single return cannot. A close down 2% that gapped down 2.5% and then rallied
all session is a market absorbing news; the same 2% that opened flat and bled all day is one still
selling. `close_location` near 1.0 means it closed on its high, near 0.0 on its low. A large move
that finished at the wrong end of its range is a move that was faded, and that belongs in the
summary because it is the difference between a level that held and one that is about to go.

`up_down_volume_60d` says which side the quarter's volume was on: above one is more volume on
rising days, below one is more on falling days. `volume_multiple_20d` is a multiple, where 1.0 is
an ordinary day — it is not a percentage change, and 0.87 means a *quieter* session than usual.

## Trend is a direction, not only a distance

`trend.two_hundred_day_slope` is how far the two-hundred day average itself moved over the last
month. A close 8% above a *falling* average is a bounce inside a downtrend; 8% above a rising one
is a trend extending. Never describe distance without direction when the slope is present.

## Then write

When you have what you need, activate the `writing` skill and follow it. You are not finished
when the prose exists; you are finished when `save_summary` accepts it.

Report what you could not explain. An honest gap is more useful than a plausible cause, because a
gap is recorded as an anomaly and a later session can close it. A cause invented to fill the
silence never can.
