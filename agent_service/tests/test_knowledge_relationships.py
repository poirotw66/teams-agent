"""Tests for configurable knowledge relationship catalog."""

from __future__ import annotations

from pathlib import Path

from agent_service.knowledge_relationships import (
    load_knowledge_relationships,
    matching_relationships,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATALOG = _REPO_ROOT / "data" / "ops" / "knowledge_relationships.json"


def test_default_catalog_loads_companion_rules() -> None:
    rows = load_knowledge_relationships(_CATALOG)
    ids = {item.relationship_id for item in rows}
    assert "enterprise-app-trust" in ids
    assert "employee-portal-password-companion" in ids
    assert "adjacent-product-shu-sonic" in ids


def test_matching_relationships_requires_portal_and_password_markers() -> None:
    rows = load_knowledge_relationships(_CATALOG)
    matched = matching_relationships(
        "員工入口網忘記密碼怎麼辦",
        relationships=rows,
    )
    assert [item.relationship_id for item in matched] == [
        "employee-portal-password-companion"
    ]
    assert matching_relationships("員工入口網首頁", relationships=rows) == []


def test_matching_relationships_shu_sonic_requires_both_product_names() -> None:
    rows = load_knowledge_relationships(_CATALOG)
    matched = matching_relationships(
        "樹精靈無法登入 vs 超音樹閃退",
        relationships=rows,
    )
    assert [item.relationship_id for item in matched] == ["adjacent-product-shu-sonic"]
    assert matching_relationships("樹精靈無法登入", relationships=rows) == []
    assert (
        matching_relationships(
            "樹精靈無法登入跟超音樹閃退是不是同一份？",
            relationships=rows,
        )[0].relationship_id
        == "adjacent-product-shu-sonic"
    )
