"""Release GCS publish port so Portal never imports Agent GCS helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "PublishedReleaseInfo",
    "ReleaseDirectoryPublisher",
    "configure_release_directory_publisher",
    "get_release_directory_publisher",
]


@dataclass(frozen=True)
class PublishedReleaseInfo:
    bucket: str
    object_prefix: str
    manifest_generation: int
    index_generation: int


@runtime_checkable
class ReleaseDirectoryPublisher(Protocol):
    def publish(
        self,
        release_dir: Path,
        *,
        bucket_name: str,
        object_prefix: str,
        tenant_id: str,
        release_id: str,
    ) -> PublishedReleaseInfo:
        ...


_release_directory_publisher: ReleaseDirectoryPublisher | None = None


def configure_release_directory_publisher(
    publisher: ReleaseDirectoryPublisher | None,
) -> None:
    """Register composition-owned release directory publisher."""

    global _release_directory_publisher
    _release_directory_publisher = publisher


def get_release_directory_publisher() -> ReleaseDirectoryPublisher | None:
    return _release_directory_publisher
