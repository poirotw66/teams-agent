"""Release source/materialization helpers for ReleasePublisher."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from knowledge_core.eligibility import is_generation_metadata_eligible

from .draft_assets import DraftAssetStore
from .models import KnowledgeVersionRecord, ReleaseManifestEntry
from .original_assets import OriginalAssetStore
from .settings import PortalSettings
from .validation import build_front_matter_markdown


def filter_eligible_versions(
    published_versions: list[KnowledgeVersionRecord],
    *,
    environment: str,
) -> list[KnowledgeVersionRecord]:
    return [
        version
        for version in published_versions
        if is_generation_metadata_eligible(
            content_state=version.content_state,
            effective_at=version.effective_at,
            expires_at=version.expires_at,
            applicable_environments=version.applicable_environments,
            environment=environment,
        )
    ]


def write_release_sources(
    *,
    release_dir: Path,
    published_versions: list[KnowledgeVersionRecord],
    settings: PortalSettings,
) -> list[ReleaseManifestEntry]:
    sources_dir = release_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[ReleaseManifestEntry] = []
    asset_store = DraftAssetStore(settings)
    original_store = OriginalAssetStore(settings)
    for version in published_versions:
        filename = f"{version.document_id}.md"
        body = version.canonical_content
        if not body.lstrip().startswith("---"):
            body = build_front_matter_markdown(
                title=version.title,
                owner_unit_id=version.owner_unit_id,
                effective_at=version.effective_at,
                review_due_at=version.review_due_at,
                audience_type=version.audience_type,
                audience_group_ids=version.audience_group_ids,
                version_number=version.version_number,
                body=body,
            )
        (sources_dir / filename).write_text(body, encoding="utf-8")
        asset_store.copy_assets_to_release(release_dir, version=version)
        original_available = original_store.copy_to_release(
            release_dir,
            version=version,
        )
        version_acl = (
            ["grp_public"]
            if version.audience_type == "ALL_EMPLOYEES"
            else [str(g).strip() for g in version.audience_group_ids if str(g).strip()]
            or ["grp_restricted"]
        )
        manifest.append(
            ReleaseManifestEntry(
                document_id=version.document_id,
                version_id=version.version_id,
                version_number=version.version_number,
                title=version.title,
                content_hash=version.content_hash,
                source_path=f"sources/{filename}",
                source_type=version.source_type,
                original_asset_available=original_available,
                original_asset_name=(
                    version.original_asset_name if original_available else None
                ),
                artifact_ref=getattr(version, "original_artifact_ref", None),
                acl_groups=version_acl,
                source_aliases=version.source_aliases,
                content_state=version.content_state,
                effective_at=version.effective_at,
                expires_at=version.expires_at,
                applicable_environments=version.applicable_environments,
            )
        )
    return manifest


def corpus_hash_for_manifest(manifest: list[ReleaseManifestEntry]) -> str:
    return hashlib.sha256(
        json.dumps(
            [entry.model_dump(mode="json") for entry in manifest],
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "corpus_hash_for_manifest",
    "filter_eligible_versions",
    "write_release_sources",
]
