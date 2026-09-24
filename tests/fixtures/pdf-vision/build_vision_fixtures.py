"""Build the four minimal Vertex Vision sample PDFs without extra dependencies.

Uses Pillow (already in the repo root extra) for JPEG pages and the same raw
PDF object layout as ``agent_service/tests/pdf_test_helpers.py``.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).resolve().parent

SELECTABLE_TEXT = "Vertex Vision selectable 20260924 IT Service Desk"
SCAN_MARKER = "Vertex Vision scan-like 20260924 IT Service Desk"
TABLE_TITLE = "Vertex Vision table 20260924 IT Service Desk"
TABLE_ROW_A = "Priority  P1  Sev-1 outage"
TABLE_ROW_B = "Channel   Chat  IT Service Desk"
MIXED_TEXT = "Vertex Vision mixed 20260924 IT Service Desk"
MIXED_IMAGE = "Mixed-page image badge 20260924"


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _jpeg_bytes(text: str, *, size: tuple[int, int] = (640, 360)) -> bytes:
    image = Image.new("RGB", size, (236, 236, 236))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.rectangle((16, 16, size[0] - 16, size[1] - 16), outline=(40, 40, 40), width=3)
    draw.text((32, size[1] // 2 - 8), text, fill=(20, 20, 20), font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _assemble_pdf(objects: list[bytes]) -> bytes:
    header = b"%PDF-1.4\n"
    offsets = [0]
    cursor = len(header)
    for obj in objects:
        offsets.append(cursor)
        cursor += len(obj)
    xref = [f"xref\n0 {len(objects) + 1}\n".encode("ascii"), b"0000000000 65535 f \n"]
    xref.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:])
    trailer = (
        f"trailer<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{cursor}\n%%EOF\n"
    ).encode("ascii")
    return header + b"".join(objects) + b"".join(xref) + trailer


def build_selectable_text_pdf() -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({_escape_pdf_text(SELECTABLE_TEXT)}) Tj ET".encode(
        "ascii"
    )
    return _assemble_pdf(
        [
            b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
            b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
            (
                b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
            ),
            f"4 0 obj<< /Length {len(content)} >>stream\n".encode("ascii")
            + content
            + b"\nendstream\nendobj\n",
            b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
        ]
    )


def build_scan_like_pdf() -> bytes:
    jpeg = _jpeg_bytes(SCAN_MARKER)
    content = b"q 540 0 0 304 36 400 cm /Im1 Do Q"
    return _assemble_pdf(
        [
            b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
            b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
            (
                b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Contents 4 0 R /Resources<< /XObject<< /Im1 5 0 R >> >> >>endobj\n"
            ),
            f"4 0 obj<< /Length {len(content)} >>stream\n".encode("ascii")
            + content
            + b"\nendstream\nendobj\n",
            (
                f"5 0 obj<< /Type /XObject /Subtype /Image /Width 640 /Height 360 "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                f"/Length {len(jpeg)} >>stream\n"
            ).encode("ascii")
            + jpeg
            + b"\nendstream\nendobj\n",
        ]
    )


def build_simple_table_pdf() -> bytes:
    lines = [
        "BT",
        "/F1 12 Tf",
        f"72 720 Td ({_escape_pdf_text(TABLE_TITLE)}) Tj",
        "0 -24 Td (Item          Value           Owner) Tj",
        f"0 -20 Td ({_escape_pdf_text(TABLE_ROW_A)}) Tj",
        f"0 -20 Td ({_escape_pdf_text(TABLE_ROW_B)}) Tj",
        "ET",
        "72 668 m 540 668 l 72 648 m 540 648 l 72 628 m 540 628 l S",
        "72 688 m 72 608 l 220 688 m 220 608 l 360 688 m 360 608 l 540 688 m 540 608 l S",
    ]
    content = "\n".join(lines).encode("ascii")
    return _assemble_pdf(
        [
            b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
            b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
            (
                b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
            ),
            f"4 0 obj<< /Length {len(content)} >>stream\n".encode("ascii")
            + content
            + b"\nendstream\nendobj\n",
            b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
        ]
    )


def build_mixed_text_image_pdf() -> bytes:
    jpeg = _jpeg_bytes(MIXED_IMAGE, size=(320, 160))
    content = (
        f"BT /F1 12 Tf 72 720 Td ({_escape_pdf_text(MIXED_TEXT)}) Tj ET\n"
        "q 280 0 0 140 72 520 cm /Im1 Do Q"
    ).encode("ascii")
    return _assemble_pdf(
        [
            b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
            b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
            (
                b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Contents 4 0 R /Resources<< /XObject<< /Im1 5 0 R >> "
                b"/Font<< /F1 6 0 R >> >> >>endobj\n"
            ),
            f"4 0 obj<< /Length {len(content)} >>stream\n".encode("ascii")
            + content
            + b"\nendstream\nendobj\n",
            (
                f"5 0 obj<< /Type /XObject /Subtype /Image /Width 320 /Height 160 "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                f"/Length {len(jpeg)} >>stream\n"
            ).encode("ascii")
            + jpeg
            + b"\nendstream\nendobj\n",
            b"6 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
        ]
    )


def write_fixtures(output_dir: Path = OUTPUT_DIR) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = {
        "selectable-text.pdf": build_selectable_text_pdf(),
        "scan-like.pdf": build_scan_like_pdf(),
        "simple-table.pdf": build_simple_table_pdf(),
        "mixed-text-image.pdf": build_mixed_text_image_pdf(),
    }
    paths: dict[str, Path] = {}
    for name, payload in written.items():
        path = output_dir / name
        path.write_bytes(payload)
        paths[name] = path
    return paths


if __name__ == "__main__":
    for name, path in write_fixtures().items():
        print(f"{name} {path.stat().st_size} bytes")
