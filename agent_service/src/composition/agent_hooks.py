"""Install Backoffice-backed builders into Agent runtime hooks."""

from __future__ import annotations

from agent_service.faq import FaqService, GovernedFaqRepository
from agent_service.runtime_hooks import (
    register_faq_service_builder,
    register_governance_builder,
    register_ops_governance_builder,
    register_pricing_builder,
)
from ai_ops_backoffice.adapters.platform_ports import (
    build_and_configure_pricing_service,
    build_governance_provider_from_rag_settings,
    build_governed_faq_domain_service,
    build_ops_governance_from_settings,
)

_installed = False


def install_agent_hooks() -> None:
    global _installed
    if _installed:
        return

    register_governance_builder(build_governance_provider_from_rag_settings)
    register_ops_governance_builder(build_ops_governance_from_settings)
    register_pricing_builder(build_and_configure_pricing_service)

    def _faq_builder(settings):  # type: ignore[no-untyped-def]
        runtime_mode = settings.faq_runtime_mode.upper()
        if runtime_mode == "GOVERNED":
            return FaqService(GovernedFaqRepository(build_governed_faq_domain_service(settings)))
        if runtime_mode != "LEGACY_JSON":
            from agent_service.faq import FaqConfigError

            raise FaqConfigError(f"Unsupported FAQ runtime mode: {runtime_mode}")
        from agent_service.faq import FaqRepository

        path = settings.faq_path or (settings.data_dir / "faq.json")
        return FaqService(FaqRepository.load(path))

    register_faq_service_builder(_faq_builder)
    _installed = True
