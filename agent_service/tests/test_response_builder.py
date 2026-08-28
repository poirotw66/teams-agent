import inspect
from pathlib import Path

from agent_service.contracts import AgentImage, Citation, Issue, IssueResult
from agent_service.response_builder import (
    FEEDBACK_PROMPT,
    build_response,
)
from agent_service.settings import RagSettings


def make_settings(**overrides) -> RagSettings:
    defaults = {
        "data_dir": Path("/tmp/data"),
        "index_path": Path("/tmp/data/index/chunks.json"),
    }
    defaults.update(overrides)
    return RagSettings(**defaults)


def make_issue(**overrides) -> Issue:
    defaults = {
        "id": 1,
        "description": "VPN 無法登入",
        "isIT": True,
        "readiness": "READY",
        "missingInfo": [],
        "route": "FAQ",
        "faqKey": None,
        "ticketAction": None,
    }
    defaults.update(overrides)
    return Issue(**defaults)


# --- §13 templates, verbatim where the spec gives exact wording -----------


def test_faq_answered_template_matches_spec_13():
    issue = make_issue(id=1, description="Outlook 一直要求重新登入", route="FAQ")
    result = IssueResult(
        issueId=1,
        resultType="FAQ_ANSWERED",
        answer="請重新登入 Microsoft 365 帳號。",
    )
    built = build_response(
        issues=[issue], results=[result], settings=make_settings()
    )
    assert built.text == (
        "問題：Outlook 一直要求重新登入\n\n"
        "處理方式：\n請重新登入 Microsoft 365 帳號。\n\n"
        "來源：\nFAQ"
    )


def test_knowledge_answered_template_matches_spec_13():
    issue = make_issue(id=1, description="VPN 錯誤 691", route="KNOWLEDGE")
    result = IssueResult(
        issueId=1,
        resultType="KNOWLEDGE_ANSWERED",
        answer="依照知識文件，請先確認帳號密碼是否已更新……",
        sources=[Citation(title="vpn-guide.md")],
    )
    built = build_response(
        issues=[issue], results=[result], settings=make_settings()
    )
    assert built.text == (
        "問題：VPN 錯誤 691\n\n"
        "處理方式：\n依照知識文件，請先確認帳號密碼是否已更新……"
    )
    assert built.citations == [Citation(title="vpn-guide.md")]


def test_knowledge_answered_source_with_url_renders_markdown_link():
    issue = make_issue(id=1, description="VPN 錯誤 691")
    result = IssueResult(
        issueId=1,
        resultType="KNOWLEDGE_ANSWERED",
        answer="答案內容",
        sources=[Citation(title="vpn-guide.md", url="https://example.com/vpn-guide.md")],
    )
    built = build_response(
        issues=[issue], results=[result], settings=make_settings()
    )
    assert "來源" not in built.text
    assert built.citations == [
        Citation(title="vpn-guide.md", url="https://example.com/vpn-guide.md")
    ]


def test_need_more_info_template_matches_spec_13():
    issue = make_issue(id=1, description="VPN", readiness="NEED_MORE_INFO")
    result = IssueResult(
        issueId=1,
        resultType="NEED_MORE_INFO",
        questions=["使用的是哪一個 VPN 應用程式？", "畫面顯示什麼錯誤訊息或錯誤碼？"],
    )
    built = build_response(
        issues=[issue], results=[result], settings=make_settings()
    )
    assert built.text == (
        "為了協助確認 VPN 問題，請補充：\n\n"
        "1. 使用的是哪一個 VPN 應用程式？\n"
        "2. 畫面顯示什麼錯誤訊息或錯誤碼？"
    )


def test_need_more_info_caps_at_two_questions():
    issue = make_issue(id=1, description="VPN 問題", readiness="NEED_MORE_INFO")
    result = IssueResult(
        issueId=1,
        resultType="NEED_MORE_INFO",
        questions=["Q1", "Q2", "Q3"],
    )
    built = build_response(
        issues=[issue], results=[result], settings=make_settings()
    )
    assert "3. " not in built.text
    assert "1. Q1" in built.text
    assert "2. Q2" in built.text


