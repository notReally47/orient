"""The conversation: which question is on screen, and what the answers add up to.

There is no text box. A reader picks an entry, then an asset class, an instrument, a session
and a reading level, each as its own turn, and the request is whatever those turns add up to.
Searching still reaches every instrument the vendor lists, so nothing is lost by removing the
box.

The run is watched by a fragment on a timer rather than by the script itself, which is what
keeps the Stop button answerable while the model is still working.
"""

from orient.gui.flow.page import render
from orient.gui.flow.shell import PAGE_ICON, REVISIT_PAGE, TITLE

__all__ = ["PAGE_ICON", "REVISIT_PAGE", "TITLE", "render"]
