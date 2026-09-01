"""The console entry point, so the page starts the same way in a container and on a laptop.

Streamlit is started in-process rather than by shelling out to its CLI, which keeps the script
path resolved from the installed package instead of from wherever the process happened to begin.
"""

import sys
from importlib.resources import files
from typing import Final

from streamlit.web import bootstrap

from orient.serving import listener

DEFAULT_PORT: Final = 8501


def script() -> str:
    """Where the page lives once installed, which is not where the working directory is."""
    return str(files("orient.gui").joinpath("app.py"))


def main(argv: list[str] | None = None) -> int:
    where: Final = listener("orient-gui", sys.argv[1:] if argv is None else argv, DEFAULT_PORT)
    bootstrap.load_config_options(
        flag_options={"server.address": where.host, "server.port": where.port, "server.headless": True}
    )
    bootstrap.run(script(), is_hello=False, args=[], flag_options={})
    return 0


if __name__ == "__main__":
    sys.exit(main())
