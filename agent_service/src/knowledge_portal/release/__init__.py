"""Release workflow skeleton (Wave 3 / P1).

Incremental extraction from ``knowledge_portal.services.release_service``.
Activation, agent reload, policy, and command bodies live in dedicated
modules; ``ReleaseService`` remains the public command facade.
"""

from __future__ import annotations

from .activation import (
    activate_release,
    deactivate_other_releases,
    mark_release_failed,
    mark_release_gate_blocked,
    persist_failed_release,
    settle_after_agent_reload,
    settle_promote_after_agent_reload,
    write_local_active_pointer,
)
from .agent_reload import notify_agent_reload
from .coordinator import (
    assert_promotable,
    compensation_target_status,
    deactivated_status,
    decide_reload_branch,
    is_allowed_status_hop,
    resolve_post_reload_status,
    restored_previous_status,
    should_compensate_reload_failure,
    should_finalize_as_active,
    should_mark_rolled_back,
    validate_status_hop,
)
from .policy import require_release_allowed
from .ports import (
    ActivationStorePort,
    AgentReloadPort,
    ReleaseGateBlockedError,
    ReleaseGateChecker,
    SourceCatalogEntry,
    SourceCatalogPort,
    SourceCatalogWriter,
    fetch_google_id_token,
)
from .promote import promote_candidate_release
from .publish import (
    collect_active_published_versions,
    publish_version,
    reindex_all_published,
    remove_document,
    unpublish_document,
)
from .queries import compare_releases, list_releases
from .rollback import rollback_release
from .sync import sync_agent_release
from .transitions import (
    ACTIVE,
    ALL_RELEASE_STATUSES,
    ALLOWED_TRANSITIONS,
    BUILDING,
    DEACTIVATABLE_STATUSES,
    DEPLOYING,
    FAILED,
    GATE_BLOCKED,
    PROMOTABLE_STATUSES,
    READY,
    RELOAD_FAILED,
    ROLLED_BACK,
    can_promote,
    can_transition,
    ensure_can_transition,
    is_deactivatable,
    is_known_status,
    promote_rejection_message,
    status_after_reload,
)

__all__ = [
    "ACTIVE",
    "ALLOWED_TRANSITIONS",
    "ALL_RELEASE_STATUSES",
    "BUILDING",
    "DEACTIVATABLE_STATUSES",
    "DEPLOYING",
    "FAILED",
    "GATE_BLOCKED",
    "PROMOTABLE_STATUSES",
    "READY",
    "RELOAD_FAILED",
    "ROLLED_BACK",
    "ActivationStorePort",
    "AgentReloadPort",
    "ReleaseGateBlockedError",
    "ReleaseGateChecker",
    "SourceCatalogEntry",
    "SourceCatalogPort",
    "SourceCatalogWriter",
    "activate_release",
    "assert_promotable",
    "can_promote",
    "can_transition",
    "collect_active_published_versions",
    "compare_releases",
    "compensation_target_status",
    "deactivate_other_releases",
    "deactivated_status",
    "decide_reload_branch",
    "ensure_can_transition",
    "fetch_google_id_token",
    "is_allowed_status_hop",
    "is_deactivatable",
    "is_known_status",
    "list_releases",
    "mark_release_failed",
    "mark_release_gate_blocked",
    "notify_agent_reload",
    "persist_failed_release",
    "promote_candidate_release",
    "promote_rejection_message",
    "publish_version",
    "reindex_all_published",
    "remove_document",
    "require_release_allowed",
    "resolve_post_reload_status",
    "restored_previous_status",
    "rollback_release",
    "settle_after_agent_reload",
    "settle_promote_after_agent_reload",
    "should_compensate_reload_failure",
    "should_finalize_as_active",
    "should_mark_rolled_back",
    "status_after_reload",
    "sync_agent_release",
    "unpublish_document",
    "validate_status_hop",
    "write_local_active_pointer",
]
