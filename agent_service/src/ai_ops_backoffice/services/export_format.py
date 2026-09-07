from __future__ import annotations

import csv
import io
import json
import zipfile
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from agent_service.operations.contracts import DEFAULT_TIMEZONE, utc_now

from .periods import ResolvedPeriod


def sanitize_csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


def _extract_tabular_rows(payload: dict[str, Any]) -> list[list[str]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    if not data:
        rows = [["key", "value"]]
        for key, value in payload.items():
            rows.append([sanitize_csv_cell(key), sanitize_csv_cell(value)])
        return rows

    export_meta = payload.get("exportMetadata") if isinstance(payload.get("exportMetadata"), dict) else {}
    export_type = str(export_meta.get("exportType") or "")
    items = data.get("items") or data.get("records") or data.get("routeDistribution")

    if export_type == "conversations" or (isinstance(items, list) and items and any(isinstance(it, dict) and "turns" in it for it in items)):
        headers = [
            "conversationId",
            "turnId",
            "occurredAt",
            "actorRef",
            "userMessage",
            "aiReply",
            "model",
            "issueTypeId",
            "route",
            "faqKey",
            "documentIds",
            "feedbackRating",
            "feedbackReason",
            "handoffStatus",
            "channelScope",
        ]
        rows: list[list[str]] = [headers]
        if isinstance(items, list):
            for conv in items:
                if not isinstance(conv, dict):
                    continue
                conv_id = str(conv.get("conversationId") or "")
                actor_ref = str(conv.get("actorRef") or "")
                channel_scope = str(conv.get("channelScope") or "")
                turns = conv.get("turns")
                if isinstance(turns, list) and turns:
                    for turn in turns:
                        if not isinstance(turn, dict):
                            continue
                        docs = turn.get("documentIds")
                        docs_str = ",".join(docs) if isinstance(docs, (list, tuple)) else str(docs or "")
                        rows.append([
                            sanitize_csv_cell(conv_id),
                            sanitize_csv_cell(turn.get("turnId") or ""),
                            sanitize_csv_cell(turn.get("occurredAt") or ""),
                            sanitize_csv_cell(turn.get("actorRef") or actor_ref),
                            sanitize_csv_cell(turn.get("userMessage") or ""),
                            sanitize_csv_cell(turn.get("aiReply") or ""),
                            sanitize_csv_cell(turn.get("model") or ""),
                            sanitize_csv_cell(turn.get("issueTypeId") or ""),
                            sanitize_csv_cell(turn.get("route") or ""),
                            sanitize_csv_cell(turn.get("faqKey") or ""),
                            sanitize_csv_cell(docs_str),
                            sanitize_csv_cell(turn.get("feedbackRating") or ""),
                            sanitize_csv_cell(turn.get("feedbackReason") or ""),
                            sanitize_csv_cell(turn.get("handoffStatus") or ""),
                            sanitize_csv_cell(channel_scope),
                        ])
                else:
                    routes = conv.get("routes")
                    routes_str = ",".join(routes) if isinstance(routes, (list, tuple)) else str(routes or "")
                    rows.append([
                        sanitize_csv_cell(conv_id),
                        "",
                        sanitize_csv_cell(conv.get("lastOccurredAt") or ""),
                        sanitize_csv_cell(actor_ref),
                        "",
                        "",
                        "",
                        "",
                        sanitize_csv_cell(routes_str),
                        "",
                        "",
                        "",
                        "",
                        "",
                        sanitize_csv_cell(channel_scope),
                    ])
        return rows

    if isinstance(items, list) and items and isinstance(items[0], dict):
        keys = list(items[0].keys())
        for it in items[1:]:
            if isinstance(it, dict):
                for k in it:
                    if k not in keys:
                        keys.append(k)
        rows = [keys]
        for it in items:
            if isinstance(it, dict):
                rows.append([sanitize_csv_cell(it.get(k)) for k in keys])
        return rows

    rows = [["key", "value"]]
    for key, value in payload.items():
        rows.append([sanitize_csv_cell(key), sanitize_csv_cell(value)])
    return rows


def flatten_for_csv(payload: dict[str, Any]) -> str:
    rows = _extract_tabular_rows(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _sheet_xml(rows: list[list[str]]) -> str:
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row, start=1):
            cell_ref = f"{_column_name(column_index)}{row_index}"
            cells.append(
                f'<c r="{cell_ref}" t="inlineStr"><is><t>{escape(sanitize_csv_cell(value))}</t></is></c>'
            )
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(xml_rows)}</sheetData></worksheet>"
    )


def flatten_for_xlsx(payload: dict[str, Any]) -> bytes:
    rows = _extract_tabular_rows(payload)
    sheet = _sheet_xml(rows)
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Export" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def period_metadata(period: ResolvedPeriod) -> dict[str, Any]:
    return {
        "preset": period.preset,
        "days": period.days,
        "startAt": period.start_at.isoformat(),
        "endAt": period.end_at.isoformat(),
        "timezone": DEFAULT_TIMEZONE,
    }


def wrap_export_payload(
    data: dict[str, Any],
    *,
    export_type: str,
    reason: str,
    requested_by: str,
    requested_role: str,
    export_format: str,
    period: ResolvedPeriod,
    pricing_version: str | None = None,
    query_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row_keys = {
        "issues_summary": "items",
        "feedback": "items",
        "knowledge_performance": "items",
        "conversations": "items",
        "routes_summary": "routeDistribution",
    }
    records = data.get(row_keys.get(export_type, ""))
    if isinstance(records, list):
        record_count = len(records)
        fields = sorted(
            {
                str(key)
                for record in records
                if isinstance(record, dict)
                for key in record
            }
        )
    else:
        record_count = 1
        fields = sorted(str(key) for key in data)
    metadata: dict[str, Any] = {
        "exportType": export_type,
        "exportFormat": export_format,
        "reason": reason,
        "requestedBy": requested_by,
        "requestedRole": requested_role,
        "generatedAt": utc_now().isoformat(),
        "timezone": DEFAULT_TIMEZONE,
        "period": period_metadata(period),
        "recordCount": record_count,
        "fields": fields,
    }
    if pricing_version:
        metadata["pricingVersion"] = pricing_version
    if query_filters:
        metadata["queryFilters"] = query_filters
    return {
        "exportMetadata": metadata,
        "data": data,
    }
