#!/usr/bin/env python3
"""Fail when console_frontend hand-written DTOs redefine OpenAPI-generated names.

Phase F exit wants handwritten duplicate frontend DTOs at zero. Exact name
collisions between shared API type modules and ``generated/backoffice-schemas.ts``
must be re-exports (or removed), never parallel ``interface`` / ``type`` bodies.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "console_frontend" / "src" / "shared" / "api"
TYPES_FILES = (
    API_ROOT / "types.ts",
    API_ROOT / "workbench" / "types.ts",
)
GENERATED = API_ROOT / "generated" / "backoffice-schemas.ts"

DECL_RE = re.compile(r"^export (?:interface|type) (\w+)\b", re.M)
REEXPORT_RE = re.compile(
    r"export type \{([^}]+)\} from ['\"](?:\.\/|\.\.\/)*generated\/backoffice-schemas['\"]",
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
    if not GENERATED.is_file():
        print("missing generated schemas", file=sys.stderr)
        return 1
    missing_types = [path for path in TYPES_FILES if not path.is_file()]
    if missing_types:
        print(
            "missing types files: "
            + ", ".join(path.as_posix() for path in missing_types),
            file=sys.stderr,
        )
        return 1

    generated_src = GENERATED.read_text(encoding="utf-8")
    generated = declared_names(generated_src)

    total_reexports = 0
    total_handwritten = 0
    collisions: list[str] = []

    for path in TYPES_FILES:
        source = path.read_text(encoding="utf-8")
        hand_decls = declared_names(source)
        reexports = reexported_names(source)
        total_reexports += len(reexports & generated)
        total_handwritten += len(hand_decls - generated)
        for name in sorted((hand_decls & generated) - reexports):
            collisions.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{name}")

    if collisions:
        print(
            "DUPLICATE_DTO: handwritten declarations collide with generated schemas: "
            + ", ".join(collisions),
            file=sys.stderr,
        )
        return 1

    print(
        f"frontend DTO overlap OK: reexported={total_reexports}, "
        f"handwritten_only={total_handwritten}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