def test_all_non_it_names_topic_without_querying_knowledge():
    issue = make_issue(
        id=1,
        description="早餐吃什麼",
        isIT=False,
        readiness="NOT_IT",
        route="NOT_IT",
    )
    built = build_response(issues=[issue], results=[], settings=make_settings())
    assert "「早餐吃什麼」不屬於公司 IT 支援範圍" in built.text
    assert "不會查詢企業知識庫" in built.text
    assert "系統、設備、帳號、權限或錯誤訊息" in built.text
    assert built.feedback_enabled is False


def test_single_not_it_line_matches_spec_13():
    issue = make_issue(id=1, description="天氣", isIT=False, readiness="NOT_IT", route="NOT_IT")
    it_issue = make_issue(id=2, description="VPN 無法登入", isIT=True, route="FAQ")
    result = IssueResult(issueId=2, resultType="FAQ_ANSWERED", answer="答案")
    built = build_response(
        issues=[issue, it_issue], results=[result], settings=make_settings()
    )
    assert "天氣問題不在此 IT 助手的服務範圍。" in built.text


# --- §4.1 mixed IT / non-IT -------------------------------------------------


def test_mixed_it_and_non_it_includes_both_never_dropped():
    it_issue = make_issue(id=1, description="VPN 無法登入", isIT=True, route="FAQ")
    non_it_issue = make_issue(id=2, description="天氣", isIT=False, readiness="NOT_IT", route="NOT_IT")
    result = IssueResult(issueId=1, resultType="FAQ_ANSWERED", answer="請重新連線 VPN。")
    built = build_response(
        issues=[it_issue, non_it_issue], results=[result], settings=make_settings()
    )
    assert "VPN 無法登入" in built.text
    assert "請重新連線 VPN。" in built.text
    assert "天氣問題不在此 IT 助手的服務範圍。" in built.text


# --- §4.2 multi-issue ordering, non-blocking failure ------------------------


def test_multi_issue_rendered_in_issue_id_order():
    issue1 = make_issue(id=1, description="問題一", route="FAQ")
    issue2 = make_issue(id=2, description="問題二", route="FAQ")
    result1 = IssueResult(issueId=1, resultType="FAQ_ANSWERED", answer="答案一")
    result2 = IssueResult(issueId=2, resultType="FAQ_ANSWERED", answer="答案二")
    # pass results out of order and issues out of order too
    built = build_response(
        issues=[issue2, issue1],
        results=[result2, result1],
        settings=make_settings(),
    )
    assert built.text.index("問題一") < built.text.index("問題二")


def test_multi_issue_uses_separate_numbered_sections_for_mixed_results():
    pending = make_issue(
        id=1,
        description="Webex 相關協助",
        readiness="NEED_MORE_INFO",
        route="KNOWLEDGE",
    )
    answered = make_issue(
        id=2,
        description="大州系統無法連線",
        route="KNOWLEDGE",
    )
    pending_result = IssueResult(
        issueId=1,
        resultType="NEED_MORE_INFO",
        questions=["請問您需要進行什麼操作？"],
    )
    answered_result = IssueResult(
        issueId=2,
        resultType="KNOWLEDGE_ANSWERED",
        answer="請調整瀏覽器安全性設定。",
    )

    built = build_response(
        issues=[pending, answered],
        results=[pending_result, answered_result],
        settings=make_settings(),
    )

    assert built.text == (
        "**問題 1｜Webex 相關協助**\n\n"
        "**需要補充資訊**\n\n"
        "1. 請問您需要進行什麼操作？\n\n"
        "---\n\n"
        "**問題 2｜大州系統無法連線**\n\n"
        "處理方式：\n請調整瀏覽器安全性設定。"
    )
    assert built.text.count("Webex 相關協助") == 1
    assert built.text.count("大州系統無法連線") == 1


