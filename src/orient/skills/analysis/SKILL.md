---
name: analysis
description: Establish what happened in a market session and why, before anything is written about it. Use when researching an instrument's session, deciding which measurements a question needs, or attributing a move to a cause.
---

You are researching one instrument's session so a summary can be written about it. Nothing has
been fetched for you. Deciding what this instrument needs is the first part of the job.

## Work in as few turns as you can

Tool calls in the same turn run at the same time, so issue every call that does not depend on
another one together. Calls that do depend on something have to wait for it.

What depends on what:

- `get_instrument_profile` depends on nothing. Call it first.
- `references/{asset_class}.md` depends on the profile, because the profile is what tells you the
  asset class.
- `compute_instrument_signals` and `recall_history` depend on nothing. Call them alongside the
  profile in your first turn.
- `get_market_context`, `get_calendar`, `get_earnings_detail` and `get_price_history` depend on
  the guidance you are about to read, so hold them until you have it.
- `search_news` depends on the measurements, because you cannot ask a good question until you
  know what needs explaining.

A well-run session is four or five turns. Twelve turns of one call each is a worse answer, not a
more thorough one.

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

Never attribute a cause before you know whether the instrument moved on its own. Compare it
against whatever backdrop the asset class file told you to fetch. A stock down 3% on a day its
sector fell 2.8% has not done anything that needs a company explanation. A stock down 3% on a day
its sector rose has, and that is where a news search earns its request.

Say which comparison you made. "Moved with its sector" is a finding, not the absence of one.

## Ask the news everything at once

`search_news` takes a list of questions and answers all of them in one round trip, so six
questions cost what one costs. Being sparing with it is how a summary ends up asserting a cause
nobody checked.

Ask about anything the measurements raise but cannot explain: why the leading sector led, what
the day's economic release actually said, whether a move that looks large for this instrument was
part of something wider. Ask full questions with the date in them. "Why did semiconductor stocks
fall on 13 August 2026" beats "NVDA".

What comes back is somebody's claim about the market. Attribute it that way, and never quote a
figure out of it: the numbers you may use are the ones the other tools measured, and the grounding
check will reject anything else.

## Then write

When you have what you need, activate the `writing` skill and follow it. You are not finished
when the prose exists; you are finished when `save_summary` accepts it.

## Report what you could not explain

An honest gap is more useful than a plausible cause, because a gap is recorded as an anomaly and
a later session can close it. A cause invented to fill the silence never can.
