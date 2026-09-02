"""Shared helpers for Knowledge Portal PDF tests."""

from __future__ import annotations


def build_text_pdf_bytes(text: str) -> bytes:
    """Build a minimal text-based PDF with extractable content."""
    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content_stream = f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET".encode("ascii")
    objects = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        (
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
        ),
        f"4 0 obj<< /Length {len(content_stream)} >>stream\n".encode("ascii")
        + content_stream
        + b"\nendstream\nendobj\n",
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]
    body = b"".join(objects)
    header = b"%PDF-1.4\n"
    offsets = [0]
    cursor = len(header)
    for obj in objects:
        offsets.append(cursor)
        cursor += len(obj)
    xref_offset = cursor
    xref = [b"xref\n0 6\n", b"0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    trailer = (
        b"trailer<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return header + body + b"".join(xref) + trailer
