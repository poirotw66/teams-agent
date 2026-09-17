import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.settings import RagSettings
from agent_service.workflow import INITIAL_STAGE_LABEL, STAGE_LABELS


def make_settings(
    tmp_path: Path,
    token: str | None = None,
    evaluation_token: str | None = None,
) -> RagSettings:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "vpn.md").write_text(
        "# VPN 處理方式\n\nVPN 密碼被鎖時，請聯繫資訊服務窗口協助解鎖。",
        encoding="utf-8",
    )
    return RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
        min_score=0.05,
        service_token=token,
        golden_evaluation_token=evaluation_token,
    )


def test_ready_and_chat_endpoints(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        ready = client.get("/readyz")
        response = client.post(
            "/agent/chat",
            json={
                "requestId": "request-1",
                "channel": "msteams",
                "conversation": {
                    "tenantId": "tenant-1",
                    "conversationId": "conversation-1",
                },
                "user": {"entraObjectId": "user-1", "groups": []},
                "message": {
                    "text": "VPN 密碼被鎖怎麼辦？",
                    "locale": "zh-TW",
                },
            },
        )

    assert ready.status_code == 200
    assert ready.json()["chunks"] == 1
    assert response.status_code == 200
    assert "VPN 密碼被鎖" in response.json()["answer"]
    assert response.json()["citations"][0]["title"] == "VPN 處理方式"
    assert response.json()["citations"][0]["evidence"] is None
    assert "retrievalTraces" not in response.json()


def test_service_token_is_required_when_configured(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path, token="test-token"))) as client:
        rejected = client.post(
            "/retrieval/search",
            json={"query": "VPN", "groups": [], "limit": 1},
        )
        accepted = client.post(
            "/retrieval/search",
            headers={"Authorization": "Bearer test-token"},
            json={"query": "VPN", "groups": [], "limit": 1},
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200


def test_evaluation_chat_requires_distinct_capability_token(tmp_path: Path) -> None:
    payload = {
        "requestId": "evaluation-request",
        "channel": "evaluation",
        "conversation": {
            "tenantId": "tenant-1",
            "conversationId": "evaluation-conversation",
        },
        "user": {"entraObjectId": "evaluation-user", "groups": []},
        "message": {"text": "VPN 密碼被鎖怎麼辦？", "locale": "zh-TW"},
    }
    settings = make_settings(tmp_path, evaluation_token="evaluation-token")
    with TestClient(create_app(settings)) as client:
        rejected = client.post("/agent/evaluation/chat", json=payload)
        accepted = client.post(
            "/agent/evaluation/chat",
            headers={"Authorization": "Bearer evaluation-token"},
            json=payload,
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    body = accepted.json()
    evidence = body["citations"][0]["evidence"]
    assert "[chunkId=" in evidence
    assert body["retrievalTraces"][0]["trace"]["actualBackend"] == "HYBRID"
    assert body["retrievalTraces"][0]["trace"]["attempts"][0]["candidates"]
    assert body["retrievalTraces"][0]["trace"]["answerability"] == "FULL"
    assert body["retrievalTraces"][0]["trace"]["claims"][0]["chunkIds"]
    assert body["retrievalTraces"][0]["trace"]["resolvedIssueQuery"] == "VPN 密碼被鎖怎麼辦？"
    assert body["llmCallCount"] in {1, 2}


def test_evaluation_chat_is_disabled_without_capability_token(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.post("/agent/evaluation/chat", json={})

    assert response.status_code == 404


def test_regular_chat_rejects_reserved_evaluation_channel(tmp_path: Path) -> None:
    payload = {
        "requestId": "reserved-channel-request",
        "channel": "__golden_evaluation__",
        "conversation": {"tenantId": "tenant-1"},
        "user": {"entraObjectId": "user-1", "groups": []},
        "message": {"text": "VPN 密碼被鎖怎麼辦？", "locale": "zh-TW"},
    }
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.post("/agent/chat", json=payload)
        stream_response = client.post("/agent/chat/stream", json=payload)

    assert response.status_code == 400
    assert stream_response.status_code == 400


def test_evaluation_token_must_differ_from_service_token(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        token="shared-token",
        evaluation_token="shared-token",
    )

    with pytest.raises(ValueError, match="must differ"):
        create_app(settings)


def test_knowledge_backend_control_reports_unconfigured_gemini(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path, token="test-token"))) as client:
        rejected = client.get("/admin/knowledge-backend")
        status = client.get(
            "/admin/knowledge-backend",
            headers={"Authorization": "Bearer test-token"},
        )
        switched = client.put(
            "/admin/knowledge-backend",
            headers={"Authorization": "Bearer test-token"},
            json={"backend": "GEMINI_FILE_SEARCH"},
        )

    assert rejected.status_code == 401
    assert status.status_code == 200
    assert status.json()["activeBackend"] == "HYBRID"
    gemini = next(item for item in status.json()["options"] if item["id"] == "GEMINI_FILE_SEARCH")
    assert gemini["available"] is False
    assert switched.status_code == 409
    assert "GEMINI_FILE_SEARCH_STORE" in switched.json()["detail"]


def test_startup_refuses_rag_acl_requirement_without_enforcement(tmp_path: Path) -> None:
    settings = replace(
        make_settings(tmp_path),
        gemini_file_search_store="fileSearchStores/example",
        rag_require_file_search_acl=True,
        gemini_file_search_enforce_acl=False,
    )

    with (
        pytest.raises(RuntimeError, match="GEMINI_FILE_SEARCH_ENFORCE_ACL=false"),
        TestClient(create_app(settings)),
    ):
        pass


def parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, data) pairs."""
    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name = ""
        payload = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                payload = line.removeprefix("data: ")
        events.append((name, json.loads(payload)))
    return events


CHAT_PAYLOAD = {
    "requestId": "request-1",
    "channel": "msteams",
    "conversation": {"tenantId": "tenant-1", "conversationId": "conversation-1"},
    "user": {"entraObjectId": "user-1", "groups": []},
    "message": {"text": "VPN 密碼被鎖怎麼辦？", "locale": "zh-TW"},
}


def test_chat_stream_emits_stages_then_the_same_answer_as_chat(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        plain = client.post("/agent/chat", json=CHAT_PAYLOAD)
        stream_payload = {**CHAT_PAYLOAD, "requestId": "request-stream"}
        streamed = client.post("/agent/chat/stream", json=stream_payload)

    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(streamed.text)
    names = [name for name, _ in events]

    # Progress first, exactly one terminal event, and it is last.
    assert names[0] == "stage"
    assert names[-1] == "response"
    assert names.count("response") == 1
    assert "error" not in names
    assert set(names[:-1]) == {"stage"}

    stage_labels = [data["label"] for name, data in events if name == "stage"]
    assert stage_labels[0] == INITIAL_STAGE_LABEL
    # Every stage label is one the workflow actually declares.
    assert set(stage_labels[1:]) <= set(STAGE_LABELS.values())
    # Stages are emitted in graph order, without repeats.
    assert stage_labels == list(dict.fromkeys(stage_labels))

    # Both streaming and non-streaming endpoints must satisfy the contract:
    # return grounded answers with valid citations, matching metadata, and cost tracking.
    final = events[-1][1]
    assert "[S1]" in final["answer"] and "[S1]" in plain.json()["answer"]
    assert "VPN" in final["answer"] and "VPN" in plain.json()["answer"]
    assert "資訊服務窗口" in final["answer"] and "資訊服務窗口" in plain.json()["answer"]
    assert final["citations"] == plain.json()["citations"]
    assert final["feedbackEnabled"] == plain.json()["feedbackEnabled"]
    assert final.get("costComplete") is True
    assert isinstance(final.get("estimatedCostUsd"), float)


def test_chat_fails_closed_when_operational_events_cannot_persist(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        client.app.state.ops_runtime.emitter.emit_turn = AsyncMock(
            side_effect=RuntimeError("store unavailable")
        )
        response = client.post("/agent/chat", json=CHAT_PAYLOAD)

    assert response.status_code == 503
    assert "Correlation ID" in response.json()["detail"]


def test_feedback_rejects_unverifiable_provenance(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.post(
            "/feedback",
            json={
                "correlationId": "unknown-correlation",
                "conversationId": "unknown-conversation",
                "issueId": 1,
                "rating": "UP",
                "userId": "user-1",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Feedback provenance could not be verified."


def test_chat_includes_turn_cost_by_default(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.post("/agent/chat", json=CHAT_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["costComplete"] is True
    assert isinstance(body["estimatedCostUsd"], float)
    assert body["estimatedCostUsd"] >= 0
    assert isinstance(body["estimatedCostTwd"], float)
    assert body["estimatedCostTwd"] >= 0


def test_chat_omits_turn_cost_when_disabled(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), show_turn_cost=False)
    with TestClient(create_app(settings)) as client:
        response = client.post("/agent/chat", json=CHAT_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["estimatedCostUsd"] is None
    assert body["estimatedCostTwd"] is None
    assert body["costComplete"] is None


def test_playground_omits_turn_cost_by_default_but_still_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logged: list[object] = []

    def _capture(summary: object) -> None:
        logged.append(summary)

    monkeypatch.setattr("agent_service.routers.chat_support.log_request_cost", _capture)
    payload = {**CHAT_PAYLOAD, "channel": "playground"}
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.post("/agent/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["estimatedCostUsd"] is None
    assert body["estimatedCostTwd"] is None
    assert body["costComplete"] is None
    assert len(logged) == 1
    assert logged[0].estimated_cost_usd is not None


def test_playground_shows_turn_cost_when_enabled(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), show_turn_cost_playground=True)
    payload = {**CHAT_PAYLOAD, "channel": "playground"}
    with TestClient(create_app(settings)) as client:
        response = client.post("/agent/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["costComplete"] is True
    assert isinstance(body["estimatedCostUsd"], float)


def test_chat_stream_rejects_a_disallowed_tenant_before_streaming(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings = replace(settings, allowed_tenants=("tenant-allowed",))
    with TestClient(create_app(settings)) as client:
        response = client.post("/agent/chat/stream", json=CHAT_PAYLOAD)

    # Checks that run before the body starts stay real HTTP errors.
    assert response.status_code == 403
    assert not response.headers["content-type"].startswith("text/event-stream")


def test_chat_stream_requires_the_service_token_when_configured(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path, token="test-token"))) as client:
        rejected = client.post("/agent/chat/stream", json=CHAT_PAYLOAD)
        accepted = client.post(
            "/agent/chat/stream",
            headers={"Authorization": "Bearer test-token"},
            json=CHAT_PAYLOAD,
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200


def test_chat_stream_reports_a_workflow_failure_as_an_error_event(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:

        async def boom(*_args, **_kwargs):
            raise RuntimeError("knowledge backend is down")
            yield  # pragma: no cover - makes this an async generator

        app.state.workflow.stream = boom
        response = client.post("/agent/chat/stream", json=CHAT_PAYLOAD)

    # The status is already committed, so the failure arrives as an event.
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["correlationId"]
    # Spec §17: no stack trace or raw exception text reaches the caller.
    assert "knowledge backend is down" not in response.text
    assert "RuntimeError" not in response.text
