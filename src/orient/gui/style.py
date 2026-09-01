"""The stylesheet: the two things Streamlit draws differently from the way this page reads.

The first is the reader's own answer. Streamlit gives every chat message the same treatment,
left-aligned and full width, so a question and the answer to it read as two remarks from the same
speaker. The answer is therefore drawn here rather than borrowed: Streamlit sizes a chat message
from its own line height and leaves the text hanging below any border put around it, which at a
large window is the whole bubble missing its last line.

The second is a term defined where the reader meets it. The browser's own `title` tooltip arrives
late, in a typeface of its choosing, and never on focus, so the definition is drawn too — matched
to the help Streamlit shows beside a metric, because two tooltips on one page that behave
differently is a page that looks unfinished.

Nothing here names a colour. Streamlit publishes its palette as `--st-` custom properties only
inside a v2 component's own frame, never on the page itself, so the shades are mixed from
`currentColor` and from `Canvas`, the browser's own page colour. Streamlit sets `color-scheme` on
the app root from the background of the active theme, which makes both of those follow the theme
rather than the operating system — the distinction matters, because the two disagree whenever a
reader picks a theme by hand.

Every length is relative — a fraction, a rem or a clamp — so the same sheet holds from a laptop to
a wall.
"""

from typing import Final

import streamlit as st

ARRIVE_MS: Final = 320

OPEN_DELAY_MS: Final = 200
CLOSE_DELAY_MS: Final = 300
FADE_MS: Final = 120

SHEET: Final = f"""
<style>
  /* The reader's own answer. Streamlit sizes the box inside a chat message from its own line
     height and treats the block within it as though it were shorter than the text it holds, so a
     border drawn around that box sits above the words. Owning the element outright is the only
     way the bubble fits its contents at every size. */
  .orient-said {{
      display: flex;
      justify-content: flex-end;
      margin: 0 0 1rem;
  }}

  .orient-said > span {{
      max-width: min(80%, 34rem);
      padding: 0.45rem 0.9rem;
      border-radius: 0.85rem 0.85rem 0.15rem 0.85rem;
      background: color-mix(in srgb, currentColor 9%, transparent);
      border: 1px solid color-mix(in srgb, currentColor 16%, transparent);
      text-align: right;
      overflow-wrap: anywhere;
  }}

  /* A term the writer flagged. Underlined rather than coloured, because colour alone would read
     as a link, and drawn with `text-decoration` rather than a border so it clears the descenders
     and follows the word across a line break. */
  .orient-term {{
      position: relative;
      cursor: help;
      text-decoration: underline dotted
          color-mix(in srgb, currentColor 75%, transparent);
      text-decoration-thickness: 0.09em;
      text-underline-offset: 0.22em;
  }}

  .orient-term:hover,
  .orient-term:focus-visible {{
      text-decoration-color: currentColor;
  }}

  /* The definition itself, in Streamlit's tooltip clothes: the body's own ink on a ground at
     the same radius, size, padding and shadow. The ground is lifted towards light rather than
     towards the ink, which is the direction Streamlit's own moves in both themes — in light it
     stays on the page colour and lets the shadow do the separating, and mixing towards the ink
     instead would grey a tooltip Streamlit leaves white. It is a child of the term, so moving
     onto it keeps it open and it can be read at length. There is no border, because Streamlit's
     has none and the shadow is what separates it from the page. */
  .orient-term > .orient-meaning {{
      position: absolute;
      bottom: calc(100% + 0.625rem);
      left: 50%;
      transform: translateX(-50%);
      z-index: 1000;
      width: max-content;
      max-width: min(28rem, 80vw);
      padding: 0.375rem 0.75rem;
      border-radius: 0.5rem;
      font-size: 0.875rem;
      font-weight: 400;
      line-height: 1.5;
      text-align: left;
      text-decoration: none;
      white-space: normal;
      color: inherit;
      background: color-mix(in srgb, Canvas 92%, white);
      box-shadow: 0 1px 4px light-dark(rgb(0 0 0 / 16%), rgb(0 0 0 / 40%));
      opacity: 0;
      visibility: hidden;
      transition:
          opacity {FADE_MS}ms ease-in {CLOSE_DELAY_MS}ms,
          visibility 0s linear {CLOSE_DELAY_MS + FADE_MS}ms;
  }}

  /* Focus as well as hover, so the definition is reachable from the keyboard. */
  .orient-term:hover > .orient-meaning,
  .orient-term:focus-visible > .orient-meaning {{
      opacity: 1;
      visibility: visible;
      transition:
          opacity {FADE_MS}ms ease-in {OPEN_DELAY_MS}ms,
          visibility 0s linear {OPEN_DELAY_MS}ms;
  }}

  /* Centring a tooltip on a term near the edge of a narrow window puts half of it off screen. */
  @media (max-width: 40rem) {{
      .orient-term > .orient-meaning {{
          left: 0;
          transform: none;
          max-width: 88vw;
      }}
  }}

  /* A figure needs room for its digits before it needs to share a row. */
  div[data-testid="stMetric"] {{
      min-width: 9rem;
  }}

  /* A tile or a panel arriving rather than appearing. The charts animate themselves — ECharts
     grows its own bars and draws its own lines on mount — but a metric and a bordered container
     have no entry of their own, and beside a chart that does they read as having been there all
     along. The reveal is paced from Python, an element at a time, so each of these plays once as
     it lands rather than all of them together. */
  @keyframes orient-arrive {{
      from {{ opacity: 0; transform: translateY(0.4rem); }}
      to {{ opacity: 1; transform: none; }}
  }}

  div[data-testid="stMetric"],
  div[data-testid="stMetric"][class*="st-key-"],
  div[data-testid="stVerticalBlockBorderWrapper"] {{
      animation: orient-arrive {ARRIVE_MS}ms ease-out both;
  }}

  /* Motion is a preference, and this one is decorative. */
  @media (prefers-reduced-motion: reduce) {{
      div[data-testid="stMetric"],
      div[data-testid="stVerticalBlockBorderWrapper"] {{
          animation: none;
      }}
  }}
</style>
"""


def apply() -> None:
    """Injected once per run, before anything it styles is drawn."""
    st.html(SHEET)
