from ai_ops_backoffice.services.runtime_models import runtime_models_from_ready


def test_runtime_models_follow_agent_readiness() -> None:
    catalog = runtime_models_from_ready(
        {
            "agentModel": "google_genai:gemini-3.8-flash",
            "model": "google_genai:gemini-3.1-flash-lite",
            "embeddingModel": "google_genai:gemini-embedding-2",
            "fileSearchModel": "gemini-3.5-flash-lite",
            "knowledgeMode": "HYBRID",
        }
    )

    assert catalog["available"] is True
    assert catalog["knowledgeMode"] == "HYBRID"
    assert [item["model"] for item in catalog["items"]] == [
        "google_genai:gemini-3.8-flash",
        "google_genai:gemini-3.1-flash-lite",
        "google_genai:gemini-embedding-2",
        "gemini-3.5-flash-lite",
    ]
