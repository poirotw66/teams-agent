"""Tests verifying Milestone 1 CQRS query services and command handlers."""

from __future__ import annotations

from pathlib import Path

from ai_ops_backoffice.faq_domain import (
    FaqDomainService,
    FaqPublishCommandHandler,
    InMemoryFaqRepository,
)
from ai_ops_backoffice.services.query_service import (
    BackofficeQueryService,
    BudgetQueryService,
    ConversationQueryService,
    CostQueryService,
    ExportQueryService,
    FeedbackQueryService,
    HealthQueryService,
    IssueAnalyticsQueryService,
    KnowledgeQueryService,
    OperationsQueryService,
)
from ai_ops_backoffice.settings import BackofficeSettings


def test_cqrs_query_services_exports():
    """Verify all domain query service classes are exposed as first-class domain types."""
    assert issubclass(ConversationQueryService, object)
    assert issubclass(IssueAnalyticsQueryService, object)
    assert issubclass(CostQueryService, object)
    assert issubclass(HealthQueryService, object)
    assert issubclass(BudgetQueryService, object)
    assert issubclass(FeedbackQueryService, object)
    assert issubclass(KnowledgeQueryService, object)
    assert issubclass(OperationsQueryService, object)
    assert issubclass(ExportQueryService, object)


def test_backoffice_query_service_composes_subservices(tmp_path):
    """Verify BackofficeQueryService composes all domain query sub-services."""
    data_dir = Path(__file__).resolve().parents[2] / "data"
    settings = BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="MEMORY",
        ops_store_path=tmp_path / "events",
        ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="MEMORY",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
    )
    query_svc = BackofficeQueryService(settings)

    assert isinstance(query_svc.conversations, ConversationQueryService)
    assert isinstance(query_svc.issues, IssueAnalyticsQueryService)
    assert isinstance(query_svc.costs, CostQueryService)
    assert isinstance(query_svc.health, HealthQueryService)
    assert isinstance(query_svc.budget, BudgetQueryService)
    assert isinstance(query_svc.feedback, FeedbackQueryService)
    assert isinstance(query_svc.knowledge, KnowledgeQueryService)
    assert isinstance(query_svc.operations, OperationsQueryService)
    assert isinstance(query_svc.exports, ExportQueryService)


def test_faq_domain_service_composes_publish_command_handler():
    """Verify FaqDomainService composes FaqPublishCommandHandler."""
    repo = InMemoryFaqRepository()
    faq_svc = FaqDomainService(repo)
    assert isinstance(faq_svc.publish_handler, FaqPublishCommandHandler)
