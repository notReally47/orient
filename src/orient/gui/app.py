"""The page Streamlit runs.

Everything the page does lives in `flow`, which is a module and therefore importable, testable and
visible to coverage. A Streamlit script is none of those: it is compiled and executed rather than
imported, so logic left in here could only ever be exercised blind.

What stays is the one call that has to come before any other Streamlit command, and the call that
draws whichever turn the reader has reached.
"""

import streamlit as st

from orient.gui import flow

st.set_page_config(page_title=flow.TITLE, page_icon=flow.PAGE_ICON, layout="centered")

flow.render()
