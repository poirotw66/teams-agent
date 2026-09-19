"""Payload and HTML builders for Teams Adapter source routes."""

from __future__ import annotations

import html
from typing import Any
from urllib.parse import quote

_VIEWER_LOGIN_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>知識庫來源存取驗證</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f5f5f5;
      margin: 0;
      padding: 48px 16px;
      display: flex;
      justify-content: center;
    }}
    .card {{
      max-width: 480px;
      width: 100%;
      background: #ffffff;
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.06);
      padding: 32px;
      box-sizing: border-box;
    }}
    h2 {{
      margin-top: 0;
      color: #242424;
      font-size: 20px;
    }}
    p {{
      color: #616161;
      line-height: 1.6;
      font-size: 14px;
    }}
    .callout {{
      background: #f0f4ff;
      border-left: 4px solid #5b5fc7;
      padding: 12px 16px;
      border-radius: 4px;
      font-size: 13px;
      color: #242424;
      margin: 20px 0;
      line-height: 1.5;
    }}
    .sso-btn {{
      display: block;
      width: 100%;
      box-sizing: border-box;
      text-align: center;
      text-decoration: none;
      background: #0078d4;
      color: #ffffff;
      border-radius: 4px;
      padding: 12px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s ease;
      margin-bottom: 20px;
    }}
    .sso-btn:hover {{
      background: #106ebe;
    }}
    .divider {{
      display: flex;
      align-items: center;
      text-align: center;
      margin: 20px 0;
      color: #8a8886;
      font-size: 12px;
    }}
    .divider::before, .divider::after {{
      content: "";
      flex: 1;
      border-bottom: 1px solid #e0e0e0;
    }}
    .divider:not(:empty)::before {{
      margin-right: .75em;
    }}
    .divider:not(:empty)::after {{
      margin-left: .75em;
    }}
    label {{
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: #242424;
      margin-bottom: 8px;
    }}
    input[type=text] {{
      width: 100%;
      box-sizing: border-box;
      padding: 10px 12px;
      border: 1px solid #c8c8c8;
      border-radius: 4px;
      font-size: 14px;
      margin-bottom: 20px;
    }}
    input[type=text]:focus {{
      outline: none;
      border-color: #5b5fc7;
      box-shadow: 0 0 0 2px rgba(91,95,199,0.2);
    }}
    button {{
      width: 100%;
      background: #5b5fc7;
      color: #ffffff;
      border: none;
      border-radius: 4px;
      padding: 12px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s ease;
    }}
    button:hover {{
      background: #4f52b2;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h2>知識庫來源文件存取驗證</h2>
    <p>為了維護企業資訊安全，存取引用來源文件需透過企業單一登入 (SSO) 或經由授權閘道完成身分確認。</p>
    <div class="callout">
      <strong>存取說明</strong><br />
      引用來源文件受企業授權與存取控制保護。請使用您的 Microsoft 365 / 公司帳號完成登入，或使用經授權核發的檢視憑證。
    </div>
    <a href="/sources/auth/login?redirect_url={escaped_redirect}" class="sso-btn">使用 Microsoft 365 / 公司帳號登入 (SSO)</a>
    <div class="divider">或使用檢視憑證驗證</div>
    <form method="POST" action="/sources/login">
      <input type="hidden" name="redirect_url" value="{escaped_redirect}" />
      <label for="token">檢視憑證 (Viewer Token)：</label>
      <input type="text" id="token" name="token" placeholder="請輸入或貼上有效的 Viewer Token" required />
      <button type="submit">驗證身分並開啟文件</button>
    </form>
  </div>
</body>
</html>
"""


def preview_evidence(payload: dict[str, Any]) -> str:
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    return str(evidence.get("excerpt") or "")


def fallback_preview_markdown(payload: dict[str, Any]) -> str:
    title = str(payload.get("title") or "引用來源")
    excerpt = preview_evidence(payload) or "目前沒有可顯示的引用內容。"
    return f"# {title}\n\n## 已索引引用片段\n\n{excerpt}"


def build_viewer_login_page_html(redirect_url: str) -> str:
    """Traditional Chinese viewer login / SSO landing page."""
    escaped_redirect = html.escape(redirect_url)
    return _VIEWER_LOGIN_PAGE_TEMPLATE.format(escaped_redirect=escaped_redirect)


def build_entra_authorize_url(
    *,
    tenant_id: str,
    client_id: str,
    callback_url: str,
    state_param: str,
    nonce: str,
) -> str:
    return (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
        f"?client_id={quote(client_id)}"
        f"&response_type=code"
        f"&redirect_uri={quote(callback_url)}"
        f"&response_mode=query"
        f"&scope=openid%20profile%20email"
        f"&state={quote(state_param)}"
        f"&nonce={quote(nonce)}"
    )


def citation_html_response_headers() -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; "
            "img-src 'self' https:; base-uri 'none'; form-action 'none'"
        ),
        "X-Content-Type-Options": "nosniff",
    }
