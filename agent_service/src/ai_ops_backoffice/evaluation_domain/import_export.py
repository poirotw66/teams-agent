from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

from agent_service.operations.access import ActorContext

from .errors import EvaluationValidationError
from .models import (
    CriterionItem,
    EvaluationCriteria,
    ImportValidationResult,
    ProvenanceSpec,
)
from .service import EvaluationService

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> str:
    """Sanitizes text cells to prevent CSV spreadsheet formula injection (CWE-1236)."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return f"'{text}"
    return text


def desanitize_csv_cell(value: str) -> str:
    """Strips leading single quote if prepended for spreadsheet formula defense."""
    if value.startswith("'") and len(value) > 1 and value[1] in FORMULA_PREFIXES:
        return value[1:]
    return value


class EvaluationImportExportManager:
    def __init__(self, service: EvaluationService) -> None:
        self._service = service
        self._staged_batches: dict[str, list[dict[str, Any]]] = {}

    def validate_import(
        self,
        content: str,
        *,
        file_format: str,
        owner_unit_id: str,
        actor: ActorContext,
    ) -> ImportValidationResult:
        self._service._authorize(actor, "ops.evals.write", owner_unit_id)

        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        similar_warnings: list[dict[str, Any]] = []

        if file_format.upper() == "JSONL":
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            for idx, line in enumerate(lines, start=1):
                try:
                    data = json.loads(line)
                    rows.append(data)
                except Exception as e:
                    errors.append({"row": idx, "field": "json", "message": f"Malformed JSON: {e}"})
        elif file_format.upper() == "CSV":
            reader = csv.DictReader(io.StringIO(content))
            for idx, raw_row in enumerate(reader, start=2):  # row 1 is header
                clean_row = {k.strip(): desanitize_csv_cell(v.strip()) for k, v in raw_row.items() if k}
                rows.append(clean_row)
        else:
            raise EvaluationValidationError(f"Unsupported import format: {file_format}")

        valid_rows_data: list[dict[str, Any]] = []
        existing_cases = self._service.list_cases(actor=actor, limit=500)
        existing_queries = {c["current_revision"]["query"].strip().lower() for c in existing_cases if "current_revision" in c}

        for idx, row in enumerate(rows, start=1):
            row_errors = []
            title = row.get("title", "").strip()
            query = row.get("query", "").strip()
            behavior = row.get("behavior", "ANSWER_WITH_CITATION").strip()

            if not title:
                row_errors.append({"row": idx, "field": "title", "message": "Title is required"})
            if not query:
                row_errors.append({"row": idx, "field": "query", "message": "Query is required"})
            if behavior not in ("ANSWER_WITH_CITATION", "CLARIFY", "REFUSE", "HANDOFF", "TOOL_TASK"):
                row_errors.append({"row": idx, "field": "behavior", "message": f"Invalid behavior: {behavior}"})

            if query.lower() in existing_queries:
                similar_warnings.append(
                    {"row": idx, "query": query, "message": "Query already exists in current eval case bank"}
                )

            if row_errors:
                errors.extend(row_errors)
            else:
                valid_rows_data.append(row)

        is_valid = len(errors) == 0 and len(valid_rows_data) > 0
        staged_id = None
        if is_valid:
            staged_id = f"stage_{uuid.uuid4().hex[:12]}"
            self._staged_batches[staged_id] = valid_rows_data

        return ImportValidationResult(
            is_valid=is_valid,
            total_rows=len(rows),
            valid_rows=len(valid_rows_data),
            error_rows=len(errors),
            errors=tuple(errors),
            similar_warnings=tuple(similar_warnings),
            staged_import_id=staged_id,
        )

    def commit_staged_import(
        self,
        staged_id: str,
        *,
        owner_unit_id: str,
        actor: ActorContext,
        correlation_id: str | None = None,
    ) -> list[str]:
        self._service._authorize(actor, "ops.evals.write", owner_unit_id)
        staged = self._staged_batches.pop(staged_id, None)
        if not staged:
            raise EvaluationValidationError(f"Staged import {staged_id} not found or expired")

        created_case_ids: list[str] = []
        for row in staged:
            title = row["title"]
            query = row["query"]
            behavior = row.get("behavior", "ANSWER_WITH_CITATION")
            tags = tuple(row.get("tags", [])) if isinstance(row.get("tags"), list) else ()
            criticality = row.get("criticality", "NORMAL")
            ref_answer = row.get("reference_answer")
            req_facts_raw = row.get("required_facts", [])
            facts = []
            if isinstance(req_facts_raw, list):
                for f_idx, item in enumerate(req_facts_raw, start=1):
                    if isinstance(item, str):
                        facts.append(CriterionItem(criterion_id=f"crit_{f_idx}", description=item))
                    elif isinstance(item, dict):
                        facts.append(CriterionItem(**item))

            criteria = EvaluationCriteria(
                required_facts=tuple(facts),
                forbidden_claims=tuple(row.get("forbidden_claims", ())),
                reference_answer=ref_answer,
            )

            provenance = ProvenanceSpec(
                source_type=row.get("source_type", "MANUAL"),
                source_id=row.get("source_id", f"import:{actor.user_id}"),
                source_version_id=row.get("source_version_id"),
            )

            created = self._service.create_case(
                title=title,
                query=query,
                owner_unit_id=owner_unit_id,
                behavior=behavior,
                criteria=criteria,
                tags=tags,
                criticality=criticality,
                provenance=provenance,
                actor=actor,
                correlation_id=correlation_id,
            )
            created_case_ids.append(created["case"]["case_id"])

        return created_case_ids

    def export_cases(
        self,
        *,
        actor: ActorContext,
        set_id: str | None = None,
        file_format: str = "JSONL",
    ) -> str:
        self._service._authorize(actor, "ops.evals.export")

        cases_to_export: list[dict[str, Any]] = []
        if set_id:
            set_detail = self._service.get_set_detail(set_id, actor=actor)
            versions = set_detail.get("versions", [])
            if not versions:
                return ""
            latest_version = versions[-1]
            rev_ids = set(latest_version.get("case_revision_ids", []))
            all_cases = self._service.list_cases(actor=actor, limit=1000)
            for item in all_cases:
                if item["current_revision"]["revision_id"] in rev_ids:
                    cases_to_export.append(item)
        else:
            cases_to_export = self._service.list_cases(actor=actor, limit=1000)

        if file_format.upper() == "JSONL":
            lines = []
            for item in cases_to_export:
                c = item["case"]
                r = item["current_revision"]
                record = {
                    "case_id": c["case_id"],
                    "title": c["title"],
                    "query": r["query"],
                    "behavior": r["behavior"],
                    "criticality": r["criticality"],
                    "tags": r["tags"],
                    "criteria": r["criteria"],
                    "evidence": r["evidence"],
                    "provenance": r["provenance"],
                    "status": r["status"],
                }
                lines.append(json.dumps(record, ensure_ascii=False))
            return "\n".join(lines)

        elif file_format.upper() == "CSV":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "case_id",
                "title",
                "query",
                "behavior",
                "criticality",
                "reference_answer",
                "tags",
                "status",
            ])
            for item in cases_to_export:
                c = item["case"]
                r = item["current_revision"]
                ref_ans = r["criteria"].get("reference_answer") or ""
                writer.writerow([
                    sanitize_csv_cell(c["case_id"]),
                    sanitize_csv_cell(c["title"]),
                    sanitize_csv_cell(r["query"]),
                    sanitize_csv_cell(r["behavior"]),
                    sanitize_csv_cell(r["criticality"]),
                    sanitize_csv_cell(ref_ans),
                    sanitize_csv_cell(",".join(r["tags"])),
                    sanitize_csv_cell(r["status"]),
                ])
            return output.getvalue()

        else:
            raise EvaluationValidationError(f"Unsupported export format: {file_format}")
