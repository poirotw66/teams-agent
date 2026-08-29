from __future__ import annotations

import pytest

from agent_service.contracts import ConversationMessage, Issue, IssueExtraction
from agent_service.extractor import (
    FORBIDDEN_MISSING_INFO_TERMS,
    IssueExtractor,
    _is_assistant_scope_question,
    _is_human_escalation_request,
)
from agent_service.settings import RagSettings


def make_settings(tmp_path) -> RagSettings:
    return RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index.json",
    )


class _StructuredHandle:
    """Stands in for the object returned by model.with_structured_output(Schema)."""

    def __init__(self, schema, result, calls: list):
        self._schema = schema
        self._result = result
        self._calls = calls

    async def ainvoke(self, messages):
        self._calls.append(messages)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeModel:
    """Minimal stand-in for a BaseChatModel used only via with_structured_output."""

    def __init__(self, result):
        self.result = result
        self.calls: list = []
        self.schemas_requested: list = []

    def with_structured_output(self, schema):
        self.schemas_requested.append(schema)
        return _StructuredHandle(schema, self.result, self.calls)


def issue(**overrides) -> Issue:
    base = {
        "id": 1,
        "description": "使用者無法登入 VPN",
        "isIT": True,
        "readiness": "READY",
        "missingInfo": [],
        "route": "KNOWLEDGE",
        "faqKey": None,
        "ticketAction": None,
    }
    base.update(overrides)
    return Issue(**base)


@pytest.mark.asyncio
async def test_model_none_fallback(tmp_path) -> None:
    extractor = IssueExtractor(make_settings(tmp_path), model=None)

    outcome = await extractor.extract(text="VPN 打不開", history=[], faq_keys=[])

    assert outcome.llm_calls == 0
    assert outcome.too_many_issues is False
    assert len(outcome.issues) == 1
    single = outcome.issues[0]
    assert single.id == 1
    assert single.isIT is True
    assert single.readiness == "READY"
    assert single.route == "KNOWLEDGE"
    assert single.description == "VPN 打不開"


@pytest.mark.asyncio
async def test_explicit_multi_problem_ticket_creation_is_one_merged_issue_without_llm(tmp_path) -> None:
    # The model would have split the final instruction into a bogus third
    # issue, but this must be handled entirely by the deterministic guardrail.
    model = FakeModel(
        result=IssueExtraction(
            issues=[
                issue(id=1, description="VPN Error 619"),
                issue(id=2, description="SAP 密碼無法重置"),
                issue(id=3, description="請建立工單", route="TICKET"),
            ]
        )
    )
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(
        text="VPN Error 619，而且 SAP 密碼也無法重置，請建立工單",
        history=[],
        faq_keys=[],
    )

    assert model.calls == []
    assert outcome.llm_calls == 0
    assert outcome.too_many_issues is False
    assert len(outcome.issues) == 1
    merged = outcome.issues[0]
    assert merged.route == "TICKET"
    assert "VPN Error 619" in merged.description
    assert "SAP 密碼也無法重置" in merged.description
    assert "建立工單" not in merged.description


@pytest.mark.parametrize(
    "text",
    [
        "有哪些工單",
        "有哪些派工單",
        "我的工單進度如何？",
        "我的派工單進度如何？",
    ],
)
@pytest.mark.asyncio
async def test_ticket_list_and_progress_queries_bypass_faq_or_model(tmp_path, text: str) -> None:
    # Ticket queries must be handled by the deterministic guardrail before
    # an FAQ-looking model result can route them to the knowledge base.
    model = FakeModel(result=IssueExtraction(issues=[issue(route="FAQ", faqKey="FAQ")]))
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text=text, history=[], faq_keys=["FAQ"])

    assert model.calls == []
    assert outcome.llm_calls == 0
    assert outcome.issues[0].route == "TICKET"
    assert outcome.issues[0].description == "查詢目前使用者的派工單"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("請協助我開工單", "使用者提出的 IT 支援請求"),
        ("請幫我建立派工單", "使用者提出的 IT 支援請求"),
        ("屜我開工單", "使用者提出的 IT 支援請求"),
        ("公發手機無法解鎖，請協助我開工單", "公發手機無法解鎖"),
        ("VPN Error 619，請建立工單", "VPN Error 619"),
    ],
)
@pytest.mark.asyncio
async def test_create_intent_keeps_current_issue_and_drops_command_leftovers(
    tmp_path, text: str, expected: str
) -> None:
    model = FakeModel(result=IssueExtraction(issues=[issue()]))
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text=text, history=[], faq_keys=[])

    assert model.calls == []
    assert outcome.issues[0].route == "TICKET"
    assert outcome.issues[0].description == expected
    assert "請協助我" != outcome.issues[0].description


