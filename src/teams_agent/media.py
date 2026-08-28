import hashlib
import hmac
from io import BytesIO
from pathlib import Path, PurePosixPath
from time import time
from urllib.parse import quote

from PIL import Image, ImageOps

from .settings import AgentSettings

SUPPORTED_IMAGE_FORMATS = {"PNG", "JPEG", "GIF"}


def sign_asset_path(path: str, expires: int, key: str) -> str:
    payload = f"{path}\n{expires}".encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


def build_asset_url(
    path: str,
    settings: AgentSettings,
    now: int | None = None,
) -> str | None:
    if not settings.images_ready:
        return None
    issued_at = int(time()) if now is None else now
    expires = issued_at + settings.asset_url_ttl_seconds
    signature = sign_asset_path(path, expires, settings.asset_signing_key or "")
    encoded_path = quote(path, safe="/")
    return (
        f"{settings.public_base_url}/rag-assets/{encoded_path}"
        f"?expires={expires}&signature={signature}"
    )


def resolve_asset(
    path: str,
    expires: str | None,
    signature: str | None,
    settings: AgentSettings,
    now: int | None = None,
) -> Path:
    if not settings.images_ready:
        raise PermissionError("RAG image delivery is not configured.")
    try:
        expiry = int(expires or "")
    except ValueError as error:
        raise PermissionError("Invalid asset expiry.") from error
    current_time = int(time()) if now is None else now
    if expiry < current_time or expiry > current_time + settings.asset_url_ttl_seconds:
        raise PermissionError("Asset URL has expired or has an invalid lifetime.")

    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        raise PermissionError("Invalid asset path.")
    expected = sign_asset_path(pure_path.as_posix(), expiry, settings.asset_signing_key or "")
    if not signature or not hmac.compare_digest(signature, expected):
        raise PermissionError("Invalid asset signature.")

    asset_dir = (settings.asset_dir or Path()).resolve()
    resolved = (asset_dir / pure_path).resolve()
    try:
        resolved.relative_to(asset_dir)
    except ValueError as error:
        raise PermissionError("Invalid asset path.") from error
    if not resolved.is_file():
        raise FileNotFoundError(path)
    return resolved


def render_teams_image(path: Path, settings: AgentSettings) -> tuple[bytes, str]:
    with Image.open(path) as source:
        if source.format not in SUPPORTED_IMAGE_FORMATS:
            raise ValueError("Unsupported image format.")
        image = ImageOps.exif_transpose(source)
        image.thumbnail(
            (settings.asset_max_dimension, settings.asset_max_dimension),
            Image.Resampling.LANCZOS,
        )
        output = BytesIO()
        if source.format == "JPEG":
            image.convert("RGB").save(
                output,
                format="JPEG",
                quality=88,
                optimize=True,
            )
            content_type = "image/jpeg"
        else:
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA")
            image.save(output, format="PNG", optimize=True)
            content_type = "image/png"
    value = output.getvalue()
    if len(value) > settings.asset_max_bytes:
        raise ValueError("Optimized image exceeds the configured size limit.")
    return value, content_type
