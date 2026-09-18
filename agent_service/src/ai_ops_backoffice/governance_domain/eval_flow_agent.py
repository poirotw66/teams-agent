"""Release-eligible Agent workflow eval harness."""

from __future__ import annotations

from typing import Any, Protocol

from platform_kernel.eval import FlowObservation

from .constants import is_allowlisted_model
from .eval_flow_unavailable import UnavailableFlowHarness


class AgentTurnExecutor(Protocol):
    """Runs one Agent turn under a candidate prompt/model binding."""

    def execute(
        self,
        *,
        template: str,
        model_id: str,
        text: str,
        history: list[dict[str, str]] | None,
    ) -> FlowObservation: ...


class AgentWorkflowFlowHarness:
    """Release-eligible harness backed by the real Agent workflow executor.

    Prefer ``runtime_factory`` so each observe builds an isolated runtime.
    A shared executor is supported for tests but must not be reused across
    concurrent eval runs.
    """

    name = "agent_workflow_v1"

    def __init__(
        self,
        executor: AgentTurnExecutor | None = None,
        *,
        runtime_factory: Any | None = None,
        model_ready: bool = True,
        fixture_metadata: dict[str, Any] | None = None,
    ) -> None:
        if executor is None and runtime_factory is None:
            raise ValueError("executor or runtime_factory is required")
        self._executor = executor
        self._runtime_factory = runtime_factory
        self._model_ready = model_ready
        self._fixture_metadata = fixture_metadata

    def reproducibility_metadata(self) -> dict[str, Any]:
        if isinstance(self._fixture_metadata, dict) and self._fixture_metadata:
            return dict(self._fixture_metadata)
        return {
            "version": "agent_workflow_v1-unspecified-fixture",
            "layer": "flowRegression",
            "knowledgeQualityAcceptance": False,
        }

    @property
    def available(self) -> bool:
        return self._model_ready

    @property
    def release_eligible(self) -> bool:
        return True

    def _observation_unavailable(self, *, model_id: str | None) -> FlowObservation:
        return FlowObservation(
            route="UNAVAILABLE",
            label="UNAVAILABLE",
            refused_injection=False,
            detail=f"model_not_bound:{model_id or 'missing'}",
            used_template_chars=0,
            model_id_used=model_id,
        )

    def _build_executor_from_runtime(self, runtime: Any) -> Any:
        from ai_ops_backoffice.ports.eval_agent import get_eval_agent_bindings

        return get_eval_agent_bindings().build_turn_executor(runtime)

    def _executor_call_kwargs(
        self,
        fn: Any,
        *,
        template: str,
        model_id: str,
        text: str,
        history: list[dict[str, str]] | None,
        setup: str | None,
    ) -> dict[str, Any]:
        import inspect

        kwargs: dict[str, Any] = {
            "template": template,
            "model_id": model_id,
            "text": text,
            "history": history,
        }
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return kwargs
        parameters = signature.parameters
        accepts_var_kw = any(
            item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()
        )
        if setup is not None and ("setup" in parameters or accepts_var_kw):
            kwargs["setup"] = setup
        return kwargs

    def observe(
        self,
        *,
        template: str,
        text: str,
        history: list[dict[str, str]] | None = None,
        model_id: str | None = None,
        setup: str | None = None,
    ) -> FlowObservation:
        if not self.available:
            return UnavailableFlowHarness().observe(
                template=template, text=text, history=history, model_id=model_id
            )
        if not is_allowlisted_model(model_id):
            return self._observation_unavailable(model_id=model_id)
        executor = self._executor
        if self._runtime_factory is not None:
            executor = self._build_executor_from_runtime(self._runtime_factory())
        assert executor is not None
        execute = executor.execute
        return execute(
            **self._executor_call_kwargs(
                execute,
                template=template,
                model_id=model_id,
                text=text,
                history=history,
                setup=setup,
            )
        )

    async def aobserve(
        self,
        *,
        template: str,
        text: str,
        history: list[dict[str, str]] | None = None,
        model_id: str | None = None,
        setup: str | None = None,
    ) -> FlowObservation:
        if not self.available:
            return UnavailableFlowHarness().observe(
                template=template, text=text, history=history, model_id=model_id
            )
        if not is_allowlisted_model(model_id):
            return self._observation_unavailable(model_id=model_id)
        # Fresh runtime per observe: candidate/baseline and concurrent evals
        # do not share conversation, handoff, or ticket mutable state.
        if self._runtime_factory is not None:
            executor = self._build_executor_from_runtime(self._runtime_factory())
            return await executor.aexecute(
                template=template,
                model_id=model_id,
                text=text,
                history=history,
                setup=setup,
            )
        assert self._executor is not None
        aexecute = getattr(self._executor, "aexecute", None)
        if callable(aexecute):
            return await aexecute(
                **self._executor_call_kwargs(
                    aexecute,
                    template=template,
                    model_id=model_id,
                    text=text,
                    history=history,
                    setup=setup,
                )
            )
        execute = self._executor.execute
        return execute(
            **self._executor_call_kwargs(
                execute,
                template=template,
                model_id=model_id,
                text=text,
                history=history,
                setup=setup,
            )
        )
