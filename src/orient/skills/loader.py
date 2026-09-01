"""The skill tree, read in the three tiers the Agent Skills spec defines.

Tier 1 is the catalog: name and description only, cheap enough to hand over before anything has
been decided. Tier 2 is a skill's body, read when a model decides it needs that skill. Tier 3 is
one bundled file under `references/`, read when the body points at it. Handing over a body before
it is asked for collapses the three tiers into one and makes the frontmatter decorative.

Frontmatter is parsed here rather than through a YAML dependency. The reference implementation
uses strictyaml and rejects `description: Use this when: ...`, which the spec's own guidance says
to tolerate; splitting on the first colon reads it correctly. Nothing in this tree needs the
nested shapes a real parser would buy.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Final

FENCE: Final = "---"
PACKAGE: Final = "orient.skills"
SKILL_FILE: Final = "SKILL.md"
REFERENCES: Final = "references"

MAX_NAME: Final = 64
MAX_DESCRIPTION: Final = 1024

NEXT: Final = (
    "Those instructions are in force from now on. Act on them in this turn: read whichever "
    "bundled files they told you to read, and call the tools they said this instrument needs."
)


class SkillError(RuntimeError):
    """A missing or malformed skill is a deployment fault, not something a run recovers from."""


@dataclass(frozen=True, slots=True)
class Listing:
    """Tier 1. What the model is told exists, before it has decided it wants any of it."""

    name: str
    description: str
    resources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Body:
    """Tier 2. The instructions, plus what they are allowed to point at."""

    name: str
    body: str
    resources: tuple[str, ...]


def _split(text: str, source: str) -> tuple[str, str]:
    lines: Final = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        message = f"{source} does not open with a '{FENCE}' frontmatter fence"
        raise SkillError(message)
    closing: Final = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == FENCE), None)
    if closing is None:
        message = f"{source} never closes its frontmatter fence"
        raise SkillError(message)
    return "\n".join(lines[1:closing]), "\n".join(lines[closing + 1 :]).strip()


def _fields(block: str, source: str) -> tuple[str, str]:
    entries: Final = {
        key.strip(): value.strip()
        for key, sep, value in (line.partition(":") for line in block.splitlines() if line.strip())
        if sep
    }
    name: Final = entries.get("name", "")
    description: Final = entries.get("description", "")
    if not name or not description:
        message = f"{source} frontmatter needs both 'name' and 'description'"
        raise SkillError(message)
    if len(name) > MAX_NAME or len(description) > MAX_DESCRIPTION:
        message = f"{source} frontmatter exceeds the spec's length limits"
        raise SkillError(message)
    return name, description


class Skills:
    """The tree, rooted wherever it is packaged, so a test points at a directory it wrote."""

    def __init__(self, root: Traversable | None = None) -> None:
        self._root: Final = root if root is not None else files(PACKAGE)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(entry.name for entry in self._skills()))

    def catalog(self) -> tuple[Listing, ...]:
        """Tier 1 for every skill in the tree, which is all a model needs to choose one."""
        return tuple(
            Listing(name=name, description=description, resources=self._resources(entry.name))
            for entry in self._skills()
            for name, description in (self._frontmatter(entry.name),)
        )

    def body(self, name: str) -> Body:
        """Tier 2. The frontmatter is stripped, since its two fields were already disclosed."""
        _, body = _split(self._read(name, SKILL_FILE), f"{name}/{SKILL_FILE}")
        return Body(name=name, body=body, resources=self._resources(name))

    def resource(self, name: str, path: str) -> str:
        """Tier 3. `path` is `references/<file>.md`, exactly as the body spelled it."""
        wanted: Final = path.removeprefix("./")
        if wanted not in self._resources(name):
            message = f"{name} has no resource at {path}"
            raise SkillError(message)
        return self._read(name, *wanted.split("/"))

    def _skills(self) -> Iterator[Traversable]:
        return (entry for entry in sorted(self._root.iterdir(), key=lambda e: e.name) if _is_skill(entry))

    def _frontmatter(self, name: str) -> tuple[str, str]:
        source: Final = f"{name}/{SKILL_FILE}"
        block, _ = _split(self._read(name, SKILL_FILE), source)
        return _fields(block, source)

    def _resources(self, name: str) -> tuple[str, ...]:
        folder: Final = self._root.joinpath(name, REFERENCES)
        if not folder.is_dir():
            return ()
        return tuple(sorted(f"{REFERENCES}/{entry.name}" for entry in folder.iterdir() if entry.is_file()))

    def _read(self, *parts: str) -> str:
        target: Final = self._root.joinpath(*parts)
        if not target.is_file():
            message = f"no skill file at {'/'.join(parts)}"
            raise SkillError(message)
        return target.read_text(encoding="utf-8")


def _is_skill(entry: Traversable) -> bool:
    return entry.is_dir() and entry.joinpath(SKILL_FILE).is_file()


def as_catalog(listings: Sequence[Listing]) -> str:
    """The tier-1 block, in the shape the spec's own reference implementation emits."""
    entries: Final = "\n".join(
        f"  <skill>\n    <name>{listing.name}</name>\n    <description>{listing.description}</description>\n  </skill>"
        for listing in listings
    )
    return f"<available_skills>\n{entries}\n</available_skills>"


def as_activation(body: Body) -> str:
    """Tier 2: the instructions, introduced by a marker rather than enclosed in one.

    The markers are self-closing because the proxy's compression sidecar protects the contents of
    every custom XML element it finds. Instructions wrapped in `<skill_content>...</skill_content>`
    are the one part of a transcript that can never be compressed, while the same instructions
    announced by `<skill name="..."/>` read identically to the model and shrink like any other
    prose. The tier-1 catalog keeps the enclosing shape, because it rides in the system message
    and no compressor is allowed to touch that.

    The last line is an instruction rather than the file list, because a tool result ending in a
    bare enumeration reads as having nothing left to do: a run activating the second skill
    answered that list with an empty turn, and the nudge it took to restart cost a turn of its
    own. What a model reads last is what it acts on.
    """
    listing: Final = ("\n\n<skill_resources/>\n" + "\n".join(body.resources)) if body.resources else ""
    return f'<skill name="{body.name}"/>\n\n{body.body}{listing}\n\n{NEXT}'
