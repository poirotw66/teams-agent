"""Phase 2 human-handoff routing and presentation policy.

The handoff supervisor is model-driven: ``AgenticHandoffRouter`` classifies the
user's next action from conversation state.  Deterministic code here is limited
to summary fallback templates and offer copy — not NLU keyword routing.
"""

from __future__ import annotations

from .handoff_policy import (
    CANCELLED_MESSAGE,
    CLOSE_FORBIDDEN_MESSAGE,
    DEMO_CLOSED_MESSAGE,
    DEMO_MESSAGE_SAVED,
    DEMO_STARTED_MESSAGE,
    HANDOFF_OFFER_MESSAGE,
    SUMMARY_SUPPLEMENT_MESSAGE,
    TERMINAL_STATUSES,
    HandoffAction,
    HandoffResumeReason,
    RoutingTarget,
    authorize_handoff_action,
    available_handoff_actions,
    is_protocol_close_command,
    routing_target_for_status,
    validate_handoff_action,
)
from .handoff_router import AgenticHandoffRouter, HandoffRouteDecision
from .handoff_summary import (
    SummaryDraft,
    SummaryGenerator,
    SupplementSummaryUpdate,
    agentic_supplement_summary,
    deterministic_summary,
    generate_summary_with_fallback,
    offer_message,
    offer_message_from_summary_text,
    supplement_summary_deterministic_fallback,
)

__all__ = [
    "CANCELLED_MESSAGE",
    "CLOSE_FORBIDDEN_MESSAGE",
    "DEMO_CLOSED_MESSAGE",
    "DEMO_MESSAGE_SAVED",
    "DEMO_STARTED_MESSAGE",
    "HANDOFF_OFFER_MESSAGE",
    "SUMMARY_SUPPLEMENT_MESSAGE",
    "TERMINAL_STATUSES",
    "AgenticHandoffRouter",
    "HandoffAction",
    "HandoffResumeReason",
    "HandoffRouteDecision",
    "RoutingTarget",
    "SummaryDraft",
    "SummaryGenerator",
    "SupplementSummaryUpdate",
    "agentic_supplement_summary",
    "authorize_handoff_action",
    "available_handoff_actions",
    "deterministic_summary",
    "generate_summary_with_fallback",
    "is_protocol_close_command",
    "offer_message",
    "offer_message_from_summary_text",
    "routing_target_for_status",
    "supplement_summary_deterministic_fallback",
    "validate_handoff_action",
]
