---
name: writing
description: The structure every market summary follows, the rules that hold at every reading level, and how figures are written. Use when turning researched measurements into the summary itself.
---

Write markdown, and nothing but the summary. No preamble, no note about what you did, no closing
offer to explain further.

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

Each section answers its own question. "What moved, and why" must give causes, not just name the
movers. A section whose data is missing may be left out entirely, but never left hollow.

## Figures

Every figure you write must be one that was measured and handed to you. Do not compute a new one
and do not carry a number out of a news article. A figure that is null was not measurable, which
means the window was too short, and null is not zero.

Read a figure back from the tool result before writing it. A number close to a measured one is
not the measured one: writing 7763.18 when the close was 7798.99 fails the same way inventing it
would, and costs the summary a rewrite. If you cannot point at the field a figure came from, drop
the sentence.

A return, a change or a distance arrives as a fraction and is written as a percentage: 0.0065 is
"0.65%". A close, a level, a yield or a price is already in its own units and keeps them. "The VIX
rose by 0.0055" is the first mistaken for the second: it rose 0.55%, to a level of 14.63.

A drawdown of zero means the instrument closed at its highest point of the past year. Write that,
not the zero.

## Breadth

Breadth and contribution were counted across the eleven sector ETFs, never across index
constituents. Say sector when you describe them. Writing "advancers led decliners" about an index
implies a count of its members that nobody made.

## Causes

Say what the data shows. Where an earlier summary's explanation did not hold, say so plainly and
say what is now unexplained. Never speculate about why anyone acted.

## Ending

The last section is what to watch, and it comes from the calendar and from open expectations, not
from a view about where the price is going.

Name only events the calendar returned. An article may mention something scheduled, and a
plausible event on a date the calendar left empty is the easiest thing here to invent. The date
gives it away: "on Sunday 16 August" when nothing in the calendar falls on the 16th quotes a
figure nothing measured. If the calendar is thin, say the week is quiet. That is a finding.

## Before you start

Read `references/compliance.md`. It is short and it is not optional.

Then read the guide for the reading level you were asked for, exactly one of
`references/beginner.md`, `references/intermediate.md` or `references/advanced.md`. Both can be
read in the same turn.

## Finishing

Call `save_summary` with the finished markdown. It parses the four sections, checks every figure
against what was measured, and refuses prose quoting anything that was not. A refusal names the
offending figures: fix those and call it again. The summary does not exist until it is accepted.
