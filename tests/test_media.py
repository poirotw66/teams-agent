from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from PIL import Image

from teams_agent.media import (
    build_asset_url,
    fetch_gcs_asset,
    gcs_object_name_from_delivery,
    render_teams_image,
    resolve_asset,
    storage_relative_from_delivery,
)
from teams_agent.settings import AgentSettings


def make_settings(tmp_path: Path, **overrides) -> AgentSettings:
    source_dir = overrides.pop("source_dir", tmp_path / "data")
    asset_dir = overrides.pop("asset_dir", source_dir / "sources" / "assets")
    source_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    return AgentSettings(
        asset_dir=asset_dir,
        source_dir=source_dir,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
        asset_url_ttl_seconds=3600,
        asset_max_dimension=1024,
        asset_max_bytes=1_000_000,
        **overrides,
    )


def test_signed_asset_url_resolves_only_expected_file(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    image_dir = settings.asset_dir / "大州"
    image_dir.mkdir()
    image_path = image_dir / "p01.png"
    Image.new("RGB", (100, 100), "white").save(image_path)

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


def test_release_asset_url_resolves_under_source_dir_assets(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    image_dir = settings.source_dir / "releases" / "release-1" / "assets" / "大州"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "p01.png"
    Image.new("RGB", (100, 100), "white").save(image_path)

    # Wrong layout under asset_dir must not be preferred.
    decoy = settings.asset_dir / "releases" / "release-1" / "大州"
    decoy.mkdir(parents=True)
    Image.new("RGB", (40, 40), "red").save(decoy / "p01.png")

    url = build_asset_url(
        "大州/p01.png",
        settings,
        now=1_000,
        release_id="release-1",
    )
    parsed = urlparse(url or "")
    delivery = unquote(parsed.path.removeprefix("/rag-assets/"))
    query = parse_qs(parsed.query)

    assert delivery == "releases/release-1/大州/p01.png"
    assert "assets/" not in delivery
    assert storage_relative_from_delivery(delivery) == (
        "releases/release-1/assets/大州/p01.png",
        True,
    )

    resolved = resolve_asset(
        delivery,
        query["expires"][0],
        query["signature"][0],
        settings,
        now=1_000,
    )
    assert resolved == image_path


def test_release_delivery_with_embedded_assets_is_rejected() -> None:
    with pytest.raises(PermissionError):
        storage_relative_from_delivery("releases/release-1/assets/大州/p01.png")


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


def test_release_asset_falls_back_to_corpus_when_missing_from_package(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    corpus_dir = settings.asset_dir / "國金CRM_OTP綁訂操作"
    corpus_dir.mkdir(parents=True)
    corpus_image = corpus_dir / "p01.png"
    Image.new("RGB", (80, 80), "blue").save(corpus_image)

    # Release package has other docs but not this markdown-aligned folder.
    (
        settings.source_dir / "releases" / "release-1" / "assets" / "大州系統_功能無法點選"
    ).mkdir(parents=True)

    url = build_asset_url(
        "國金CRM_OTP綁訂操作/p01.png",
        settings,
        now=1_000,
        release_id="release-1",
    )
    parsed = urlparse(url or "")
    delivery = unquote(parsed.path.removeprefix("/rag-assets/"))
    query = parse_qs(parsed.query)

    assert delivery == "releases/release-1/國金CRM_OTP綁訂操作/p01.png"
    resolved = resolve_asset(
        delivery,
        query["expires"][0],
        query["signature"][0],
        settings,
        now=1_000,
    )
    assert resolved == corpus_image


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
    assert gcs_object_name_from_delivery(delivery_path, settings) == (
        "knowledge-releases/tenants/default/releases/release-1/"
        "assets/總公司IP話機操作/p02.png"
    )
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
