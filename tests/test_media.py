from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image

from teams_agent.media import (
    build_asset_url,
    fetch_gcs_asset,
    render_teams_image,
    resolve_asset,
)
from teams_agent.settings import AgentSettings


def make_settings(tmp_path: Path) -> AgentSettings:
    return AgentSettings(
        asset_dir=tmp_path,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
        asset_url_ttl_seconds=3600,
        asset_max_dimension=1024,
        asset_max_bytes=1_000_000,
    )


def test_signed_asset_url_resolves_only_expected_file(tmp_path: Path) -> None:
    image_dir = tmp_path / "大州"
    image_dir.mkdir()
    image_path = image_dir / "p01.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    settings = make_settings(tmp_path)

    url = build_asset_url("大州/p01.png", settings, now=1_000)
    parsed = urlparse(url or "")
    query = parse_qs(parsed.query)
    resolved = resolve_asset(
        unquote(parsed.path.removeprefix("/rag-assets/")),
        query["expires"][0],
        query["signature"][0],
        settings,
        now=1_000,
    )

    assert resolved == image_path


def test_invalid_asset_signature_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    try:
        resolve_asset(
            "大州/p01.png",
            "4600",
            "invalid",
            settings,
            now=1_000,
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("Invalid signature must be rejected.")


def test_image_is_resized_for_teams(tmp_path: Path) -> None:
    image_path = tmp_path / "large.png"
    Image.new("RGB", (1191, 1684), "white").save(image_path)
    settings = make_settings(tmp_path)

    content, content_type = render_teams_image(image_path, settings)
    output_path = tmp_path / "output.png"
    output_path.write_bytes(content)

    with Image.open(output_path) as output:
        assert max(output.size) == 1024
    assert content_type == "image/png"
    assert len(content) <= 1_000_000


def test_release_asset_url_fetches_private_gcs_object(tmp_path: Path) -> None:
    settings = AgentSettings(
        **{
            **make_settings(tmp_path).__dict__,
            "asset_gcs_bucket": "knowledge-bucket",
            "asset_gcs_prefix": "knowledge-releases",
            "asset_gcs_tenant_id": "default",
        }
    )
    url = build_asset_url(
        "總公司IP話機操作/p02.png",
        settings,
        now=1_000,
        release_id="release-1",
    )
    parsed = urlparse(url or "")
    delivery_path = unquote(parsed.path.removeprefix("/rag-assets/"))
    blob = MagicMock(size=128)
    blob.download_as_bytes.return_value = b"image"
    bucket = MagicMock()
    bucket.blob.return_value = blob
    client = MagicMock()
    client.bucket.return_value = bucket

    with patch("google.cloud.storage.Client", return_value=client):
        value = fetch_gcs_asset(delivery_path, settings)

    assert value == b"image"
    bucket.blob.assert_called_once_with(
        "knowledge-releases/tenants/default/releases/release-1/"
        "assets/總公司IP話機操作/p02.png"
    )
