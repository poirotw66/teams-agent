#!/usr/bin/env python3
"""Replay operational events from a JSON file into the configured ops store.

Usage:
    cd agent_service
    OPS_STORE_MODE=FILE OPS_STORE_PATH=/tmp/ops-events uv run python ../scripts/ops_replay_events.py \\
        --input ../data/ops/sample_events.json

The input file must contain a JSON array of OperationalEvent-compatible objects.
Duplicate event_id values are skipped by the store (idempotent replay).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent_service" / "src"))

from agent_service.operations.contracts import OperationalEvent
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.file_store import FileOperationalStore
from agent_service.operations.stores.firestore_store import (
    FirestoreOperationalStore,
    build_firestore_client,
)
from agent_service.operations.stores.memory_store import MemoryOperationalStore


def _build_store(settings: OpsSettings):
    if settings.store_mode == "FILE":
        return FileOperationalStore(settings.store_path)
    if settings.store_mode == "MEMORY":
        return MemoryOperationalStore()
    if settings.store_mode == "FIRESTORE":
        client = build_firestore_client(settings.firestore_project, settings.firestore_database)
        return FirestoreOperationalStore(client, settings.firestore_collection)
    raise SystemExit(f"Unsupported OPS_STORE_MODE for replay: {settings.store_mode}")


async def replay(input_path: Path) -> int:
    settings = OpsSettings.from_env()
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Input file must contain a JSON array of events.")

    events = [OperationalEvent.model_validate(item) for item in payload]
    store = _build_store(settings)
    ingestion = EventIngestionService(store, settings)
    inserted = await ingestion.ingest_many(events)
    skipped = len(events) - inserted
    print(f"Replayed {len(events)} events: inserted={inserted}, skipped={skipped}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay operational events into the ops store.")
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Input file not found: {args.input}")
    return asyncio.run(replay(args.input))


if __name__ == "__main__":
    raise SystemExit(main())
