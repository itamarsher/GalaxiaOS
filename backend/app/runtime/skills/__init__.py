"""Skills — markdown playbooks agents load on demand.

A *skill* is a structured capability module: a single Markdown file with a small
front-matter header (``name``, ``title``, ``description``, optional ``roles``) and
a body that lays out a step-by-step workflow and best practices for a common job
(e.g. running a cold-email campaign, auditing a competitor, writing the weekly
investor update).

Why this exists: baking every playbook into the always-on system prompt is
expensive (tokens) and rigid (a code change per playbook). Instead the prompt
carries only a compact *index* of the skills relevant to an agent's role, and the
agent pulls a skill's full instructions in with the ``load_skill`` tool only when
it actually needs them — progressive loading, à la DeerFlow. Dropping a new
``.md`` file into ``library/`` adds a skill with no code change.

The loader is pure and filesystem-backed; skills are parsed once at import.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_LIBRARY = Path(__file__).parent / "library"


@dataclass(frozen=True)
class Skill:
    name: str  # stable slug used by ``load_skill`` and the prompt index
    title: str
    description: str
    roles: tuple[str, ...]  # empty == available to every role
    body: str  # the full markdown playbook

    def available_to(self, role: str) -> bool:
        return not self.roles or role in self.roles


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a leading ``---`` front-matter block from the markdown body.

    Deliberately tiny (``key: value`` lines only) so skills need no YAML
    dependency. A file without front matter is treated as all-body.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    rest = stripped[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    header = rest[:end]
    body = rest[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in header.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip()
    return meta, body


def parse_skill_text(text: str, *, default_name: str = "") -> Skill:
    """Parse raw skill-file text (front matter + body) into a :class:`Skill`.

    ``default_name`` is used when the front matter omits ``name`` (the on-disk
    loader passes the filename stem). Exposed so the optimizer can validate a
    candidate file with exactly the same rules the loader applies.
    """
    meta, body = _parse_front_matter(text)
    name = meta.get("name") or default_name
    roles_raw = meta.get("roles", "")
    roles = tuple(r.strip() for r in roles_raw.replace(";", ",").split(",") if r.strip())
    return Skill(
        name=name,
        title=meta.get("title") or (name.replace("-", " ").title() if name else ""),
        description=meta.get("description", ""),
        roles=roles,
        body=body.strip(),
    )


def _load_skill_file(path: Path) -> Skill | None:
    return parse_skill_text(path.read_text(encoding="utf-8"), default_name=path.stem)


def _load_all() -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    if not _LIBRARY.is_dir():
        return skills
    for path in sorted(_LIBRARY.glob("*.md")):
        skill = _load_skill_file(path)
        if skill is not None:
            skills[skill.name] = skill
    return skills


_SKILLS: dict[str, Skill] = _load_all()


def all_skills() -> list[Skill]:
    return list(_SKILLS.values())


def get_skill(name: str) -> Skill | None:
    return _SKILLS.get((name or "").strip())


def skill_file(name: str) -> Path | None:
    """Absolute path to a skill's markdown file, or ``None`` if there is no such
    skill or its ``<name>.md`` file is missing.

    The optimizer treats the *whole* file (front matter + body) as the trainable
    unit — the ``description``/``roles`` trigger matters as much as the steps — so
    it needs the raw file, not just the parsed :class:`Skill`.
    """
    if get_skill(name) is None:
        return None
    path = _LIBRARY / f"{(name or '').strip()}.md"
    return path if path.is_file() else None


#: Repo-relative path of the skill library, for issue bodies / PR targets.
LIBRARY_REPO_PATH = "backend/app/runtime/skills/library"


def skills_for_role(role: str) -> list[Skill]:
    return [s for s in _SKILLS.values() if s.available_to(role)]


def index_for_role(role: str) -> str:
    """Compact bullet index of skills available to ``role`` for the system prompt."""
    relevant = skills_for_role(role)
    if not relevant:
        return "(no skills available)"
    return "\n".join(f"- {s.name}: {s.description or s.title}" for s in relevant)
