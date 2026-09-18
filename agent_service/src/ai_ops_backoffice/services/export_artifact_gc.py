"""Orphan export artifact garbage-collection mixin."""

from __future__ import annotations

from operations_core.contracts import utc_now

__all__ = [
    "ExportArtifactGcMixin",
]


class ExportArtifactGcMixin:
    """Sweep unreferenced export content artifacts for ``ExportJobService``."""

    async def _collect_referenced_content_refs(self) -> set[str] | None:
        """Return complete durable refs, or ``None`` when the scan is incomplete."""
        list_all = getattr(self._job_store, "list_all_content_refs", None)
        referenced: set[str] = set(self._pending_content_refs)
        if callable(list_all):
            try:
                referenced.update(await list_all())
            except Exception:  # noqa: BLE001
                return None
        else:
            # Legacy stores without a complete scanner must not drive deletes.
            return None
        async with self._lock:
            for job in self._jobs.values():
                if job.content_ref:
                    referenced.add(job.content_ref)
        return referenced

    async def _artifact_older_than(
        self,
        content_ref: str,
        *,
        now_ts: float,
        min_age_seconds: int,
    ) -> bool:
        created_at = None
        created_at_fn = getattr(self._content_store, "created_at_epoch", None)
        if callable(created_at_fn):
            try:
                created_at = await created_at_fn(content_ref)
            except Exception:  # noqa: BLE001
                created_at = None
        if created_at is None:
            # Unknown age (remote backend without metadata) — retain.
            return False
        return (now_ts - float(created_at)) >= min_age_seconds

    async def purge_orphan_artifacts(self, *, min_age_seconds: int | None = None) -> int:
        """Delete attempt artifacts that no live job still references.

        Artifacts younger than ``min_age_seconds`` are kept so an in-flight
        worker that has uploaded but not yet committed ``content_ref`` is not
        raced by the sweeper. Cross-process pending uploads are covered by age;
        same-process pending refs are tracked in ``_pending_content_refs``.

        Fail closed: incomplete reference scans or unknown artifact age retain
        the object rather than treating "not in a capped page" as orphaned.
        """
        list_refs = getattr(self._content_store, "list_refs", None)
        if not callable(list_refs):
            return 0
        min_age = (
            min_age_seconds if min_age_seconds is not None else max(300, self._lease_seconds * 3)
        )
        referenced = await self._collect_referenced_content_refs()
        if referenced is None:
            return 0
        removed = 0
        now_ts = utc_now().timestamp()
        for content_ref in await list_refs():
            if content_ref in referenced or content_ref in self._pending_content_refs:
                continue
            if not await self._artifact_older_than(
                content_ref, now_ts=now_ts, min_age_seconds=min_age
            ):
                continue
            # Re-check references immediately before delete (lease/commit race).
            fresh = await self._collect_referenced_content_refs()
            if fresh is None or content_ref in fresh or content_ref in self._pending_content_refs:
                continue
            await self._content_store.delete(content_ref=content_ref)
            removed += 1
        return removed