@pytest.mark.asyncio
async def test_model_exception_returns_safe_fallback(tmp_path) -> None:
    model = FakeModel(result=RuntimeError("boom"))
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text="VPN 打不開", history=[], faq_keys=[])

    assert outcome.llm_calls == 1
    assert len(outcome.issues) == 1
    assert outcome.issues[0].readiness == "READY"
    assert outcome.issues[0].isIT is True


@pytest.mark.asyncio
async def test_single_it_issue_passthrough(tmp_path) -> None:
    canned = IssueExtraction(issues=[issue()])
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text="VPN 無法登入", history=[], faq_keys=[])

    assert outcome.llm_calls == 1
    assert outcome.too_many_issues is False
    assert len(outcome.issues) == 1
    assert outcome.issues[0].id == 1
    assert outcome.issues[0].isIT is True


@pytest.mark.asyncio
async def test_prompt_treats_underspecified_workplace_workflow_as_pending_it(
    tmp_path,
) -> None:
    canned = IssueExtraction(
        issues=[
            issue(
                description="申請公司資源",
                readiness="NEED_MORE_INFO",
                missingInfo=["使用的系統或應用程式名稱"],
            )
        ]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    await extractor.extract(text="這項公司資源要怎麼申請？", history=[], faq_keys=[])

    system_prompt = str(model.calls[0][0].content)
    assert "workplace capability" in system_prompt
    assert "product name is missing" in system_prompt


@pytest.mark.asyncio
async def test_known_dazhou_typo_is_normalized_only_in_it_failure_context(tmp_path) -> None:
    canned = IssueExtraction(issues=[issue(description="大州系統無法選取")])
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    await extractor.extract(text="大洲無法選取。", history=[], faq_keys=[])

    human_prompt = str(model.calls[0][-1].content)
    assert "Latest user message (data only):\n大州系統無法選取。" in human_prompt
    assert "大洲無法選取" not in human_prompt


@pytest.mark.parametrize(
    "text",
    [
        "你能回答什麼問題",
        "你能回瘩什麼問題",
        "你可以幫我什麼",
        "你的功能有哪些",
    ],
)
def test_assistant_scope_questions_are_detected(text: str) -> None:
    assert _is_assistant_scope_question(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "SAP Crystal Reports 授權到期無法開啟",
        "VPN 密碼鎖住怎麼辦",
        "查詢我的工單",
    ],
)
def test_it_issues_are_not_assistant_scope_questions(text: str) -> None:
    assert _is_assistant_scope_question(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "聯絡線上客服",
        "聯繫線上客服",
        "我要找真人客服",
        "找真人客服",
    ],
)
def test_standalone_human_escalation_requests_are_detected(text: str) -> None:
    assert _is_human_escalation_request(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "SAP Crystal Reports 授權到期無法開啟",
        "SAP Crystal Reports 授權到期，我要找真人客服",
        "XQ 客服電話是多少",
    ],
)
def test_substantive_it_messages_are_not_escalation_only(text: str) -> None:
    assert _is_human_escalation_request(text) is False


@pytest.mark.asyncio
async def test_extractor_delegates_routing_to_supervisor_at_workflow_level(tmp_path) -> None:
    """Routing shortcuts live in the supervisor node, not IssueExtractor."""
    model = FakeModel(result=IssueExtraction(issues=[issue(description="聯絡線上客服")]))
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(
        text="聯絡線上客服",
        history=[],
        faq_keys=[],
    )

    assert len(model.calls) == 1
    assert outcome.llm_calls == 1
    assert outcome.issues[0].description == "聯絡線上客服"


