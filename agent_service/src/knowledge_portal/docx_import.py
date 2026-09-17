"""Safe DOCX-to-Markdown conversion for knowledge ingestion."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree

_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MAX_ARCHIVE_MEMBERS = 2_000
_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


def docx_to_markdown(payload: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            _validate_archive(archive)
            document_xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as error:
        raise ValueError("Uploaded content is not a valid DOCX document.") from error
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as error:
        raise ValueError("DOCX document XML is malformed.") from error

    paragraphs: list[str] = []
    for paragraph in root.iter(f"{_WORD_NAMESPACE}p"):
        text = "".join(
            node.text or "" for node in paragraph.iter(f"{_WORD_NAMESPACE}t")
        ).strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        raise ValueError("DOCX document does not contain readable text.")
    return "\n\n".join(paragraphs)


def _validate_archive(archive: zipfile.ZipFile) -> None:
    members = archive.infolist()
    if len(members) > _MAX_ARCHIVE_MEMBERS:
        raise ValueError("DOCX archive contains too many members.")
    total_size = 0
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", member.filename):
            raise ValueError("DOCX archive contains an unsafe member path.")
        total_size += member.file_size
        if total_size > _MAX_UNCOMPRESSED_BYTES:
            raise ValueError("DOCX archive exceeds the uncompressed size limit.")
        if member.filename.casefold().endswith((".vba", "vbaproject.bin")):
            raise ValueError("Macro-enabled Office content is not supported.")
