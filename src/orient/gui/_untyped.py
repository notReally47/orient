"""The only GUI module permitted to touch untyped third-party libraries.

`streamlit-echarts` ships no type information, and Streamlit's session state is a bag of `Any` by
construction. Confining both here keeps the suppressions in one reviewable place and leaves the
rest of the front end strict, the same way `providers/_untyped` does for the market vendors.
"""

from collections.abc import Mapping
from typing import Final, TypeVar, cast

import streamlit as st
from streamlit_echarts import st_echarts  # pyright: ignore[reportUnknownVariableType]  # no stubs

Stored = TypeVar("Stored")

THEME: Final = "streamlit"


def chart(option: Mapping[str, object], height: str, key: str) -> None:
    """One ECharts figure. The return value is a selection nothing here listens for."""
    _ = st_echarts(dict(option), theme=THEME, height=height, key=key)  # pyright: ignore[reportUnknownMemberType]  # no stubs


def remembered(key: str, default: Stored) -> Stored:
    """Session state read back at the type it was stored as."""
    return cast("Stored", st.session_state.get(key, default))


def remember(key: str, value: object) -> None:
    st.session_state[key] = value


def forget(*keys: str) -> None:
    for key in keys:
        if key in st.session_state:
            del st.session_state[key]


def holds(key: str) -> bool:
    return key in st.session_state
