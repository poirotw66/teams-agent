"""Document AI PDF layout parser port for Portal convert jobs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from knowledge_core.document_layout import ParsedDocument

__all__ = [
    "PdfLayoutParser",
    "PdfLayoutParserFactory",
    "configure_pdf_layout_parser_factory",
    "get_pdf_layout_parser_factory",
]


@runtime_checkable
class PdfLayoutParser(Protocol):
    name: str
    version: str

    def parse_pdf(self, payload: bytes, *, title: str) -> ParsedDocument:
        ...


@runtime_checkable
class PdfLayoutParserFactory(Protocol):
    def create(self, processor_name: str) -> PdfLayoutParser:
        ...


_pdf_layout_parser_factory: PdfLayoutParserFactory | None = None


def configure_pdf_layout_parser_factory(
    factory: PdfLayoutParserFactory | None,
) -> None:
    """Register composition-owned Document AI parser factory."""

    global _pdf_layout_parser_factory
    _pdf_layout_parser_factory = factory


def get_pdf_layout_parser_factory() -> PdfLayoutParserFactory | None:
    return _pdf_layout_parser_factory
