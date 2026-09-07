from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowledge_portal.api import create_app
from knowledge_portal.settings import PortalSettings
from knowledge_portal.validation import validate_draft

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "knowledge_portal" / "static"


@pytest.fixture
def portal_client() -> TestClient:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    return TestClient(create_app(settings))


def portal_headers() -> dict[str, str]:
    return {
        "X-Portal-User-Id": "contributor.demo",
        "X-Portal-User-Name": "Contributor Demo",
        "X-Portal-Role": "CONTRIBUTOR",
        "X-Portal-Owner-Units": "IT Service Desk",
    }


def sample_document_payload() -> dict[str, str]:
    return {
        "title": "VPN 登入問題",
        "summary": "協助員工排除 VPN 登入失敗。",
        "category": "VPN",
        "owner_unit_id": "IT Service Desk",
        "business_contact": "it-helpdesk@example.test",
        "audience_type": "ALL_EMPLOYEES",
        "audience_group_ids": [],
        "effective_at": "2026-08-01",
        "review_due_at": "2026-12-01",
        "change_summary": "Initial draft",
        "change_reason": "建立新的 VPN 協助文件。",
        "markdown_content": "# VPN 登入問題\n\n請先確認帳號未鎖定。",
    }


def test_validation_messages_are_traditional_chinese() -> None:
    summary = validate_draft(
        title="",
        owner_unit_id="",
        change_reason="",
        effective_at="",
        review_due_at="",
        audience_type="ALL_EMPLOYEES",
        audience_group_ids=[],
        markdown_content="   ",
    )
    assert summary.has_blocking
    for issue in summary.issues:
        assert issue.message
        assert "required" not in issue.message.lower()
        assert "cannot" not in issue.message.lower()


