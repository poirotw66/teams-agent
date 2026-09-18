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

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from .contracts import Citation, FaqEntry
from .settings import RagSettings

logger = logging.getLogger(__name__)

FAQ_SOURCE_TYPE = "FAQ"


def citation_for_faq(entry: FaqEntry, *, include_evidence: bool = True) -> Citation:
    """Build a Judge-verifiable FAQ provenance citation."""
    version_id = entry.versionId or "legacy"
    chunk_id = f"faq:{entry.id}:{version_id}"
    evidence = (
        f"[chunkId={chunk_id}]\n{entry.answer}" if include_evidence and entry.answer else None
    )
    return Citation(
        title=f"FAQ: {entry.faqKey}",
        chunkId=chunk_id,
        documentId=entry.id,
        versionId=version_id,
        sourceType=FAQ_SOURCE_TYPE,
        evidence=evidence,
        sourceAliases=[entry.faqKey, entry.id, f"FAQ:{entry.faqKey}"],
    )


def _with_fallback_provenance(entry: FaqEntry) -> FaqEntry:
    if entry.versionId:
        return entry
    payload = f"{entry.id}\0{entry.faqKey}\0{entry.answer}".encode()
    version_id = f"legacy-{hashlib.sha256(payload).hexdigest()[:16]}"
    return entry.model_copy(update={"versionId": version_id})


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
        for raw_entry in entries:
            entry = _with_fallback_provenance(raw_entry)
            if entry.faqKey in self._by_key:
                raise FaqConfigError(
                    f"Duplicate faqKey {entry.faqKey!r} in FAQ configuration; "
                    "faqKey values must be unique."
                )
            self._by_key[entry.faqKey] = entry

    @property
    def entries(self) -> list[FaqEntry]:
        return list(self._by_key.values())

    def get(self, faq_key: str, audience_group_ids: tuple[str, ...] = ()) -> FaqEntry | None:
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
                    f"FAQ config file {path} must be a bare list or an object with a 'faqs' key."
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

    def get(self, faq_key: str, audience_group_ids: tuple[str, ...] = ()) -> FaqEntry | None:
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
        from agent_service.runtime_hooks import build_faq_service

        service = build_faq_service(settings)
        if service is None:
            raise FaqConfigError(
                "GOVERNED FAQ mode requires composition.install_agent_hooks(); "
                "no FAQ service builder is registered."
            )
        # build_faq_service returns a full FaqService; unwrap its repository.
        repository = getattr(service, "_repository", None)
        if isinstance(repository, cls):
            return repository
        raise FaqConfigError("registered FAQ builder did not produce a GovernedFaqRepository")


class FaqService:
    """Pure faqKey -> fixed-answer lookup. See module docstring for constraints."""

    def __init__(self, repository: Any):
        self._repository = repository

    def get(self, faq_key: str, audience_group_ids: tuple[str, ...] = ()) -> FaqEntry | None:
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
            from agent_service.runtime_hooks import build_faq_service

            service = build_faq_service(settings)
            if service is None:
                raise FaqConfigError(
                    "GOVERNED FAQ mode requires composition.install_agent_hooks(); "
                    "no FAQ service builder is registered."
                )
            return service
        if runtime_mode != "LEGACY_JSON":
            raise FaqConfigError(f"Unsupported FAQ runtime mode: {runtime_mode}")
        path = settings.faq_path or (settings.data_dir / "faq.json")
        return cls(FaqRepository.load(path))