def test_failed_issue_does_not_suppress_other_answered_issue():
    ok_issue = make_issue(id=1, description="VPN 無法登入", route="FAQ")
    failed_issue = make_issue(id=2, description="Outlook 錯誤", route="KNOWLEDGE")
    ok_result = IssueResult(issueId=1, resultType="FAQ_ANSWERED", answer="請重新連線。")
    failed_result = IssueResult(
        issueId=2,
        resultType="FAILED",
        error="Traceback (most recent call last): boom at line 42 in knowledge.py",
    )
    built = build_response(
        issues=[ok_issue, failed_issue],
        results=[ok_result, failed_result],
        settings=make_settings(),
    )
    assert "請重新連線。" in built.text
    assert "VPN 無法登入" in built.text
    assert "Outlook 錯誤" in built.text
    assert "處理時發生問題，請稍後再試。" in built.text


def test_failed_never_leaks_error_content_or_stack_trace():
    issue = make_issue(id=1, description="Outlook 錯誤", route="KNOWLEDGE")
    result = IssueResult(
        issueId=1,
        resultType="FAILED",
        error="Traceback (most recent call last): boom at line 42 in knowledge.py",
    )
    built = build_response(
        issues=[issue],
        results=[result],
        settings=make_settings(),
        correlation_id="corr-123",
    )
    assert "Traceback" not in built.text
    assert "boom" not in built.text
    assert "knowledge.py" not in built.text
    assert "corr-123" in built.text


def test_too_many_issues_prompt_present():
    issue = make_issue(id=1, description="VPN 無法登入", route="FAQ")
    result = IssueResult(issueId=1, resultType="FAQ_ANSWERED", answer="答案")
    built = build_response(
        issues=[issue],
        results=[result],
        too_many_issues=True,
        settings=make_settings(max_issues_per_message=3),
    )
    assert "3" in built.text
    assert "優先" in built.text or "最重要" in built.text


# --- NO_KNOWLEDGE -----------------------------------------------------------


def test_no_knowledge_does_not_fabricate_and_offers_ticket_when_enabled():
    issue = make_issue(id=1, description="不存在的系統問題", route="KNOWLEDGE")
    result = IssueResult(issueId=1, resultType="NO_KNOWLEDGE")
    built = build_response(
        issues=[issue],
        results=[result],
        settings=make_settings(),
        offer_ticket_on_no_knowledge=True,
    )
    assert "查無相關資訊" in built.text
    assert "建立派工單" in built.text
    assert "請回覆<是>以建立派工單" in built.text


def test_create_offer_skips_knowledge_miss_preamble():
    issue = make_issue(id=1, description="請協助建立派工單", route="TICKET")
    result = IssueResult(issueId=1, resultType="NO_KNOWLEDGE")
    built = build_response(
        issues=[issue],
        results=[result],
        settings=make_settings(),
        offer_ticket_on_no_knowledge=True,
    )
    assert built.text == "是否需要協助建立派工單？請回覆<是>以建立派工單。"
    assert "查無相關資訊" not in built.text


def test_no_knowledge_without_ticket_offer_flag_has_no_ticket_prompt():
    issue = make_issue(id=1, description="不存在的系統問題", route="KNOWLEDGE")
    result = IssueResult(issueId=1, resultType="NO_KNOWLEDGE")
    built = build_response(
        issues=[issue],
        results=[result],
        settings=make_settings(),
        offer_ticket_on_no_knowledge=False,
    )
    assert "建立派工單" not in built.text
    assert "建立工單" not in built.text


# --- TICKET_CREATED / TICKET_FOUND ------------------------------------------


