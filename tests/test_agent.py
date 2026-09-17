from teams_agent.source_links import citation_source_groups, citation_source_tenant_id
from teams_agent.text import clean_message_text


def test_clean_message_text_normalizes_whitespace() -> None:
    assert clean_message_text("  hello \n Teams  ") == "hello Teams"


def test_clean_message_text_handles_none() -> None:
    assert clean_message_text(None) == ""


def test_playground_citations_use_shared_knowledge_tenant() -> None:
    assert (
        citation_source_tenant_id(
            "playground",
            "00000000-0000-0000-0000-0000000000001",
        )
        == "default"
    )
    assert citation_source_groups(
        "playground",
        "00000000-0000-0000-0000-0000000000001",
        (),
    ) == ("grp_public",)


def test_teams_citations_preserve_tenant() -> None:
    assert citation_source_tenant_id("msteams", "enterprise-tenant") == "enterprise-tenant"
