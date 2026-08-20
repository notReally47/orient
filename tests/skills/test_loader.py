"""The skill tree, read in tiers.

The point of every test here is what is *not* returned. A catalog that carried bodies, or an
activation that eagerly read the references beside it, would pass a naive assertion about content
and quietly undo progressive disclosure.
"""

from pathlib import Path
from typing import Final

import pytest

from orient.skills.loader import (
    MAX_DESCRIPTION,
    SkillError,
    Skills,
    as_activation,
    as_catalog,
)

BODY: Final = "Use the tools. Read `references/deep.md` when the question needs it."


def _tree(root: Path, *, description: str = "What this skill is for and when to reach for it") -> Path:
    skill: Final = root / "researching"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: researching\ndescription: {description}\n---\n\n{BODY}\n",
        encoding="utf-8",
    )
    (skill / "references" / "deep.md").write_text("The detail, loaded only when asked for.\n", encoding="utf-8")
    (skill / "references" / "other.md").write_text("Something else.\n", encoding="utf-8")
    (root / "notaskill").mkdir()
    (root / "notaskill" / "README.md").write_text("no frontmatter here\n", encoding="utf-8")
    return root


def test_a_directory_without_a_skill_file_is_not_a_skill(tmp_path: Path) -> None:
    """The tree is packaged alongside other files, so presence in the folder is not membership."""
    skills: Final = Skills(_tree(tmp_path))

    assert skills.names() == ("researching",)


def test_the_catalog_carries_the_frontmatter_and_not_the_body(tmp_path: Path) -> None:
    """Tier one is what a model is told before it has decided anything. A body here is the whole
    mistake this loader exists to fix."""
    listing: Final = Skills(_tree(tmp_path)).catalog()[0]

    assert listing.name == "researching"
    assert listing.description.startswith("What this skill is for")
    assert BODY not in listing.description


def test_the_catalog_names_the_bundled_files_without_reading_them(tmp_path: Path) -> None:
    listing: Final = Skills(_tree(tmp_path)).catalog()[0]

    assert listing.resources == ("references/deep.md", "references/other.md")


def test_activating_a_skill_returns_the_body_with_the_frontmatter_stripped(tmp_path: Path) -> None:
    """The two frontmatter fields were already disclosed in the catalog, so sending them again
    spends tokens to repeat something the model has."""
    body: Final = Skills(_tree(tmp_path)).body("researching")

    assert BODY in body.body
    assert "description:" not in body.body


def test_an_activation_lists_its_resources_without_their_contents(tmp_path: Path) -> None:
    rendered: Final = as_activation(Skills(_tree(tmp_path)).body("researching"))

    assert "<file>references/deep.md</file>" in rendered
    assert "The detail, loaded only when asked for" not in rendered


def test_a_resource_is_read_only_when_it_is_asked_for(tmp_path: Path) -> None:
    text: Final = Skills(_tree(tmp_path)).resource("researching", "references/deep.md")

    assert text.strip() == "The detail, loaded only when asked for."


def test_a_resource_outside_the_skill_is_refused(tmp_path: Path) -> None:
    """`path` arrives from a model, so it decides which file is read and must not escape the tree."""
    skills: Final = Skills(_tree(tmp_path))

    with pytest.raises(SkillError):
        _ = skills.resource("researching", "../../../etc/passwd")


def test_an_unknown_resource_is_refused_rather_than_returning_nothing(tmp_path: Path) -> None:
    with pytest.raises(SkillError):
        _ = Skills(_tree(tmp_path)).resource("researching", "references/absent.md")


def test_frontmatter_survives_a_colon_inside_the_description(tmp_path: Path) -> None:
    """The spec warns about this shape and the reference library rejects it. Splitting on the
    first colon reads it, which is the whole reason this parser is hand written."""
    skills: Final = Skills(_tree(tmp_path, description="Use this when: the session needs explaining"))

    assert skills.catalog()[0].description == "Use this when: the session needs explaining"


def test_a_file_without_frontmatter_is_a_deployment_fault(tmp_path: Path) -> None:
    skill: Final = tmp_path / "broken"
    skill.mkdir()
    (skill / "SKILL.md").write_text("no fence at all\n", encoding="utf-8")

    with pytest.raises(SkillError):
        _ = Skills(tmp_path).catalog()


def test_frontmatter_missing_a_description_is_a_deployment_fault(tmp_path: Path) -> None:
    """A description is what the catalog is made of; without one the skill can never be chosen."""
    skill: Final = tmp_path / "nameless"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: nameless\n---\n\nbody\n", encoding="utf-8")

    with pytest.raises(SkillError):
        _ = Skills(tmp_path).catalog()


def test_a_description_beyond_the_spec_limit_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SkillError):
        _ = Skills(_tree(tmp_path, description="x" * (MAX_DESCRIPTION + 1))).catalog()


def test_the_catalog_renders_as_the_block_the_spec_uses(tmp_path: Path) -> None:
    rendered: Final = as_catalog(Skills(_tree(tmp_path)).catalog())

    assert rendered.startswith("<available_skills>")
    assert "<name>researching</name>" in rendered
    assert BODY not in rendered


def test_the_packaged_tree_is_readable_and_every_skill_declares_itself() -> None:
    """The tree that ships is the one both the orchestrator and any MCP client will read."""
    skills: Final = Skills()

    assert set(skills.names()) == {"analysis", "writing"}
    for listing in skills.catalog():
        assert listing.description
        assert listing.resources
        assert skills.body(listing.name).body
