from __future__ import annotations

import json
from pathlib import Path

from .contracts import IssueTaxonomyDocument, IssueTypeRecord


class TaxonomyRepository:
    def __init__(self, taxonomy_path: Path) -> None:
        self._taxonomy_path = taxonomy_path
        self._document = self._load()

    def _load(self) -> IssueTaxonomyDocument:
        if not self._taxonomy_path.is_file():
            raise FileNotFoundError(f"Issue taxonomy not found: {self._taxonomy_path}")
        payload = json.loads(self._taxonomy_path.read_text(encoding="utf-8"))
        return IssueTaxonomyDocument.model_validate(payload)

    @property
    def version(self) -> str:
        return self._document.taxonomy_version

    def list_active(self) -> list[IssueTypeRecord]:
        return [item for item in self._document.issue_types if item.status == "ACTIVE"]

    def get(self, issue_type_id: str) -> IssueTypeRecord | None:
        for item in self._document.issue_types:
            if item.issue_type_id == issue_type_id:
                return item
        return None

    def fallback_type_id(self) -> str:
        return "other.unclassified"
