"""Unavailable / fail-closed prompt eval harness."""

from __future__ import annotations

from platform_kernel.eval import FlowObservation


class UnavailableFlowHarness:
    """Marks real-flow incomplete when no executable model/harness is bound."""

    name = "unavailable"

    @property
    def available(self) -> bool:
        return False

    @property
    def release_eligible(self) -> bool:
        return False

    def observe(
        self,
        *,
        template: str,
        text: str,
        history: list[dict[str, str]] | None = None,
        model_id: str | None = None,
    ) -> FlowObservation:
        _ = template, text, history, model_id
        return FlowObservation(
            route="UNAVAILABLE",
            label="UNAVAILABLE",
            refused_injection=False,
            detail="model_unavailable",
            used_template_chars=0,
        )
