from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .contracts import ClassificationSource
from .taxonomy import TaxonomyRepository

_VALID_SOURCES = frozenset(
    {
        "MODEL",
        "KEYWORD_RULE",
        "FAQ_MAPPING",
        "DOCUMENT_MAPPING",
        "MANUAL",
        "FALLBACK",
    }
)


@dataclass(frozen=True)
class IssueClassification:
    issue_type_id: str
    classification_source: ClassificationSource
    confidence_status: str
    normalized_description: str


class IssueClassifier:
    def __init__(
        self,
        taxonomy: TaxonomyRepository,
        rules_path: Path | None = None,
    ) -> None:
        self._taxonomy = taxonomy
        self._rules_path = rules_path
        self._faq_mapping: dict[str, dict[str, str]] = {}
        self._keyword_rules: list[dict[str, object]] = []
        if rules_path and rules_path.is_file():
            payload = json.loads(rules_path.read_text(encoding="utf-8"))
            self._faq_mapping = payload.get("faq_key_mapping") or {}
            self._keyword_rules = list(payload.get("keyword_rules") or [])

    def classify(
        self,
        description: str,
        *,
        route: str,
        faq_key: str | None = None,
        model_issue_type_id: str | None = None,
    ) -> IssueClassification:
        """Classify an issue for analytics taxonomy.

        Prefer structured extractor outputs when provided:
        - ``faq_key`` → FAQ_MAPPING
        - ``model_issue_type_id`` → MODEL (extractor/LLM taxonomy id)

        Keyword rules are always labeled ``KEYWORD_RULE``, never ``MODEL``.
        """
        normalized = " ".join(description.lower().split())
        if faq_key and faq_key in self._faq_mapping:
            mapped = self._faq_mapping[faq_key]
            issue_type_id = str(mapped["issue_type_id"])
            if self._taxonomy.get(issue_type_id):
                return IssueClassification(
                    issue_type_id=issue_type_id,
                    classification_source="FAQ_MAPPING",
                    confidence_status="HIGH",
                    normalized_description=normalized,
                )
        if route == "FAQ" and faq_key:
            return IssueClassification(
                issue_type_id=self._taxonomy.fallback_type_id(),
                classification_source="FAQ_MAPPING",
                confidence_status="LOW",
                normalized_description=normalized,
            )
        if model_issue_type_id and self._taxonomy.get(model_issue_type_id):
            return IssueClassification(
                issue_type_id=model_issue_type_id,
                classification_source="MODEL",
                confidence_status="HIGH",
                normalized_description=normalized,
            )
        best_match = self._match_keywords(normalized)
        if best_match is not None:
            issue_type_id, source = best_match
            if self._taxonomy.get(issue_type_id):
                return IssueClassification(
                    issue_type_id=issue_type_id,
                    classification_source=source,
                    confidence_status="MEDIUM",
                    normalized_description=normalized,
                )
        return IssueClassification(
            issue_type_id=self._taxonomy.fallback_type_id(),
            classification_source="FALLBACK",
            confidence_status="LOW",
            normalized_description=normalized,
        )

    def _match_keywords(self, normalized: str) -> tuple[str, ClassificationSource] | None:
        best: tuple[str, ClassificationSource, int] | None = None
        for rule in self._keyword_rules:
            keywords = [str(item).lower() for item in rule.get("keywords") or []]
            if not keywords:
                continue
            hits = sum(1 for keyword in keywords if keyword in normalized)
            if hits == 0:
                continue
            issue_type_id = str(rule["issue_type_id"])
            # Keyword hits must never be marketed as MODEL output.
            raw_source = str(rule.get("source") or "KEYWORD_RULE")
            if raw_source in {"MODEL", "KEYWORD"}:
                source: ClassificationSource = "KEYWORD_RULE"
            elif raw_source in _VALID_SOURCES:
                source = raw_source  # type: ignore[assignment]
            else:
                source = "KEYWORD_RULE"
            candidate = (issue_type_id, source, hits)
            if best is None or candidate[2] > best[2]:
                best = candidate
        if best is None:
            return None
        return best[0], best[1]

    @staticmethod
    def document_id_from_source_path(source_path: str | None) -> str | None:
        if not source_path:
            return None
        normalized = source_path.strip().strip("/")
        if not normalized:
            return None
        stem = Path(normalized).stem
        return re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-") or None
