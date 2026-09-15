#!/usr/bin/env python3
"""Dry-run / apply historical SourceRecord original-asset migration.

Scans release source indexes and SourceRecord files, reports pairing status,
and optionally writes LEGACY_UNVERIFIED placeholders when an exact original
cannot be proven. Never guesses a newer version from a filename alone.

Usage:
    uv run python scripts/migrate_historical_source_originals.py --dry-run
    uv run python scripts/migrate_historical_source_originals.py --apply --tenant default
    uv run python scripts/migrate_historical_source_originals.py \\
        --firestore-project itr-aimasteryhub-lab --tenant default --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = REPO_ROOT / "data"


@dataclass(frozen=True)
class MigrationRow:
    tenant_id: str
    source_ref_id: str
    release_id: str
    document_id: str | None
    version_id: str | None
    source_path: str | None
    mapping_status: str
    original_asset_name: str | None
    artifact_ref: str | None
    action: str
    reason: str


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _iter_source_records(data_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    candidates = [
        data_dir / "ops" / "sources" / "records",
        data_dir / "sources" / "records",
        data_dir / "source_records",
    ]
    for root in candidates:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.json")):
            payload = _load_json(path)
            if isinstance(payload, dict) and (
                payload.get("source_ref_id") or payload.get("sourceRefId")
            ):
                records.append((path, payload))
    return records


def _release_index_entries(data_dir: Path) -> dict[str, dict[str, Any]]:
    """Map source_ref_id → release index entry when present."""

    indexed: dict[str, dict[str, Any]] = {}
    releases = data_dir / "releases"
    if not releases.is_dir():
        return indexed
    for release_dir in sorted(releases.iterdir()):
        if not release_dir.is_dir() or release_dir.name.startswith("."):
            continue
        for index_name in ("source_index.json", "sources_index.json", "index.json"):
            payload = _load_json(release_dir / index_name)
            if not isinstance(payload, dict):
                continue
            items = payload.get("sources") or payload.get("entries") or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                ref = str(item.get("source_ref_id") or item.get("sourceRefId") or "").strip()
                if not ref:
                    continue
                indexed[ref] = {
                    **item,
                    "release_id": item.get("release_id")
                    or item.get("releaseId")
                    or release_dir.name,
                }
    return indexed


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify_record(
    record: dict[str, Any],
    *,
    data_dir: Path,
    release_index: dict[str, dict[str, Any]],
) -> MigrationRow:
    tenant_id = str(record.get("tenant_id") or record.get("tenantId") or "default")
    source_ref_id = str(record.get("source_ref_id") or record.get("sourceRefId") or "")
    release_id = str(record.get("release_id") or record.get("releaseId") or "")
    document_id = record.get("document_id") or record.get("documentId")
    version_id = record.get("version_id") or record.get("versionId")
    source_path = record.get("source_path") or record.get("sourcePath")
    mapping_status = str(record.get("mapping_status") or record.get("mappingStatus") or "")
    original_name = record.get("original_asset_name") or record.get("originalAssetName")
    artifact_ref = record.get("artifact_ref") or record.get("artifactRef")
    content_hash = str(record.get("content_hash") or record.get("contentHash") or "")

    if artifact_ref and mapping_status == "AVAILABLE":
        return MigrationRow(
            tenant_id=tenant_id,
            source_ref_id=source_ref_id,
            release_id=release_id,
            document_id=str(document_id) if document_id else None,
            version_id=str(version_id) if version_id else None,
            source_path=str(source_path) if source_path else None,
            mapping_status=mapping_status or "AVAILABLE",
            original_asset_name=str(original_name) if original_name else None,
            artifact_ref=str(artifact_ref),
            action="keep",
            reason="artifact_ref already bound",
        )

    indexed = release_index.get(source_ref_id)
    if indexed and not release_id:
        release_id = str(indexed.get("release_id") or "")

    local_path: Path | None = None
    if source_path:
        candidate = data_dir / str(source_path)
        if candidate.is_file():
            local_path = candidate
        else:
            fallback = data_dir / "sources" / Path(str(source_path)).name
            if fallback.is_file():
                local_path = fallback

    if local_path is not None and content_hash:
        digest = _sha256_file(local_path)
        if digest and digest == content_hash:
            return MigrationRow(
                tenant_id=tenant_id,
                source_ref_id=source_ref_id,
                release_id=release_id,
                document_id=str(document_id) if document_id else None,
                version_id=str(version_id) if version_id else None,
                source_path=str(source_path) if source_path else None,
                mapping_status="AVAILABLE",
                original_asset_name=local_path.name,
                artifact_ref=str(artifact_ref) if artifact_ref else None,
                action="verify_local_hash",
                reason="local file matches content_hash; upload to artifact store separately",
            )

    if mapping_status in {"LEGACY_UNVERIFIED", "ORIGINAL_NOT_PRESERVED", "SOURCE_MISSING"}:
        return MigrationRow(
            tenant_id=tenant_id,
            source_ref_id=source_ref_id,
            release_id=release_id,
            document_id=str(document_id) if document_id else None,
            version_id=str(version_id) if version_id else None,
            source_path=str(source_path) if source_path else None,
            mapping_status=mapping_status,
            original_asset_name=str(original_name) if original_name else None,
            artifact_ref=str(artifact_ref) if artifact_ref else None,
            action="keep",
            reason="already marked non-exact",
        )

    return MigrationRow(
        tenant_id=tenant_id,
        source_ref_id=source_ref_id,
        release_id=release_id,
        document_id=str(document_id) if document_id else None,
        version_id=str(version_id) if version_id else None,
        source_path=str(source_path) if source_path else None,
        mapping_status="LEGACY_UNVERIFIED",
        original_asset_name=str(original_name) if original_name else None,
        artifact_ref=str(artifact_ref) if artifact_ref else None,
        action="mark_legacy_unverified",
        reason="no proven original/artifact pairing for this version",
    )


def _apply_legacy_marker(path: Path, record: dict[str, Any]) -> None:
    record = dict(record)
    record["mapping_status"] = "LEGACY_UNVERIFIED"
    record["mappingStatus"] = "LEGACY_UNVERIFIED"
    record["migrated_at"] = datetime.now(timezone.utc).isoformat()
    record["migration_note"] = (
        "Historical source lacked a proven original artifact pairing; "
        "marked LEGACY_UNVERIFIED without guessing a newer version."
    )
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _iter_firestore_source_records(
    *,
    project_id: str,
    tenant_filter: str | None,
) -> list[tuple[str, dict[str, Any]]]:
    """Load SourceRecords from Firestore tenants/{tenant}/source_records.

    Returns (doc_path, payload) tuples where doc_path is a logical identifier
    used for apply logging (not a local filesystem path).
    """

    try:
        from google.cloud import firestore
    except ImportError as error:  # pragma: no cover - optional cloud dependency
        raise RuntimeError(
            "Firestore migration requires google-cloud-firestore. "
            "Install agent_service[firestore] extras."
        ) from error

    client = firestore.Client(project=project_id)
    tenants: list[str]
    if tenant_filter:
        tenants = [tenant_filter]
    else:
        tenants = [snap.id for snap in client.collection("tenants").stream()]

    records: list[tuple[str, dict[str, Any]]] = []
    for tenant_id in tenants:
        collection = (
            client.collection("tenants")
            .document(tenant_id)
            .collection("source_records")
        )
        for snap in collection.stream():
            payload = snap.to_dict() or {}
            if not isinstance(payload, dict):
                continue
            if not (payload.get("source_ref_id") or payload.get("sourceRefId")):
                payload = {**payload, "source_ref_id": snap.id}
            if not payload.get("tenant_id") and not payload.get("tenantId"):
                payload = {**payload, "tenant_id": tenant_id}
            records.append((f"firestore:{tenant_id}/{snap.id}", payload))
    return records


def _apply_legacy_marker_firestore(doc_path: str, record: dict[str, Any]) -> None:
    """Mark a Firestore SourceRecord as LEGACY_UNVERIFIED without guessing versions."""

    if not doc_path.startswith("firestore:"):
        raise ValueError(f"Not a Firestore document path: {doc_path}")
    _, remainder = doc_path.split(":", 1)
    tenant_id, source_ref_id = remainder.split("/", 1)
    try:
        from google.cloud import firestore
    except ImportError as error:  # pragma: no cover
        raise RuntimeError(
            "Firestore apply requires google-cloud-firestore."
        ) from error

    project_id = str(record.get("_project_id") or "").strip() or None
    client = firestore.Client(project=project_id) if project_id else firestore.Client()
    doc_ref = (
        client.collection("tenants")
        .document(tenant_id)
        .collection("source_records")
        .document(source_ref_id)
    )
    patch = {
        "mapping_status": "LEGACY_UNVERIFIED",
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "migration_note": (
            "Historical source lacked a proven original artifact pairing; "
            "marked LEGACY_UNVERIFIED without guessing a newer version."
        ),
    }
    doc_ref.set(patch, merge=True)


def migrate(
    *,
    data_dir: Path,
    tenant_filter: str | None,
    dry_run: bool,
    apply: bool,
    firestore_project: str | None = None,
) -> int:
    release_index = _release_index_entries(data_dir)
    rows: list[MigrationRow] = []
    if firestore_project:
        source_records = _iter_firestore_source_records(
            project_id=firestore_project,
            tenant_filter=tenant_filter,
        )
    else:
        source_records = [
            (str(path), record) for path, record in _iter_source_records(data_dir)
        ]

    for path, record in source_records:
        tenant_id = str(record.get("tenant_id") or record.get("tenantId") or "default")
        if tenant_filter and tenant_id != tenant_filter:
            continue
        row = _classify_record(record, data_dir=data_dir, release_index=release_index)
        rows.append(row)
        if apply and not dry_run and row.action == "mark_legacy_unverified":
            if str(path).startswith("firestore:"):
                record_with_project = {**record, "_project_id": firestore_project}
                _apply_legacy_marker_firestore(str(path), record_with_project)
            else:
                _apply_legacy_marker(Path(path), record)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.action] = counts.get(row.action, 0) + 1

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "dataDir": str(data_dir),
        "firestoreProject": firestore_project,
        "dryRun": dry_run or not apply,
        "tenantFilter": tenant_filter,
        "counts": counts,
        "rows": [asdict(row) for row in rows],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--tenant", default=None, help="Optional tenant filter.")
    parser.add_argument(
        "--firestore-project",
        default=None,
        help="When set, scan Firestore tenants/*/source_records instead of local files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report only (default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write LEGACY_UNVERIFIED markers for unproven pairings.",
    )
    args = parser.parse_args(argv)
    dry_run = not args.apply
    return migrate(
        data_dir=args.data_dir.resolve(),
        tenant_filter=args.tenant,
        dry_run=dry_run,
        apply=args.apply,
        firestore_project=args.firestore_project,
    )


if __name__ == "__main__":
    raise SystemExit(main())
