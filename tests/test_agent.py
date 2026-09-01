from teams_agent.text import clean_message_text


def test_clean_message_text_normalizes_whitespace() -> None:
    assert clean_message_text("  hello \n Teams  ") == "hello Teams"


def test_clean_message_text_handles_none() -> None:
    assert clean_message_text(None) == ""
