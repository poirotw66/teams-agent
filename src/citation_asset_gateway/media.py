import hashlib
import hmac
import re
from io import BytesIO
from pathlib import Path, PurePosixPath
from time import time
from urllib.parse import quote

from PIL import Image, ImageOps

from teams_agent.settings import AgentSettings

SUPPORTED_IMAGE_FORMATS = {"PNG", "JPEG", "GIF"}
MAX_SOURCE_ASSET_BYTES = 20 * 1024 * 1024
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")


def sign_asset_path(path: str, expires: int, key: str) -> str:
    payload = f"{path}\n{expires}".encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


def storage_relative_from_delivery(delivery_path: str) -> tuple[str, bool]:
    """Map a signed delivery path to the on-disk / GCS-relative storage path.

    Delivery URLs never include the ``assets/`` segment (HMAC stays stable).
    Release storage always inserts ``assets/`` between the release id and the
    chunk-relative image path — the same rule for local files and GCS objects.

    Returns ``(storage_relative, is_release)``.
    """
    pure_path = PurePosixPath(delivery_path)
    if pure_path.is_absolute() or ".." in pure_path.parts or not pure_path.parts:
        raise PermissionError("Invalid asset path.")
    parts = pure_path.parts
    if len(parts) >= 3 and parts[0] == "releases":
        release_id = parts[1]
        if not _SAFE_IDENTIFIER.fullmatch(release_id):
            raise PermissionError("Invalid asset path.")
        rest = PurePosixPath(*parts[2:]).as_posix()
        if not rest or rest.startswith("assets/"):
            # Reject empty rest or delivery paths that already embed assets/
            # so callers cannot bypass the canonical contract.
            raise PermissionError("Invalid asset path.")
        return f"releases/{release_id}/assets/{rest}", True
    return pure_path.as_posix(), False


def resolve_local_asset_path(delivery_path: str, settings: AgentSettings) -> Path:
    """Resolve a delivery path against local source_dir (release) or asset_dir.

    Release-pinned URLs prefer ``releases/<id>/assets/<path>``. When that file
    is missing — typically because publish used a title slug that differs from
    the markdown asset folder — fall back to the corpus ``asset_dir/<path>``
    for the same relative image path.
    """
    storage_relative, is_release = storage_relative_from_delivery(delivery_path)
    root = (
        (settings.source_dir or Path()).resolve()
        if is_release
        else (settings.asset_dir or Path()).resolve()
    )
    resolved = (root / storage_relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise PermissionError("Invalid asset path.") from error
    if resolved.is_file() or not is_release:
        return resolved
    return _corpus_fallback_for_release(delivery_path, settings)


def _corpus_fallback_for_release(delivery_path: str, settings: AgentSettings) -> Path:
    """Map ``releases/<id>/<rest>`` to ``asset_dir/<rest>`` when release packaging missed the file."""
    pure_path = PurePosixPath(delivery_path)
    rest = PurePosixPath(*pure_path.parts[2:]).as_posix()
    if not rest:
        raise PermissionError("Invalid asset path.")
    asset_root = (settings.asset_dir or Path()).resolve()
    fallback = (asset_root / rest).resolve()
    try:
        fallback.relative_to(asset_root)
    except ValueError as error:
        raise PermissionError("Invalid asset path.") from error
    return fallback


def build_asset_url(
    path: str,
    settings: AgentSettings,
    now: int | None = None,
    *,
    release_id: str | None = None,
) -> str | None:
    """Build a signed /rag-assets URL.

    Delivery paths never contain ``assets/``. Storage backends insert that
    segment via ``storage_relative_from_delivery``.
    """
    if not settings.images_ready:
        return None
    delivery_path = path
    if release_id:
        if not _SAFE_IDENTIFIER.fullmatch(release_id):
            return None
        delivery_path = f"releases/{release_id}/{path}"
    issued_at = int(time()) if now is None else now
    expires = issued_at + settings.asset_url_ttl_seconds
    signature = sign_asset_path(
        delivery_path,
        expires,
        settings.asset_signing_key or "",
    )
    encoded_path = quote(delivery_path, safe="/")
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

    resolved = resolve_local_asset_path(pure_path.as_posix(), settings)
    if not resolved.is_file():
        raise FileNotFoundError(path)
    return resolved


def gcs_object_name_from_delivery(delivery_path: str, settings: AgentSettings) -> str:
    """Build the private GCS object name for a release delivery path."""
    storage_relative, is_release = storage_relative_from_delivery(delivery_path)
    if not is_release:
        raise FileNotFoundError(delivery_path)
    prefix = settings.asset_gcs_prefix.strip("/")
    return (
        f"{prefix}/tenants/{settings.asset_gcs_tenant_id}/{storage_relative}"
    ).lstrip("/")


def fetch_gcs_asset(path: str, settings: AgentSettings) -> bytes:
    """Fetch a release-pinned image from the private knowledge bucket."""
    if not settings.asset_gcs_bucket:
        raise FileNotFoundError(path)
    try:
        object_name = gcs_object_name_from_delivery(path, settings)
    except PermissionError as error:
        raise FileNotFoundError(path) from error

    try:
        from google.api_core.exceptions import Forbidden, GoogleAPIError, NotFound
        from google.cloud import storage
    except ImportError as error:
        raise RuntimeError("GCS image delivery dependency is unavailable.") from error

    blob = storage.Client().bucket(settings.asset_gcs_bucket).blob(object_name)
    try:
        blob.reload()
        if blob.size is not None and blob.size > MAX_SOURCE_ASSET_BYTES:
            raise ValueError("Source image exceeds the configured input size limit.")
        value = blob.download_as_bytes()
    except NotFound as error:
        raise FileNotFoundError(path) from error
    except Forbidden as error:
        raise PermissionError("GCS image delivery is not authorized.") from error
    except GoogleAPIError as error:
        raise RuntimeError("GCS image delivery failed.") from error
    if len(value) > MAX_SOURCE_ASSET_BYTES:
        raise ValueError("Source image exceeds the configured input size limit.")
    return value


def render_teams_image(path: Path, settings: AgentSettings) -> tuple[bytes, str]:
    return render_teams_image_bytes(path.read_bytes(), settings)


def render_teams_image_bytes(
    value: bytes,
    settings: AgentSettings,
) -> tuple[bytes, str]:
    with Image.open(BytesIO(value)) as source:
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