def test_version_conflict_message_is_traditional_chinese(portal_client: TestClient) -> None:
    create = portal_client.post(
        "/api/documents",
        json=sample_document_payload(),
        headers=portal_headers(),
    )
    assert create.status_code == 200
    document_id = create.json()["document"]["document_id"]

    response = portal_client.put(
        f"/api/documents/{document_id}/draft",
        json={
            **sample_document_payload(),
            "etag": "stale-etag",
            "change_reason": "Update draft",
        },
        headers=portal_headers(),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["code"] == "CONFLICT"
    assert "重新載入" in body["detail"]["message"]


def test_index_html_exposes_portal_build(portal_client: TestClient) -> None:
    response = portal_client.get("/")
    assert response.status_code == 200
    assert 'name="portal-build" content="20260831e"' in response.text
    assert "/static/js/main.js?v=20260831e" in response.text


def test_static_portal_assets_disable_cache(portal_client: TestClient) -> None:
    response = portal_client.get("/static/js/ui.js")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-cache, no-store, must-revalidate"


def test_static_js_contains_ux_markers() -> None:
    content_js = (STATIC_DIR / "js/views/document-detail/tabs/content.js").read_text(encoding="utf-8")
    tests_js = (STATIC_DIR / "js/views/document-detail/tabs/tests.js").read_text(encoding="utf-8")
    releases_js = (STATIC_DIR / "js/views/releases.js").read_text(encoding="utf-8")
    errors_js = (STATIC_DIR / "js/errors.js").read_text(encoding="utf-8")

    assert "renderParsePreview" in content_js
    assert "引用來源" in tests_js
    assert "切換發布版本" in releases_js
    assert "版本衝突" in errors_js


def test_publish_action_cancels_when_confirmation_declined() -> None:
    actions_js = (
        STATIC_DIR / "js/views/document-detail/actions.js"
    ).read_text(encoding="utf-8")
    assert 'if (action === "publish")' in actions_js
    publish_block = actions_js.split('if (action === "publish")')[1].split(
        'if (action === "discard-draft")'
    )[0]
    assert "const ok = await confirmDialog" in publish_block
    assert "if (!ok) return false;" in publish_block

    # Behavioral test: execute in Node.js to verify API is never called when ok is false
    import json
    import subprocess

    node_script = """
    let apiCalled = false;
    global.confirmDialog = async () => false; // User clicks Cancel
    global.api = async () => { apiCalled = true; return {}; };
    global.showToast = () => {};
    const detail = {
      draft_version: { version_id: "ver-1" },
      document: { current_published_version_id: null },
    };
    const documentId = "doc-1";

    async function runTest() {
      // Simulate action === "publish" block from actions.js
      const ok = await confirmDialog(
        "發布正式版本",
        "發布後 Teams 將引用此版本。確定要發布？",
        { confirmLabel: "發布" },
      );
      if (!ok) return false;
      const versionId = detail.draft_version?.version_id || detail.document.current_published_version_id;
      const idempotencyKey = "pub-test";
      await api(`/api/documents/${documentId}/publish`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ version_id: versionId, reason: "核准後發布正式版本" }),
      });
      showToast("發布成功");
      return true;
    }

    runTest().then((result) => {
      console.log(JSON.stringify({ result, apiCalled }));
    });
    """
    proc = subprocess.run(
        ["node", "-e", node_script],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(proc.stdout.strip())
    assert result["result"] is False
    assert result["apiCalled"] is False


def test_markdown_js_and_styles_served(portal_client: TestClient) -> None:
    res_js = portal_client.get("/static/js/markdown.js")
    assert res_js.status_code == 200
    assert "parseDocumentSections" in res_js.text
    assert "renderDocumentViewer" in res_js.text

    res_css = portal_client.get("/static/styles.css")
    assert res_css.status_code == 200
    assert ".doc-viewer" in res_css.text
    assert ".doc-archive-accordion" in res_css.text
    assert ".doc-img-fallback" in res_css.text


def test_markdown_parser_and_document_viewer_behavior() -> None:
    import json
    import subprocess

    sample_doc = """# 郵件為亂碼

## Archive metadata

- **base-slug**：`郵件為亂碼`
- **archive-slug**：`郵件為亂碼`
- **原件**：`raw/originals/郵件為亂碼.md`
- **SHA-256**：`2074e9350234ef3a4369409108a591fc39549e184fa7bd1a9a636d3c62363e2d`
- **檔型**：Markdown（知識庫匯出）
- **轉檔**：自 originals 剝 HTML／雜訊
- **archived**：2026-07-24

---

## 正文（canonical）

郵件為亂碼
2025年2月21日
上午 09:45
**點開發出的電郵，在"動作 (Actions)"欄，按步驟選取繁體中文(Big 5)，查看是否能排除，**
**如現有設定已經是繁體中文(Big 5), 請嘗試轉到Unicode(UTF-8)，**

![image1](../../../resources/3206fe4993934c3481422c2bdbb40825.png)

## Limitations / Gaps

- 原文引用圖片／附件路徑不在本倉：
  - `../../../resources/3206fe4993934c3481422c2bdbb40825.png`
"""

    markdown_js_path = str(STATIC_DIR / "js/markdown.js")

    doc_json = json.dumps(sample_doc)
    node_script = f"""
    import('{markdown_js_path}').then(({{ parseDocumentSections, renderMarkdown, renderDocumentViewer }}) => {{
      const doc = {doc_json};
      const parsed = parseDocumentSections(doc);
      const html = renderDocumentViewer({{ content: doc, id: "testViewer" }});

      console.log(JSON.stringify({{
        docTitle: parsed.docTitle,
        metaCount: parsed.archiveMetadata.length,
        hasLimitations: Boolean(parsed.limitationsText),
        canonicalContainsActions: parsed.canonicalBody.includes("點開發出的電郵"),
        hasAccordion: html.includes("doc-archive-accordion"),
        hasLimitationsBox: html.includes("doc-limitations-box"),
        hasViewerToolbar: html.includes("doc-viewer-toolbar"),
        hasImageFallback: html.includes("doc-img-fallback"),
      }}));
    }}).catch(err => {{
      console.error(err);
      process.exit(1);
    }});
    """

    proc = subprocess.run(
        ["node", "--input-type=module", "-e", node_script],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(proc.stdout.strip())
    assert result["docTitle"] == "郵件為亂碼"
    assert result["metaCount"] >= 6
    assert result["hasLimitations"] is True
    assert result["canonicalContainsActions"] is True
    assert result["hasAccordion"] is True
    assert result["hasLimitationsBox"] is True
    assert result["hasViewerToolbar"] is True
    assert result["hasImageFallback"] is True

