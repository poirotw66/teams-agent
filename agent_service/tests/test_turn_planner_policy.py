"""Tests for contextual Turn Planner activation policy."""

from __future__ import annotations

from agent_service.turn_planner_policy import should_use_turn_planner


def test_pending_clarification_activates_planner() -> None:
    assert should_use_turn_planner(
        message="公司信箱",
        pending_clarification=True,
        recent_turns=[],
        has_pending_ticket_offer=False,
    )


def test_short_follow_up_with_recent_turns_activates_planner() -> None:
    assert should_use_turn_planner(
        message="那呢？",
        pending_clarification=False,
        recent_turns=["VPN 連不上"],
        has_pending_ticket_offer=False,
    )


def test_standalone_clear_it_request_skips_planner() -> None:
    assert not should_use_turn_planner(
        message="FortiClient 出現 -455 怎麼辦？",
        pending_clarification=False,
        recent_turns=[],
        has_pending_ticket_offer=False,
    )