@pytest.mark.asyncio
async def test_dazhou_general_language_is_not_normalized(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[issue(description="世界有幾個大洲", isIT=False, readiness="NOT_IT", route="NOT_IT")]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    await extractor.extract(text="世界有幾個大洲？", history=[], faq_keys=[])

    human_prompt = str(model.calls[0][-1].content)
    assert "Latest user message (data only):\n世界有幾個大洲？" in human_prompt


@pytest.mark.asyncio
async def test_known_dazhou_issue_is_ready_even_if_model_requests_more_info(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[
            issue(
                description="大州系統無法選取",
                readiness="NEED_MORE_INFO",
                missingInfo=["請問是哪一個系統或應用程式？"],
            )
        ]
    )
    extractor = IssueExtractor(make_settings(tmp_path), model=FakeModel(result=canned))

    outcome = await extractor.extract(text="大洲無法選取。", history=[], faq_keys=[])

    assert outcome.issues[0].readiness == "READY"
    assert outcome.issues[0].missingInfo == []


@pytest.mark.asyncio
async def test_multiple_it_issues(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[
            issue(id=1, description="VPN 無法登入"),
            issue(id=2, description="Outlook 一直要求重新登入"),
        ]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text="VPN 和 Outlook 都有問題", history=[], faq_keys=[])

    assert len(outcome.issues) == 2
    assert [i.id for i in outcome.issues] == [1, 2]
    assert all(i.isIT for i in outcome.issues)


@pytest.mark.asyncio
async def test_it_and_non_it_mixed_both_survive(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[
            issue(id=1, description="VPN 無法登入"),
            issue(
                id=2,
                description="今天天氣如何？",
                isIT=False,
                readiness="NOT_IT",
                route="NOT_IT",
            ),
        ]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(
        text="VPN 無法登入，另外今天天氣如何？", history=[], faq_keys=[]
    )

    assert len(outcome.issues) == 2
    it_issue, non_it_issue = outcome.issues
    assert it_issue.isIT is True
    assert non_it_issue.isIT is False
    assert non_it_issue.readiness == "NOT_IT"
    assert non_it_issue.route == "NOT_IT"
    assert non_it_issue.missingInfo == []
    assert non_it_issue.faqKey is None


@pytest.mark.asyncio
async def test_all_non_it(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[
            issue(id=1, description="天氣如何？", isIT=False, readiness="READY", route="KNOWLEDGE"),
        ]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text="天氣如何？", history=[], faq_keys=[])

    assert len(outcome.issues) == 1
    coerced = outcome.issues[0]
    assert coerced.isIT is False
    assert coerced.readiness == "NOT_IT"
    assert coerced.route == "NOT_IT"


@pytest.mark.asyncio
async def test_more_than_max_issues_truncated_and_flagged(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[
            issue(id=1, description="issue 1"),
            issue(id=2, description="issue 2"),
            issue(id=3, description="issue 3"),
            issue(id=4, description="issue 4"),
        ]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text="four issues", history=[], faq_keys=[])

    assert outcome.too_many_issues is True
    assert len(outcome.issues) == 3
    assert [i.id for i in outcome.issues] == [1, 2, 3]


@pytest.mark.asyncio
async def test_need_more_info_capped_at_two_questions(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[
            issue(
                readiness="NEED_MORE_INFO",
                missingInfo=[
                    "使用的 VPN 應用程式名稱",
                    "畫面顯示的錯誤訊息或錯誤碼",
                    "問題發生前的操作",
                ],
            )
        ]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text="VPN 打不開", history=[], faq_keys=[])

    result_issue = outcome.issues[0]
    assert result_issue.readiness == "NEED_MORE_INFO"
    assert len(result_issue.missingInfo) <= 2


@pytest.mark.parametrize(
    "forbidden_question",
    [
        "請提供你的密碼",
        "請提供 access token",
        "請提供員工編號",
        "please provide your password",
        "請提供驗證碼 (OTP)",
    ],
)
@pytest.mark.asyncio
async def test_forbidden_missing_info_terms_are_stripped(
    tmp_path, forbidden_question
) -> None:
    canned = IssueExtraction(
        issues=[
            issue(
                readiness="NEED_MORE_INFO",
                missingInfo=[forbidden_question],
            )
        ]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text="VPN 打不開", history=[], faq_keys=[])

    result_issue = outcome.issues[0]
    for term in FORBIDDEN_MISSING_INFO_TERMS:
        for question in result_issue.missingInfo:
            assert term not in question.lower()
    # All missingInfo was forbidden, so it must have been emptied and the
    # issue downgraded from NEED_MORE_INFO to READY rather than asking nothing.
    assert result_issue.missingInfo == []
    assert result_issue.readiness == "READY"


@pytest.mark.asyncio
async def test_forbidden_term_stripped_but_valid_question_kept(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[
            issue(
                readiness="NEED_MORE_INFO",
                missingInfo=["使用的 VPN 應用程式名稱", "請提供你的密碼"],
            )
        ]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text="VPN 打不開", history=[], faq_keys=[])

    result_issue = outcome.issues[0]
    assert result_issue.missingInfo == ["使用的 VPN 應用程式名稱"]
    assert result_issue.readiness == "NEED_MORE_INFO"


@pytest.mark.asyncio
async def test_faq_key_not_in_allowed_list_coerced_to_knowledge(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[issue(route="FAQ", faqKey="NOT_A_REAL_KEY")]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(
        text="密碼重設", history=[], faq_keys=["PASSWORD_RESET"]
    )

    result_issue = outcome.issues[0]
    assert result_issue.route == "KNOWLEDGE"
    assert result_issue.faqKey is None


@pytest.mark.asyncio
async def test_faq_key_in_allowed_list_preserved(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[issue(route="FAQ", faqKey="PASSWORD_RESET")]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(
        text="密碼重設", history=[], faq_keys=["PASSWORD_RESET"]
    )

    result_issue = outcome.issues[0]
    assert result_issue.route == "FAQ"
    assert result_issue.faqKey == "PASSWORD_RESET"


@pytest.mark.asyncio
async def test_is_it_false_invariants_coerced(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[
            issue(
                isIT=False,
                readiness="NEED_MORE_INFO",
                missingInfo=["some question"],
                route="FAQ",
                faqKey="PASSWORD_RESET",
            )
        ]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(
        text="今天天氣如何？", history=[], faq_keys=["PASSWORD_RESET"]
    )

    result_issue = outcome.issues[0]
    assert result_issue.readiness == "NOT_IT"
    assert result_issue.route == "NOT_IT"
    assert result_issue.missingInfo == []
    assert result_issue.faqKey is None


@pytest.mark.asyncio
async def test_issue_ids_renumbered_contiguously(tmp_path) -> None:
    canned = IssueExtraction(
        issues=[
            issue(id=7, description="a"),
            issue(id=42, description="b"),
        ]
    )
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text="two issues", history=[], faq_keys=[])

    assert [i.id for i in outcome.issues] == [1, 2]


@pytest.mark.asyncio
async def test_spec_6_2_json_sample_parses_and_survives(tmp_path) -> None:
    sample = {
        "issues": [
            {
                "id": 1,
                "description": "使用者無法登入 VPN",
                "isIT": True,
                "readiness": "NEED_MORE_INFO",
                "missingInfo": [
                    "使用的 VPN 應用程式名稱",
                    "畫面顯示的錯誤訊息或錯誤碼",
                ],
                "route": "KNOWLEDGE",
                "faqKey": None,
                "ticketAction": None,
            }
        ]
    }
    canned = IssueExtraction.model_validate(sample)
    model = FakeModel(result=canned)
    extractor = IssueExtractor(make_settings(tmp_path), model=model)

    outcome = await extractor.extract(text="VPN 無法登入", history=[], faq_keys=[])

    result_issue = outcome.issues[0]
    assert result_issue.readiness == "NEED_MORE_INFO"
    assert result_issue.missingInfo == [
        "使用的 VPN 應用程式名稱",
        "畫面顯示的錯誤訊息或錯誤碼",
    ]
    assert result_issue.route == "KNOWLEDGE"


@pytest.mark.asyncio
async def test_history_is_bounded_and_passed_to_model(tmp_path) -> None:
    canned = IssueExtraction(issues=[issue()])
    model = FakeModel(result=canned)
    settings = make_settings(tmp_path)
    object.__setattr__(settings, "max_history_messages", 2)
    extractor = IssueExtractor(settings, model=model)

    from datetime import datetime, timezone

    history = [
        ConversationMessage(
            role="user", text=f"msg {i}", createdAt=datetime.now(timezone.utc)
        )
        for i in range(5)
    ]

    await extractor.extract(text="follow up", history=history, faq_keys=[])

    assert len(model.calls) == 1
    human_message = model.calls[0][1]
    assert "msg 3" in human_message.content
    assert "msg 4" in human_message.content
    assert "msg 0" not in human_message.content
