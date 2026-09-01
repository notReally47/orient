---
name: writing
description: Write the summary itself - its structure, what a brokerage may not say, and how a figure is cited rather than typed. Use when turning researched measurements into prose, choosing what the page shows beside it, or fixing a draft that check_summary or save_summary turned back.
---

Write markdown, and nothing but the summary. No preamble, no note about what you did, no closing
offer to explain further.

## What you may not say

**No advice.** Do not tell the reader what to do. No buy, sell, hold, add, trim, avoid or wait. No
"worth considering", no "attractive at this level", no "investors should". Describing what
happened is the job; deciding what to do with it is the reader's.

**No forecasting.** Do not predict a price, a level, a direction or an outcome. Naming a scheduled
event is fine and is the point of the last section: "CPI is released on Thursday" is a fact. "CPI
on Thursday should push yields higher" is a forecast. "If CPI comes in above expectations" is a
forecast wearing a conditional. Describing what the market currently expects is allowed when a
figure measured it, for example an implied move from options, as long as it is stated as an
expectation rather than an outcome.

**No allegations.** Do not suggest that anyone acted improperly. A recovery after a sharp fall may
be described through what was measured, such as volume against average, and it may be left
unexplained. It may not be attributed to anyone's knowledge, intent or conduct.

The line to hold: report what the data shows, name the gap where an earlier explanation did not
hold, and never speculate about motive.

## Structure

```
# <the thesis: one plain claim about the session>
## The big picture
## What moved, and why
## Reading the signals
## What to watch this week
```

The thesis is a claim a reader could disagree with, not a label. "The S&P 500 gave back Monday's
gain on a narrow tape" is a thesis. "Market summary for 13 August" is not.

Write it as a sentence, not a headline: ordinary capitalisation, no Title Case On Every Word. It
sits above the summary in the reader's own typeface and a capitalised headline there reads as a
press release rather than as something written for them.

**The instrument leads.** "The big picture" opens with what this instrument did — its close, its
move, where that sits against its own history — and reaches the backdrop afterwards, as the thing
the move happened against. A summary of Bitcoin that opens with three sentences of US inflation
and equity sector breadth has answered a question nobody asked, and the reader has to hunt for
the one they did ask. This is easy to get wrong when the instrument is not an index, because for
an index the backdrop and the instrument are nearly the same thing and for everything else they
are not.

Each section answers its own question. "What moved, and why" must give causes, not just name the
movers. A section whose data is missing may be left out entirely, but never left hollow.

## Paragraphs

**No paragraph runs past four sentences, and no section is a single block.** Break at the point
the subject changes: the instrument's own history is one paragraph, what the rest of the market
was doing is another, what it costs to borrow is a third.

This matters more than it sounds. One live summary put realised volatility, the drawdown, the
distance off the year's low, two Treasury yields, the policy rate and inflation into one
two-hundred-word paragraph. Every figure in it was correct and none of them was findable. A reader
scanning for one number gives up at a wall of text, and a reader who gives up has been told
nothing at all.

## Figures

**Cite a measurement, never type one.** `references/page.md` has the whole rule: how a reference
is written, which names resolve, and when to drop a sign with `:plain`. Read it before you write a
figure.

Anything you type by hand still has to be a figure something measured, and a number from a news
article was measured by nobody. Dates and counts are typed normally.

`shape.close_location` is a position inside the day's range, not a change. Say it whenever a move
finished at the opposite end of the range from its direction, because a rise that closed on its
low was faded and that is the most useful sentence in the section.

An excess return in `relative` is one return minus another. Say percentage points, not percent.

A drawdown of zero means the instrument closed at its highest point of the past year. Write that,
not the zero.

**Do not write a name that contains a number unless that name was handed to you.** "S&P 500" in a
summary about Apple puts a 500 into the prose that nothing measured. The benchmark you were given
is named in `relative.benchmark`.

Say sector when you describe breadth or contribution: "advancers led decliners" about an index
implies a count of its members that nobody made.

## The evidence that cuts the other way

A thesis is a claim, and a summary that reports only the measurements agreeing with it is an
argument rather than a briefing. Before you finish, go back through what was measured and name
whatever disagrees with what you have written. A reader deciding anything needs the case against
as much as the case for, and they cannot ask you for it later.

Three measurements contradict a headline move most often, and all three are easy to leave out
because the move itself is the story:

- **Where the move happened.** A stock up 2.5% that gapped up 2.0% and then added 0.4% did not
  spend the session being bought — it reopened at a new price and sat there.

  **When `gap_share_of_move` is 0.6 or more, or below 0, saying where the move happened is not
  optional and `save_summary` will refuse the summary without it.** At 0.6 and above the move was
  effectively over at the opening bell; below zero the price gapped one way and traded back the
  other, which is a different day again. "It rose 2.5%" and "it gapped and went nowhere" lead a
  reader to opposite conclusions and only one of them is what happened.
- **The two trends disagreeing.** A close above the two-hundred day average and below the fifty
  day one is a long uptrend with a short-term crack in it. Neither figure says that alone.
- **Which side the volume was on.** `up_down_volume_60d` below one means the quarter's volume has
  leaned to falling days, whatever today did.

None of these makes a move less real. Reporting them is what separates a summary a reader can act
on from one that only tells them what they already hoped.

## Explaining terms

**The prose does not stop to explain anything. The glossary does.** Use a term and keep going, and
put what it means in `glossary`. `references/page.md` says where the reader meets it and what a
definition may contain.

> Volume came in at {{volume_multiple_20d}} its twenty-day average, roughly half of normal.

not

> Volume came in at {{volume_multiple_20d}} its twenty-day average. A volume multiple measures how
> many shares were traded compared to a typical day over the previous month, where 1.00 represents
> average activity.

Both say the same thing. The first leaves room to say something else.

Be generous with the glossary and mean with the prose. Every piece of shorthand a reader at this
level might not know belongs there: the terms you used, and the labels on the panels you chose
where this instrument makes one mean something particular.

## Causes

Say what the data shows. Where an earlier summary's explanation did not hold, say so plainly and
say what is now unexplained. Never speculate about why anyone acted.

## Ending

The last section is what to watch, and it comes from the calendar and from open expectations, not
from a view about where the price is going.

Name only events the calendar returned. An article may mention something scheduled, and a
plausible event on a date the calendar left empty is the easiest thing here to invent. The date
gives it away: "on Sunday 16 August" when nothing in the calendar falls on the 16th quotes a
figure nothing measured.

Quote the month each macro figure describes: "core inflation was 2.79% in July" is a fact, while
"inflation is 2.79%" claims a measurement taken on the session and none was.

## Before you start

Read the guide for the reading level you were asked for, exactly one of `references/beginner.md`,
`references/intermediate.md` or `references/advanced.md`.

Read `references/page.md`. It says how to cite a measurement rather than typing one, and what the
page can show. Read `references/visuals.md` for how to decide which of it to ask for. All three
can be read in the same turn.

## Finishing

Call `check_summary` while you write, then `save_summary` with the finished markdown, the `layout`
of figures beside it, the `tiles` it leads with, and the `glossary` of terms it used.

A summary with no layout is prose with nothing to look at, and one with a figure under every
heading is usually one that chose by habit rather than by session.

The summary does not exist until `save_summary` accepts it.
