"""Document parsing facade: shared layout types plus Document AI adapter."""

from __future__ import annotations

import re

from knowledge_core.document_layout import (
    BlockKind,
    DocumentParser,
    MarkdownLayoutParser,
    ParsedBlock,
    ParsedDocument,
    ParsedPage,
)

__all__ = [
    "BlockKind",
    "DocumentAiLayoutParser",
    "DocumentParser",
    "MarkdownLayoutParser",
    "ParsedBlock",
    "ParsedDocument",
    "ParsedPage",
]


class DocumentAiLayoutParser:
    """Optional adapter for Document AI layout-parser responses."""

    name = "document-ai-layout"
    version = "v1"

    def __init__(self, processor_name: str) -> None:
        match = re.fullmatch(
            r"projects/[^/]+/locations/(?P<location>[^/]+)/processors/[^/]+",
            processor_name.strip(),
        )
        if match is None:
            raise ValueError("Document AI processor name is invalid.")
        self.processor_name = processor_name
        self.location = match.group("location")

    def parse(self, text: str, *, title: str) -> ParsedDocument:
        raise RuntimeError(
            "DocumentAiLayoutParser requires binary processing through the "
            "configured Document AI client; Markdown fallback is not implicit."
        )

    def parse_pdf(self, payload: bytes, *, title: str) -> ParsedDocument:
        try:
            from google.api_core.client_options import ClientOptions
            from google.cloud import documentai
        except ImportError as error:
            raise RuntimeError(
                "google-cloud-documentai is required for the Document AI parser."
            ) from error
        client = documentai.DocumentProcessorServiceClient(
            client_options=ClientOptions(api_endpoint=f"{self.location}-documentai.googleapis.com")
        )
        response = client.process_document(
            request=documentai.ProcessRequest(
                name=self.processor_name,
                raw_document=documentai.RawDocument(
                    content=payload,
                    mime_type="application/pdf",
                ),
            )
        )
        full_text = response.document.text or ""
        pages: list[ParsedPage] = []
        for page_number, page in enumerate(response.document.pages, 1):
            text = _layout_text(full_text, page.layout.text_anchor).strip()
            if not text:
                continue
            block = ParsedBlock(
                block_id=f"block-{page_number}",
                kind=BlockKind.TEXT,
                text=text,
                page_number=page_number,
                heading_path=(title,),
                bbox=_normalized_vertices(page.layout.bounding_poly),
                reading_order=page_number,
                confidence=float(page.layout.confidence or 0),
            )
            pages.append(ParsedPage(page_number=page_number, blocks=(block,)))
        return ParsedDocument(
            title=title,
            pages=tuple(pages),
            parser_name=self.name,
            parser_version=self.version,
        )


def _layout_text(full_text: str, anchor: object) -> str:
    segments = getattr(anchor, "text_segments", ())
    return "".join(
        full_text[
            int(getattr(segment, "start_index", 0) or 0) : int(
                getattr(segment, "end_index", 0) or 0
            )
        ]
        for segment in segments
    )


def _normalized_vertices(bounding_poly: object) -> tuple[float, ...] | None:
    vertices = getattr(bounding_poly, "normalized_vertices", ())
    values = tuple(
        coordinate for vertex in vertices for coordinate in (float(vertex.x), float(vertex.y))
    )
    return values or None
