"""Skills as packaged data, loaded the way Claude Code loads them.

Instructions live in `SKILL.md` files rather than in Python so a human can change how the system
reasons and writes without touching code, and so any MCP harness can read the same tree.

Loading is progressive: each phase asks for exactly the files it needs, so researching a currency
pair never pays for the equities guidance and never reads a level guide it is not writing to.

Frontmatter is `key: value` lines and nothing else, parsed here rather than through a YAML
dependency. Anything richer would be a format the tree does not use and a file could drift into.
"""

from collections.abc import Sequence
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Final

from pydantic import ValidationError

from orient.domain.models import AssetClass, Frozen, ReadingLevel

FENCE: Final = "---"
PACKAGE: Final = "orient.skills"

ANALYSIS: Final = "analysis/SKILL.md"
WRITING: Final = "writing/SKILL.md"
COMPLIANCE: Final = "writing/compliance.md"


class SkillError(RuntimeError):
    """A missing or malformed skill is a deployment fault, not something a run recovers from."""


class Skill(Frozen):
    name: str
    description: str
    body: str


class _Frontmatter(Frozen):
    name: str
    description: str


def _split(text: str, source: str) -> tuple[str, str]:
    """Returns the frontmatter block and the body, refusing a file that carries neither."""
    lines: Final = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        message = f"{source} does not open with a '{FENCE}' frontmatter fence"
        raise SkillError(message)

    closing: Final = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == FENCE), None)
    if closing is None:
        message = f"{source} never closes its frontmatter fence"
        raise SkillError(message)
    return "\n".join(lines[1:closing]), "\n".join(lines[closing + 1 :]).strip()


def _fields(block: str, source: str) -> _Frontmatter:
    entries: Final = {
        key.strip(): value.strip()
        for key, _, value in (line.partition(":") for line in block.splitlines() if line.strip())
    }
    try:
        return _Frontmatter.model_validate(entries)
    except ValidationError as exc:
        message = f"{source} frontmatter needs 'name' and 'description': {exc.error_count()} problem(s)"
        raise SkillError(message) from exc


def parse(text: str, source: str) -> Skill:
    block, body = _split(text, source)
    fields: Final = _fields(block, source)
    return Skill(name=fields.name, description=fields.description, body=body)


class Skills:
    """The tree, rooted wherever it is packaged, so a test points at a directory it wrote."""

    def __init__(self, root: Traversable | None = None) -> None:
        self._root: Final = root if root is not None else files(PACKAGE)

    def load(self, path: str) -> Skill:
        target: Final = self._root.joinpath(path)
        if not target.is_file():
            message = f"no skill at {path}"
            raise SkillError(message)
        return parse(target.read_text(encoding="utf-8"), path)

    def research(self, asset_class: AssetClass) -> tuple[Skill, ...]:
        """How to approach the task, plus the one instrument guide that applies."""
        return self._all(ANALYSIS, f"analysis/instruments/{asset_class}.md")

    def writing(self, level: ReadingLevel) -> tuple[Skill, ...]:
        """Structure, compliance, and the guide for the level being written to."""
        return self._all(WRITING, COMPLIANCE, f"writing/levels/{level}.md")

    def _all(self, *paths: str) -> tuple[Skill, ...]:
        return tuple(self.load(path) for path in paths)


def rendered(skills: Sequence[Skill]) -> str:
    """One block per skill, named, so the model can tell which instruction came from where."""
    return "\n\n".join(f"# {skill.name}\n\n{skill.description}\n\n{skill.body}" for skill in skills)
