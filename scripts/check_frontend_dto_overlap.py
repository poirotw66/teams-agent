#!/usr/bin/env python3
"""Fail when console_frontend hand-written DTOs redefine OpenAPI-generated names.

Phase F exit wants handwritten duplicate frontend DTOs at zero. Exact name
collisions between ``shared/api/types.ts`` and ``generated/backoffice-schemas.ts``
must be re-exports (or removed), never parallel ``interface`` / ``type`` bodies.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TYPES = REPO_ROOT / "console_frontend" / "src" / "shared" / "api" / "types.ts"
GENERATED = (
    REPO_ROOT
    / "console_frontend"
    / "src"
    / "shared"
    / "api"
    / "generated"
    / "backoffice-schemas.ts"
)

DECL_RE = re.compile(r"^export (?:interface|type) (\w+)\b", re.M)
REEXPORT_RE = re.compile(
    r"export type \{([^}]+)\} from ['\"]\.\/generated\/backoffice-schemas['\"]",
    re.S,
)


def declared_names(source: str) -> set[str]:
    return set(DECL_RE.findall(source))


def reexported_names(source: str) -> set[str]:
    names: set[str] = set()
    for block in REEXPORT_RE.findall(source):
        for part in block.split(","):
            name = part.strip().split(" as ")[0].strip()
            if name:
                names.add(name)
    return names


def main() -> int:
    if not TYPES.is_file() or not GENERATED.is_file():
        print("missing types or generated schemas", file=sys.stderr)
        return 1

    types_src = TYPES.read_text(encoding="utf-8")
    generated_src = GENERATED.read_text(encoding="utf-8")
    hand_decls = declared_names(types_src)
    generated = declared_names(generated_src)
    reexports = reexported_names(types_src)

    collisions = sorted((hand_decls & generated) - reexports)
    if collisions:
        print(
            "DUPLICATE_DTO: handwritten declarations collide with generated schemas: "
            + ", ".join(collisions),
            file=sys.stderr,
        )
        return 1

    print(
        f"frontend DTO overlap OK: reexported={len(reexports & generated)}, "
        f"handwritten_only={len(hand_decls - generated)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
