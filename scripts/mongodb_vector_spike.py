#!/usr/bin/env python3
"""Prepare a MongoDB Atlas Vector Search shadow collection from a JSON release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_service.mongodb_vector_spike import (
    MongoVectorSpikeSettings,
    ingest_shadow_release,
    vector_search_index_definition,
)
from agent_service.retrieval import HybridIndex


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--release-id", required=True)
    parser.add_argument(
        "--print-index-definition",
        action="store_true",
        help="Print the Atlas Search index definition without writing data.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    index = HybridIndex.load(args.index)
    dimensions = {
        len(chunk.vector) for chunk in index.chunks if chunk.vector
    }
    if len(dimensions) != 1:
        raise ValueError("The source index must have one consistent vector dimension.")
    dimension = next(iter(dimensions))
    if args.print_index_definition:
        print(json.dumps(vector_search_index_definition(dimension), indent=2))
        return 0

    settings = MongoVectorSpikeSettings.from_env()
    if settings is None:
        raise ValueError("MONGODB_URI is required for shadow ingestion.")
    written = ingest_shadow_release(
        index,
        settings,
        tenant_id=args.tenant_id,
        release_id=args.release_id,
    )
    print(f"Ingested {written} shadow chunks for release {args.release_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
