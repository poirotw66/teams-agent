#!/usr/bin/env python3
"""Backward-compatible entry point for local knowledge sync."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    sync_script = Path(__file__).resolve().parent / "sync_local_knowledge.py"
    sys.argv[0] = str(sync_script)
    runpy.run_path(str(sync_script), run_name="__main__")
