"""HTTP Range header parsing for source file streaming."""

from __future__ import annotations


def parse_range_header(range_header: str | None, total_size: int) -> tuple[int, int] | None:
    """Parse an HTTP Range header string into a 0-indexed [start, end] byte tuple."""
    if not range_header or not range_header.startswith("bytes="):
        return None
    try:
        spec = range_header[6:].strip()
        parts = spec.split("-", 1)
        if len(parts) != 2:
            return None
        start_str, end_str = parts[0].strip(), parts[1].strip()
        if start_str and end_str:
            start = int(start_str)
            end = int(end_str)
        elif start_str:
            start = int(start_str)
            end = total_size - 1
        elif end_str:
            suffix_len = int(end_str)
            start = max(0, total_size - suffix_len)
            end = total_size - 1
        else:
            return None
        if start > end or start >= total_size or start < 0:
            return None
        end = min(end, total_size - 1)
        return (start, end)
    except (ValueError, TypeError):
        return None
