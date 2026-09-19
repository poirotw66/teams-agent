"""Unit tests for scripts/check_frontend_dto_overlap.py."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_frontend_dto_overlap.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_frontend_dto_overlap", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrontendDtoOverlapTests(unittest.TestCase):
    def test_reexports_are_not_treated_as_collisions(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            types = root / "types.ts"
            generated = root / "generated.ts"
            types.write_text(
                "export type { Foo } from './generated/backoffice-schemas';\n"
                "export interface Bar { id: string }\n",
                encoding="utf-8",
            )
            generated.write_text(
                "export interface Foo { id: string }\nexport interface Baz { id: string }\n",
                encoding="utf-8",
            )
            hand = mod.declared_names(types.read_text(encoding="utf-8"))
            gen = mod.declared_names(generated.read_text(encoding="utf-8"))
            reexports = mod.reexported_names(types.read_text(encoding="utf-8"))
            collisions = (hand & gen) - reexports
            self.assertEqual(collisions, set())
            self.assertEqual(reexports & gen, {"Foo"})

    def test_parallel_interface_bodies_are_collisions(self) -> None:
        mod = _load_module()
        types_src = "export interface Foo { id: string }\n"
        gen_src = "export interface Foo { id: string }\n"
        hand = mod.declared_names(types_src)
        gen = mod.declared_names(gen_src)
        reexports = mod.reexported_names(types_src)
        collisions = (hand & gen) - reexports
        self.assertEqual(collisions, {"Foo"})


if __name__ == "__main__":
    unittest.main()
