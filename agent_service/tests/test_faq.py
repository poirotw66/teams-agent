import json
from pathlib import Path

import pytest

from agent_service.contracts import FaqEntry
from agent_service.faq import FaqConfigError, FaqRepository, FaqService
from agent_service.settings import RagSettings


def _write_faq(tmp_path: Path, payload) -> Path:
    path = tmp_path / "faq.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_faq_hit_returns_entry(tmp_path: Path) -> None:
    path = _write_faq(
        tmp_path,
        {
            "faqs": [
                {
                    "id": "FAQ_001",
                    "faqKey": "PASSWORD_RESET",
                    "enabled": True,
                    "answer": "請至密碼管理入口進行密碼重設。",
                }
            ]
        },
    )
    service = FaqService(FaqRepository.load(path))

    entry = service.get("PASSWORD_RESET")

    assert entry is not None
    assert entry.faqKey == "PASSWORD_RESET"
    assert entry.answer == "請至密碼管理入口進行密碼重設。"


def test_faq_miss_unknown_key_returns_none(tmp_path: Path) -> None:
    path = _write_faq(
        tmp_path,
        {"faqs": [{"id": "FAQ_001", "faqKey": "PASSWORD_RESET", "answer": "x"}]},
    )
    service = FaqService(FaqRepository.load(path))

    assert service.get("SOME_UNKNOWN_KEY") is None


def test_disabled_faq_returns_none(tmp_path: Path) -> None:
    path = _write_faq(
        tmp_path,
        {
            "faqs": [
                {"id": "FAQ_001", "faqKey": "VPN_INSTALL", "enabled": False, "answer": "x"}
            ]
        },
    )
    service = FaqService(FaqRepository.load(path))

    assert service.get("VPN_INSTALL") is None


def test_available_keys_excludes_disabled(tmp_path: Path) -> None:
    path = _write_faq(
        tmp_path,
        {
            "faqs": [
                {"id": "FAQ_001", "faqKey": "A", "enabled": True, "answer": "x"},
                {"id": "FAQ_002", "faqKey": "B", "enabled": False, "answer": "y"},
                {"id": "FAQ_003", "faqKey": "C", "enabled": True, "answer": "z"},
            ]
        },
    )
    service = FaqService(FaqRepository.load(path))

    assert sorted(service.available_keys()) == ["A", "C"]


def test_answer_returned_verbatim_not_rewritten(tmp_path: Path) -> None:
    answer_text = "請至公司密碼管理入口進行密碼重設。  換行也保留\n第二行"
    path = _write_faq(
        tmp_path,
        {"faqs": [{"id": "FAQ_001", "faqKey": "PASSWORD_RESET", "answer": answer_text}]},
    )
    service = FaqService(FaqRepository.load(path))

    entry = service.get("PASSWORD_RESET")

    assert entry is not None
    assert entry.answer == answer_text


def test_bare_list_shape_supported(tmp_path: Path) -> None:
    path = _write_faq(
        tmp_path,
        [{"id": "FAQ_001", "faqKey": "IT_CONTACT", "answer": "聯繫窗口資訊。"}],
    )
    service = FaqService(FaqRepository.load(path))

    entry = service.get("IT_CONTACT")

    assert entry is not None
    assert entry.answer == "聯繫窗口資訊。"


def test_duplicate_faq_key_raises_config_error(tmp_path: Path) -> None:
    path = _write_faq(
        tmp_path,
        {
            "faqs": [
                {"id": "FAQ_001", "faqKey": "PASSWORD_RESET", "answer": "x"},
                {"id": "FAQ_002", "faqKey": "PASSWORD_RESET", "answer": "y"},
            ]
        },
    )

    with pytest.raises(FaqConfigError):
        FaqRepository.load(path)


def test_malformed_json_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "faq.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(FaqConfigError):
        FaqRepository.load(path)


def test_malformed_shape_raises_config_error(tmp_path: Path) -> None:
    path = _write_faq(tmp_path, {"unexpected": "shape"})

    with pytest.raises(FaqConfigError):
        FaqRepository.load(path)


def test_malformed_entry_raises_config_error(tmp_path: Path) -> None:
    path = _write_faq(tmp_path, {"faqs": [{"id": "FAQ_001"}]})  # missing faqKey/answer

    with pytest.raises(FaqConfigError):
        FaqRepository.load(path)


def test_missing_file_yields_empty_service(tmp_path: Path) -> None:
    missing_path = tmp_path / "does-not-exist.json"

    service = FaqService(FaqRepository.load(missing_path))

    assert service.get("ANYTHING") is None
    assert service.available_keys() == []


def test_faq_service_does_not_call_llm_or_rewrite(tmp_path: Path) -> None:
    # Pure lookup contract: the returned FaqEntry is exactly what was configured,
    # with no additional processing (no LLM calls are made anywhere in this
    # module -- there is nothing here capable of making one).
    original_answer = "固定答案，不應被改寫。"
    path = _write_faq(
        tmp_path,
        {"faqs": [{"id": "FAQ_001", "faqKey": "FIXED_KEY", "answer": original_answer}]},
    )
    service = FaqService(FaqRepository.load(path))

    first = service.get("FIXED_KEY")
    second = service.get("FIXED_KEY")

    assert first is not None and second is not None
    assert first.answer == second.answer == original_answer


def test_real_faq_json_loads_and_parses() -> None:
    real_path = Path(__file__).resolve().parents[2] / "data" / "faq.json"

    repository = FaqRepository.load(real_path)

    assert len(repository.entries) > 0
    for entry in repository.entries:
        assert isinstance(entry, FaqEntry)
        assert entry.faqKey
        assert entry.answer


def test_real_faq_json_has_a_disabled_entry() -> None:
    real_path = Path(__file__).resolve().parents[2] / "data" / "faq.json"

    repository = FaqRepository.load(real_path)

    assert any(not entry.enabled for entry in repository.entries)


def test_from_settings_uses_faq_path(tmp_path: Path) -> None:
    path = _write_faq(
        tmp_path,
        {"faqs": [{"id": "FAQ_001", "faqKey": "IT_CONTACT", "answer": "聯繫窗口。"}]},
    )
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
        faq_path=path,
    )

    service = FaqService.from_settings(settings)

    assert service.get("IT_CONTACT") is not None


def test_from_settings_falls_back_to_data_dir_faq_json(tmp_path: Path) -> None:
    _write_faq(
        tmp_path,
        {"faqs": [{"id": "FAQ_001", "faqKey": "IT_CONTACT", "answer": "聯繫窗口。"}]},
    )
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
        faq_path=None,
    )

    service = FaqService.from_settings(settings)

    assert service.get("IT_CONTACT") is not None
