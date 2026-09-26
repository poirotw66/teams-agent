#!/usr/bin/env python3
"""CLI for Vertex SA smoke. Implementation lives in agent_service."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENT_SRC = Path(__file__).resolve().parent.parent / "agent_service" / "src"
if str(_AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(_AGENT_SRC))

from agent_service.vertex_sa_smoke import main

if __name__ == "__main__":
    raise SystemExit(main())