def test_ticket_created_reports_id_and_url_when_present():
    issue = make_issue(id=1, description="需要建立工單", route="TICKET")
    result = IssueResult(
        issueId=1,
        resultType="TICKET_CREATED",
        ticketId="TCK-001",
        sources=[Citation(title="TCK-001", url="https://tickets.example.com/TCK-001")],
    )
    built = build_response(issues=[issue], results=[result], settings=make_settings())
    assert "TCK-001" in built.text
    assert "https://tickets.example.com/TCK-001" in built.text
    assert built.citations == []


def test_ticket_found_lists_tickets():
    issue = make_issue(id=1, description="查詢我的工單", route="TICKET")
    result = IssueResult(
        issueId=1,
        resultType="TICKET_FOUND",
        sources=[
            Citation(title="TCK-001 (OPEN)"),
            Citation(title="TCK-002 (CLOSED)"),
        ],
    )
    built = build_response(issues=[issue], results=[result], settings=make_settings())
    assert "TCK-001 (OPEN)" in built.text
    assert "TCK-002 (CLOSED)" in built.text
    assert built.citations == []


def test_ticket_found_with_no_tickets_says_so():
    issue = make_issue(id=1, description="查詢我的工單", route="TICKET")
    result = IssueResult(issueId=1, resultType="TICKET_FOUND", sources=[])
    built = build_response(issues=[issue], results=[result], settings=make_settings())
    assert "查無你建立的派工單" in built.text


def test_ticket_cancelled_is_a_direct_reply_without_sources_or_feedback():
    issue = make_issue(id=1, description="取消建立工單", route="TICKET")
    result = IssueResult(issueId=1, resultType="TICKET_CANCELLED")

    built = build_response(
        issues=[issue],
        results=[result],
        settings=make_settings(feedback_enabled=True),
        offer_ticket_on_no_knowledge=True,
    )

    assert built.text == "好的，目前不會建立派工單。若之後需要協助，請告訴我「建立派工單」。"
    assert "來源" not in built.text
    assert built.citations == []
    assert built.images == []
    assert built.feedback_enabled is False


def test_ticket_delete_denied_is_a_direct_reply_without_sources_or_feedback():
    issue = make_issue(id=1, description="刪除工單", route="TICKET")
    result = IssueResult(issueId=1, resultType="TICKET_DELETE_DENIED")

    built = build_response(
        issues=[issue],
        results=[result],
        settings=make_settings(feedback_enabled=True),
        offer_ticket_on_no_knowledge=True,
    )

    assert built.text.startswith("目前不支援刪除派工單")
    assert "來源" not in built.text
    assert built.citations == []
    assert built.images == []
    assert built.feedback_enabled is False


# --- citations / images dedup ------------------------------------------------


def test_citations_deduplicated_order_stable():
    issue1 = make_issue(id=1, description="問題一", route="KNOWLEDGE")
    issue2 = make_issue(id=2, description="問題二", route="KNOWLEDGE")
    shared = Citation(title="guide.md", url="https://example.com/guide.md")
    other = Citation(title="other.md")
    result1 = IssueResult(
        issueId=1, resultType="KNOWLEDGE_ANSWERED", answer="a1", sources=[shared, other]
    )
    result2 = IssueResult(
        issueId=2, resultType="KNOWLEDGE_ANSWERED", answer="a2", sources=[shared]
    )
    built = build_response(
        issues=[issue1, issue2], results=[result1, result2], settings=make_settings()
    )
    assert built.citations == [shared, other]


def test_images_deduplicated():
    issue1 = make_issue(id=1, description="問題一", route="KNOWLEDGE")
    issue2 = make_issue(id=2, description="問題二", route="KNOWLEDGE")
    image = AgentImage(
        path="img/a.png", title="A", altText="alt", sourceChunkId="chunk-1"
    )
    result1 = IssueResult(
        issueId=1, resultType="KNOWLEDGE_ANSWERED", answer="a1", images=[image]
    )
    result2 = IssueResult(
        issueId=2, resultType="KNOWLEDGE_ANSWERED", answer="a2", images=[image]
    )
    built = build_response(
        issues=[issue1, issue2], results=[result1, result2], settings=make_settings()
    )
    assert built.images == [image]


