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


def flatten_for_csv(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["key", "value"])
    for key, value in payload.items():
        writer.writerow([sanitize_csv_cell(key), sanitize_csv_cell(value)])
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
    rows = [["key", "value"]]
    for key, value in payload.items():
        rows.append([sanitize_csv_cell(key), sanitize_csv_cell(value)])
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
