import re


def clean_message_text(text: str | None) -> str:
    """Normalize text left after the SDK removes a Teams recipient mention."""
    return re.sub(r"\s+", " ", text or "").strip()