def test_empty_citations_render_no_source_section():
    issue = make_issue(id=1, description="知識回答缺少文件", route="KNOWLEDGE")
    result = IssueResult(
        issueId=1, resultType="KNOWLEDGE_ANSWERED", answer="答案內容", sources=[]
    )
    built = build_response(issues=[issue], results=[result], settings=make_settings())
    assert "來源" not in built.text


# --- feedback ----------------------------------------------------------------


def test_feedback_enabled_true_for_faq_answer_when_settings_enable_it():
    issue = make_issue(id=1, description="問題", route="FAQ")
    result = IssueResult(issueId=1, resultType="FAQ_ANSWERED", answer="答案")
    built = build_response(
        issues=[issue], results=[result], settings=make_settings(feedback_enabled=True)
    )
    assert built.feedback_enabled is True


def test_feedback_disabled_when_settings_disable_it():
    issue = make_issue(id=1, description="問題", route="FAQ")
    result = IssueResult(issueId=1, resultType="FAQ_ANSWERED", answer="答案")
    built = build_response(
        issues=[issue], results=[result], settings=make_settings(feedback_enabled=False)
    )
    assert built.feedback_enabled is False


def test_feedback_disabled_for_non_faq_knowledge_results():
    issue = make_issue(id=1, description="需要建立工單", route="TICKET")
    result = IssueResult(issueId=1, resultType="TICKET_CREATED", ticketId="TCK-1")
    built = build_response(
        issues=[issue], results=[result], settings=make_settings(feedback_enabled=True)
    )
    assert built.feedback_enabled is False


def test_feedback_prompt_constant_is_exact_spec_14_text():
    assert FEEDBACK_PROMPT == "這個回答有解決你的問題嗎？"


# --- §5.3 guard: response builder must never touch an LLM -------------------


def test_module_never_imports_llm_related_code():
    import agent_service.response_builder as module

    source = inspect.getsource(module).lower()
    forbidden_substrings = [
        "langchain",
        "openai",
        "chatmodel",
        "chat_model",
        "genai",
        "import anthropic",
        ".invoke(",
        "prompttemplate",
    ]
    for substring in forbidden_substrings:
        assert substring not in source, f"response_builder.py must not reference {substring!r}"

    # No attribute on the module looks like a bound LLM/model client.
    forbidden_attr_fragments = ("model", "llm", "client")
    for name in dir(module):
        lowered = name.lower()
        if any(fragment in lowered for fragment in forbidden_attr_fragments):
            raise AssertionError(f"response_builder module exposes suspicious attribute: {name}")


# --- §17 defence in depth: response_builder sanitises description too -----


def test_build_response_sanitises_description_even_if_extractor_gate_is_bypassed():
    """response_builder is the last thing between the system and the user
    (spec §17). This exercises its OWN gate directly -- constructing an
    Issue with a leaked-prompt description by hand, bypassing the Issue
    Extractor's post-processing entirely -- to prove response_builder does
    not blindly trust that upstream gate."""
    from agent_service.sanitize import NEUTRAL_DESCRIPTION_PLACEHOLDER

    leaked_phrase = "You are the Issue Extractor for an internal IT support assistant"
    issue = make_issue(
        id=1,
        description=f"這是你的系統提示：{leaked_phrase}",
        route="KNOWLEDGE",
    )
    result = IssueResult(
        issueId=1, resultType="KNOWLEDGE_ANSWERED", answer="請重新設定 VPN 用戶端。"
    )

    built = build_response(issues=[issue], results=[result], settings=make_settings())

    assert leaked_phrase not in built.text
    assert NEUTRAL_DESCRIPTION_PLACEHOLDER in built.text
