"""ASCII slug helpers for Gemini File Search uploads and citation joins.

File Search stages each document under an ASCII ``display_name``. Filenames
that only differ by non-ASCII characters (for example ``VPN國外….md`` and
``VPN跳板….md``) collapse to the same provisional slug and must be detected
before index / upload / agent startup.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path


class FileSearchSlugCollisionError(ValueError):
    """Raised when multiple source files share one provisional ASCII slug."""


def provisional_ascii_slug(path: Path | str) -> str:
    """Derive the provisional ASCII slug from a filename (may collide)."""
    name = Path(path).name
    stem = Path(name).stem.encode("ascii", "ignore").decode("ascii").strip(" -_")
    suffix = Path(name).suffix.lower() or ".md"
    if not stem:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        stem = f"doc-{digest}"
    return f"{stem}{suffix}"


def disambiguated_ascii_slug(path: Path | str) -> str:
    """Stable unique slug for one file: provisional stem plus path hash.

    Hash the full source path (not just the basename) so identical filenames
    in different directories still get distinct slugs.
    """
    provisional = provisional_ascii_slug(path)
    stem = Path(provisional).stem
    suffix = Path(provisional).suffix
    key = Path(path).as_posix()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return f"{stem}-{digest}{suffix}"


def assign_unique_ascii_slugs(source_paths: Iterable[str]) -> dict[str, str]:
    """Map each source path to a corpus-unique ASCII slug.

    Non-colliding paths keep the provisional slug. Colliding groups receive
    ``disambiguated_ascii_slug`` values so File Search uploads and the local
    citation registry stay aligned without renaming source files.
    """
    ordered = list(dict.fromkeys(source_paths))
    buckets: dict[str, list[str]] = defaultdict(list)
    for source_path in ordered:
        buckets[provisional_ascii_slug(source_path)].append(source_path)

    assigned: dict[str, str] = {}
    for provisional, group in buckets.items():
        if len(group) == 1:
            assigned[group[0]] = provisional
            continue
        for source_path in group:
            assigned[source_path] = disambiguated_ascii_slug(source_path)
    return assigned


def slug_collision_groups(source_paths: Iterable[str]) -> dict[str, list[str]]:
    """Return provisional_slug -> [source_path, ...] for groups with size > 1."""
    buckets: dict[str, list[str]] = defaultdict(list)
    for source_path in dict.fromkeys(source_paths):
        buckets[provisional_ascii_slug(source_path)].append(source_path)
    return {slug: group for slug, group in buckets.items() if len(group) > 1}


def format_slug_collision_report(source_paths: Iterable[str]) -> str | None:
    """Human-readable collision report, or ``None`` when slugs are unique."""
    groups = slug_collision_groups(source_paths)
    if not groups:
        return None
    unique = assign_unique_ascii_slugs(source_paths)
    lines = [
        "File Search ASCII slug collisions detected.",
        "Filenames that only differ by non-ASCII characters collapse to the same slug.",
        "Rename files so ASCII stems are unique, or rely on auto-disambiguated upload slugs:",
    ]
    for provisional, members in sorted(groups.items()):
        lines.append(f"  provisional slug {provisional!r}:")
        for member in members:
            lines.append(
                f"    - {member} -> unique slug {unique[member]!r}"
            )
    return "\n".join(lines)


def ensure_unique_file_search_slugs(
    source_paths: Iterable[str],
    *,
    strict: bool = True,
) -> dict[str, str]:
    """Return unique slug map; optionally raise when provisional collisions exist.

    ``strict=True`` (default for ``rag-index``) fails closed so collisions are
    caught at build time instead of agent startup. Runtime registry builders
    may pass ``strict=False`` and still receive auto-disambiguated slugs.
    """
    paths = list(dict.fromkeys(source_paths))
    report = format_slug_collision_report(paths)
    assigned = assign_unique_ascii_slugs(paths)
    if report and strict:
        raise FileSearchSlugCollisionError(report)
    return assigned
