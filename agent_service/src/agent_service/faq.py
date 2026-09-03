"""FAQ Service (spec §7).

This module is a pure, deterministic lookup layer. Per spec §7.3, the FAQ
Service MUST NOT:

- call an LLM
- perform semantic similarity matching
- rewrite or paraphrase FAQ answers
- generate content on its own

It only maps a pre-configured ``faqKey`` to a fixed answer, and reports
which keys are currently enabled so the Issue Extractor can be constrained
to choose only from configured keys (spec §7.2). Any change that adds
LLM calls, fuzzy matching, or answer rewriting to this module violates the
spec and should be rejected in review.
"""

import json
import logging
from pathlib import Path
from typing import Any

from .contracts import FaqEntry
from .settings import RagSettings

logger = logging.getLogger(__name__)


class FaqConfigError(ValueError):
    """Raised when the FAQ configuration file is malformed."""


class FaqRepository:
    """Loads FAQ entries from a JSON file.

    Supported JSON shapes:
      - ``{"faqs": [ {...FaqEntry...}, ... ]}``
      - a bare list: ``[ {...FaqEntry...}, ... ]``

    A missing file is treated as valid, optional configuration: the
    repository is simply empty and a warning is logged, rather than
    raising an error.
    """

    def __init__(self, entries: list[FaqEntry]):
        self._by_key: dict[str, FaqEntry] = {}
        for entry in entries:
            if entry.faqKey in self._by_key:
                raise FaqConfigError(
                    f"Duplicate faqKey {entry.faqKey!r} in FAQ configuration; "
                    "faqKey values must be unique."
                )
            self._by_key[entry.faqKey] = entry

    @property
    def entries(self) -> list[FaqEntry]:
        return list(self._by_key.values())

    def get(
        self, faq_key: str, audience_group_ids: tuple[str, ...] = ()
    ) -> FaqEntry | None:
        return self._by_key.get(faq_key)

    def available_keys(self, audience_group_ids: tuple[str, ...] = ()) -> list[str]:
        return [entry.faqKey for entry in self.entries if entry.enabled]

    @classmethod
    def load(cls, path: Path) -> "FaqRepository":
        if not path.exists():
            logger.warning("FAQ config file not found at %s; FAQ Service will be empty.", path)
            return cls([])

        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FaqConfigError(f"Unable to read FAQ config file {path}: {exc}") from exc

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise FaqConfigError(f"FAQ config file {path} is not valid JSON: {exc}") from exc

        if isinstance(data, dict):
            raw_entries = data.get("faqs")
            if raw_entries is None:
                raise FaqConfigError(
                    f"FAQ config file {path} must be a bare list or an object with a "
                    "'faqs' key."
                )
        elif isinstance(data, list):
            raw_entries = data
        else:
            raise FaqConfigError(
                f"FAQ config file {path} must be a JSON object with a 'faqs' key, "
                "or a bare JSON list."
            )

        if not isinstance(raw_entries, list):
            raise FaqConfigError(f"FAQ config file {path}: 'faqs' must be a list.")

        entries: list[FaqEntry] = []
        for index, raw_entry in enumerate(raw_entries):
            try:
                entries.append(FaqEntry.model_validate(raw_entry))
            except Exception as exc:  # pydantic ValidationError, etc.
                raise FaqConfigError(
                    f"FAQ config file {path}: entry at index {index} is invalid: {exc}"
                ) from exc

        logger.info("Loaded %s FAQ entries from %s", len(entries), path)
        return cls(entries)


class GovernedFaqRepository:
    """Maps approved runtime snapshots to the legacy fixed-answer contract."""

    def __init__(self, domain_service: Any):
        self._domain_service = domain_service

    @staticmethod
    def _entry(snapshot: Any) -> FaqEntry:
        return FaqEntry(
            id=snapshot.faq_id,
            faqKey=snapshot.faq_key,
            enabled=True,
            answer=snapshot.answer,
            versionId=snapshot.version_id,
        )

    def get(
        self, faq_key: str, audience_group_ids: tuple[str, ...] = ()
    ) -> FaqEntry | None:
        snapshot = self._domain_service.active_snapshot(
            faq_key=faq_key,
            audience_group_ids=audience_group_ids,
        )
        return self._entry(snapshot) if snapshot is not None else None

    def available_keys(self, audience_group_ids: tuple[str, ...] = ()) -> list[str]:
        return [
            snapshot.faq_key
            for snapshot in self._domain_service.active_snapshots(
                audience_group_ids=audience_group_ids
            )
        ]

    @classmethod
    def from_settings(cls, settings: RagSettings) -> "GovernedFaqRepository":
        from ai_ops_backoffice.faq_domain.repository import (
            FileFaqRepository,
            FirestoreFaqRepository,
        )
        from ai_ops_backoffice.faq_domain.service import FaqDomainService

        store_mode = settings.faq_governed_store_mode.upper()
        if store_mode == "FILE":
            path = settings.faq_governed_store_path or (
                settings.data_dir / "ops" / "phase2" / "faqs.json"
            )
            repository = FileFaqRepository(path)
        elif store_mode == "FIRESTORE":
            from google.cloud import firestore

            client_kwargs = {}
            if settings.faq_firestore_project:
                client_kwargs["project"] = settings.faq_firestore_project
            if settings.faq_firestore_database:
                client_kwargs["database"] = settings.faq_firestore_database
            repository = FirestoreFaqRepository(
                firestore.Client(**client_kwargs),
                collection_prefix=settings.faq_firestore_collection_prefix,
            )
        else:
            raise FaqConfigError(f"Unsupported governed FAQ store mode: {store_mode}")
        return cls(FaqDomainService(repository))


class FaqService:
    """Pure faqKey -> fixed-answer lookup. See module docstring for constraints."""

    def __init__(self, repository: Any):
        self._repository = repository

    def get(
        self, faq_key: str, audience_group_ids: tuple[str, ...] = ()
    ) -> FaqEntry | None:
        """Return the FAQ entry for ``faq_key`` only if it exists and is enabled."""
        entry = self._repository.get(faq_key, audience_group_ids)
        if entry is None or not entry.enabled:
            return None
        return entry

    def available_keys(self, audience_group_ids: tuple[str, ...] = ()) -> list[str]:
        """Return the faqKeys of enabled entries, for the Issue Extractor's prompt."""
        return self._repository.available_keys(audience_group_ids)

    @classmethod
    def from_settings(cls, settings: RagSettings) -> "FaqService":
        runtime_mode = settings.faq_runtime_mode.upper()
        if runtime_mode == "GOVERNED":
            return cls(GovernedFaqRepository.from_settings(settings))
        if runtime_mode != "LEGACY_JSON":
            raise FaqConfigError(f"Unsupported FAQ runtime mode: {runtime_mode}")
        path = settings.faq_path or (settings.data_dir / "faq.json")
        return cls(FaqRepository.load(path))
