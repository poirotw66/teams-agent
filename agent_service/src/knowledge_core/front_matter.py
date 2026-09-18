"""YAML front-matter parsing shared by Knowledge Portal and Agent documents."""

from __future__ import annotations

import re
from typing import Any

import yaml

# Fields recognized in the YAML front matter block described in spec §9.
_FRONT_MATTER_PATTERN = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)
_KNOWN_FRONT_MATTER_KEYS = {
    "title",
    "owner",
    "category",
    "version",
    "effectiveDate",
    "reviewDate",
    "audience",
}


def parse_front_matter(raw_text: str) -> tuple[dict[str, Any], str]:
    """Split optional leading YAML front matter from the document body.

    Returns a tuple of (front_matter_dict, remaining_body_text). Documents
    without a leading ``---`` delimited block return an empty dict and the
    original text untouched, preserving current behaviour.
    """
    match = _FRONT_MATTER_PATTERN.match(raw_text)
    if not match:
        return {}, raw_text

    block = match.group(1)
    body = raw_text[match.end() :]
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML front matter: {exc}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise TypeError("Front matter must be a YAML mapping.")

    unknown_keys = set(data) - _KNOWN_FRONT_MATTER_KEYS
    if unknown_keys:
        raise ValueError(f"Unknown front matter field(s): {', '.join(sorted(unknown_keys))}")

    return data, body


def strip_excluded_markdown(raw_text: str) -> str:
    text = re.sub(
        r"(?ms)^## Archive metadata.*?^---\s*$",
        "",
        raw_text,
        count=1,
    )
    return re.split(
        r"(?m)^## Limitations / Gaps\s*$",
        text,
        maxsplit=1,
    )[0]


__all__ = [
    "parse_front_matter",
    "strip_excluded_markdown",
]
