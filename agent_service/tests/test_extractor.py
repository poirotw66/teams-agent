from __future__ import annotations

import pytest

from agent_service.contracts import ConversationMessage, Issue, IssueExtraction
from agent_service.extractor import FORBIDDEN_MISSING_INFO_TERMS, IssueExtractor
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
