"""Tolerant JSON record loaders for file-backed evaluation repositories."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


def load_json_model(path: Path, model_type: type[ModelT]) -> ModelT | None:
    """Parse one JSON file into a model, skipping corrupt or unreadable records."""
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        return model_type.model_validate_json(raw)
    except Exception:
        logger.warning("Skipping unreadable record at %s", path, exc_info=True)
        return None


def iter_json_models(directory: Path, model_type: type[ModelT]) -> Iterator[tuple[Path, ModelT]]:
    """Yield ``(path, model)`` for each readable JSON file under ``directory``."""
    for path in directory.glob("*.json"):
        model = load_json_model(path, model_type)
        if model is not None:
            yield path, model


def iter_jsonl_models(path: Path, model_type: type[ModelT]) -> Iterator[ModelT]:
    """Yield models from a JSONL file, skipping corrupt lines."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            yield model_type.model_validate_json(line)
        except Exception:
            logger.warning("Skipping unreadable audit line in %s", path, exc_info=True)
