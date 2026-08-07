#!/usr/bin/env python3
"""Retrieval A/B test harness (spec §18.7).

Runs the SAME evaluation set (``data/eval/retrieval_eval_set.json``) against
``HybridKnowledgeService`` (spec §8.2, the default) and, when configured,
``GeminiFileSearchKnowledgeService`` (spec §8.3, spike-only candidate), and
reports every metric spec §18.7 asks for:

    Answer Accuracy, Recall@K, Groundedness, Citation Accuracy,
    No-answer Accuracy, Error-code Accuracy, ACL Accuracy,
    Image Match Accuracy, P95 Latency, per-query cost, ops-complexity note.

This module is intentionally split into two halves:

  * A pure, dependency-free scoring layer (``EvalCase``, ``CaseRun``, the
    ``score_*`` functions, ``percentile``, ``aggregate``) that
    ``agent_service/tests/test_ab_harness.py`` unit-tests directly, with no
    network/LLM/file I/O involved.
  * An I/O layer (``run_backend``, ``main``) that loads settings, builds the
    real ``HybridKnowledgeService``/``GeminiFileSearchKnowledgeService``
    adapters, and drives them against the eval set.

Never run by pytest (it is not under ``agent_service/tests``, and even the
pure functions are imported by ``test_ab_harness.py`` by file path, not by
package name -- this file is a standalone script, not part of the
``agent_service`` package).

Usage (see docs/retrieval-ab-test-report.md for full instructions):

    cd agent_service
    .venv/bin/python ../scripts/retrieval_ab_test.py \\
        --eval-set ../data/eval/retrieval_eval_set.json \\
        --backends hybrid,gemini \\
        --output-dir ../outputs

Degrades cleanly: if GEMINI_API_KEY/GOOGLE_API_KEY or
GEMINI_FILE_SEARCH_STORE is not configured, the gemini backend is skipped
(reported as SKIPPED with a reason) and only Hybrid results are produced.
Never fabricates numbers for a backend it did not actually run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --- pure scoring layer -----------------------------------------------------
#
# Nothing below this line (down to "# --- I/O layer") touches the network,
# the filesystem, or an LLM. It only knows about plain dataclasses so
# test_ab_harness.py can exercise it in isolation.

NO_ANSWER_MARKERS = (
    "沒有足夠",
    "未提供",
    "找不到",
    "無法在知識庫",
    "目前知識庫沒有",
    "目前知識庫中沒有",
    "未命中",
    "無法提供",
    "資訊不足",
)


@dataclass(frozen=True)
class EvalCase:
    """One row of ``data/eval/retrieval_eval_set.json``."""

    id: str
    categories: tuple[str, ...]
    query: str
    expected_found: bool
    expected_source_titles: tuple[str, ...] = ()
    expected_keywords: tuple[str, ...] = ()
    expected_image_paths: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    notes: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvalCase:
        return cls(
            id=str(value["id"]),
            categories=tuple(value.get("categories", [])),
            query=str(value["query"]),
            expected_found=bool(value["expectedFound"]),
            expected_source_titles=tuple(value.get("expectedSourceTitles", [])),
            expected_keywords=tuple(value.get("expectedKeywords", [])),
            expected_image_paths=tuple(value.get("expectedImagePaths", [])),
            groups=tuple(value.get("groups", [])),
            notes=str(value.get("notes", "")),
        )


@dataclass(frozen=True)
class CaseRun:
    """The observed outcome of running one ``EvalCase`` against one backend."""

    case_id: str
    found: bool
    answer: str
    citation_titles: tuple[str, ...] = ()
    image_paths: tuple[str, ...] = ()
    retrieved_titles: tuple[str, ...] = ()
    latency_seconds: float = 0.0
    llm_calls: int = 0
    cost_usd: float | None = None
    error: str | None = None


def _looks_like_no_answer(answer: str) -> bool:
    return any(marker in answer for marker in NO_ANSWER_MARKERS)


def score_answer_accuracy(case: EvalCase, run: CaseRun) -> bool | None:
    """Spec §18.7 Answer Accuracy.

    Proxy metric (no LLM judge in this harness, on purpose -- an LLM judge
    would itself need validating and would add cost/nondeterminism to a
    report that must stay reproducible): an answerable case is correct if
    ``found`` is true AND every hand-verified keyword from the real document
    text appears in the answer. A no-answer case is scored separately by
    ``score_no_answer_accuracy``.
    """
    if not case.expected_found:
        return None
    if run.error:
        return False
    if not run.found:
        return False
    if not case.expected_keywords:
        return True
    answer_lower = run.answer.lower()
    return all(keyword.lower() in answer_lower for keyword in case.expected_keywords)


def score_recall_at_k(case: EvalCase, run: CaseRun) -> bool | None:
    """Spec §18.7 Recall@K: did retrieval surface an expected source at all."""
    if not case.expected_source_titles:
        return None
    return any(title in run.retrieved_titles for title in case.expected_source_titles)


def score_groundedness(run: CaseRun, known_titles: frozenset[str]) -> bool | None:
    """Spec §18.7 Groundedness: an answer must cite only real corpus documents.

    Not applicable to a correctly-declined no-answer case. A "found" answer
    with zero citations, or a citation naming a document that is not part of
    the known corpus, counts as ungrounded (spec §8.4: 不得編造文件).
    """
    if run.error:
        return None
    if not run.found:
        return None
    if not run.citation_titles:
        return False
    return all(title in known_titles for title in run.citation_titles)


def score_citation_accuracy(case: EvalCase, run: CaseRun) -> bool | None:
    """Spec §18.7 Citation Accuracy: citations point at the expected doc(s)."""
    if not case.expected_found or not case.expected_source_titles:
        return None
    if run.error or not run.found:
        return False
    if not run.citation_titles:
        return False
    return any(title in case.expected_source_titles for title in run.citation_titles)


def score_no_answer_accuracy(case: EvalCase, run: CaseRun) -> bool | None:
    """Spec §18.7 No-answer Accuracy: correctly declines out-of-corpus queries."""
    if case.expected_found:
        return None
    if run.error:
        return False
    return (not run.found) or _looks_like_no_answer(run.answer)


def score_error_code_accuracy(case: EvalCase, run: CaseRun) -> bool | None:
    """Spec §18.7 Error-code Accuracy.

    Reuses answer accuracy for error codes that ARE in the corpus, and
    no-answer accuracy for error codes that are deliberately NOT in the
    corpus (an "error-code-shaped" no-answer probe, e.g. an undocumented
    VPN error code -- the correct behavior is still declining to answer).
    """
    if "error_code" not in case.categories:
        return None
    if case.expected_found:
        return score_answer_accuracy(case, run)
    return score_no_answer_accuracy(case, run)


def score_acl_accuracy(case: EvalCase, run: CaseRun) -> bool | None:
    """Spec §18.7 ACL Accuracy: visibility matches the expected ACL outcome."""
    if "acl" not in case.categories:
        return None
    if run.error:
        return False
    return run.found == case.expected_found


def score_image_match_accuracy(case: EvalCase, run: CaseRun) -> bool | None:
    """Spec §18.7 Image Match Accuracy."""
    if not case.expected_image_paths:
        return None
    return any(path in run.image_paths for path in case.expected_image_paths)


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile (0 <= pct <= 1). ``None`` if empty."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _summarize(scores: list[bool | None]) -> dict[str, Any]:
    applicable = [score for score in scores if score is not None]
    passed = sum(1 for score in applicable if score)
    return {
        "applicable_cases": len(applicable),
        "passed": passed,
        "accuracy": (passed / len(applicable)) if applicable else None,
    }


def aggregate(
    cases: list[EvalCase],
    runs: dict[str, CaseRun],
    known_titles: frozenset[str],
) -> dict[str, Any]:
    """Build the full §18.7 metric table for one backend's set of ``runs``."""
    answer_scores: list[bool | None] = []
    recall_scores: list[bool | None] = []
    grounded_scores: list[bool | None] = []
    citation_scores: list[bool | None] = []
    no_answer_scores: list[bool | None] = []
    error_code_scores: list[bool | None] = []
    acl_scores: list[bool | None] = []
    image_scores: list[bool | None] = []
    latencies: list[float] = []
    costs: list[float] = []
    llm_calls: list[int] = []
    errors = 0

    for case in cases:
        run = runs.get(case.id)
        if run is None:
            continue
        answer_scores.append(score_answer_accuracy(case, run))
        recall_scores.append(score_recall_at_k(case, run))
        grounded_scores.append(score_groundedness(run, known_titles))
        citation_scores.append(score_citation_accuracy(case, run))
        no_answer_scores.append(score_no_answer_accuracy(case, run))
        error_code_scores.append(score_error_code_accuracy(case, run))
        acl_scores.append(score_acl_accuracy(case, run))
        image_scores.append(score_image_match_accuracy(case, run))
        latencies.append(run.latency_seconds)
        llm_calls.append(run.llm_calls)
        if run.cost_usd is not None:
            costs.append(run.cost_usd)
        if run.error:
            errors += 1

    return {
        "total_cases": len(cases),
        "errors": errors,
        "answer_accuracy": _summarize(answer_scores),
        "recall_at_k": _summarize(recall_scores),
        "groundedness": _summarize(grounded_scores),
        "citation_accuracy": _summarize(citation_scores),
        "no_answer_accuracy": _summarize(no_answer_scores),
        "error_code_accuracy": _summarize(error_code_scores),
        "acl_accuracy": _summarize(acl_scores),
        "image_match_accuracy": _summarize(image_scores),
        "p50_latency_seconds": percentile(latencies, 0.50),
        "p95_latency_seconds": percentile(latencies, 0.95),
        "max_latency_seconds": max(latencies) if latencies else None,
        "avg_llm_calls_per_query": (sum(llm_calls) / len(llm_calls)) if llm_calls else None,
        "avg_cost_usd_per_query": (sum(costs) / len(costs)) if costs else None,
        "total_cost_usd": sum(costs) if costs else (0.0 if not costs and not errors else None),
        "cost_complete": len(costs) == len([r for r in runs.values() if not r.error]),
    }


def load_eval_set(path: Path) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [EvalCase.from_dict(item) for item in payload["cases"]]


# --- I/O layer ---------------------------------------------------------------


async def _run_hybrid_case(
    service: Any,
    index: Any,
    settings: Any,
    case: EvalCase,
) -> CaseRun:
    from agent_service.contracts import UserContext
    from agent_service.knowledge import LlmCallCounter
    from agent_service.usage import build_usage_report

    try:
        from langchain_core.callbacks import get_usage_metadata_callback
    except ImportError:  # pragma: no cover - langchain always installed here
        get_usage_metadata_callback = None  # type: ignore[assignment]

    user_context = UserContext(groups=list(case.groups))
    counter = LlmCallCounter()

    # Raw top-K retrieval, independent of the generation/rewrite pipeline,
    # for an honest Recall@K that isn't skewed by which chunks the LLM chose
    # to cite in its final answer.
    raw_results = await asyncio.to_thread(
        index.search, case.query, settings.top_k, set(case.groups)
    )
    retrieved_titles = tuple(dict.fromkeys(result.chunk.title for result in raw_results))

    started = time.perf_counter()
    try:
        if get_usage_metadata_callback is not None:
            with get_usage_metadata_callback() as usage_callback:
                result = await service.search(
                    case.query, user_context, call_counter=counter
                )
            usage = build_usage_report(usage_callback.usage_metadata)
            cost = usage.estimated_cost_usd
        else:  # pragma: no cover
            result = await service.search(case.query, user_context, call_counter=counter)
            cost = None
    except Exception as exc:  # noqa: BLE001 - harness must keep going
        latency = time.perf_counter() - started
        return CaseRun(
            case_id=case.id,
            found=False,
            answer="",
            retrieved_titles=retrieved_titles,
            latency_seconds=latency,
            llm_calls=counter.count,
            error=str(exc),
        )
    latency = time.perf_counter() - started

    return CaseRun(
        case_id=case.id,
        found=result.found,
        answer=result.answer,
        citation_titles=tuple(dict.fromkeys(source.title for source in result.sources)),
        image_paths=tuple(image.path for image in result.images),
        retrieved_titles=retrieved_titles,
        latency_seconds=latency,
        llm_calls=counter.count,
        cost_usd=cost,
    )


async def _run_gemini_case(service: Any, case: EvalCase) -> CaseRun:
    from agent_service.contracts import UserContext

    user_context = UserContext(groups=list(case.groups))
    started = time.perf_counter()
    try:
        result = await service.search(case.query, user_context)
    except Exception as exc:  # noqa: BLE001 - harness must keep going
        latency = time.perf_counter() - started
        return CaseRun(
            case_id=case.id,
            found=False,
            answer="",
            latency_seconds=latency,
            error=str(exc),
        )
    latency = time.perf_counter() - started
    citation_titles = tuple(dict.fromkeys(source.title for source in result.sources))

    return CaseRun(
        case_id=case.id,
        found=result.found,
        answer=result.answer,
        citation_titles=citation_titles,
        # The File Search spike does not expose raw top-K separately from
        # the grounded answer (spec §8.3 scope), so citations are used as a
        # best-effort Recall@K proxy -- documented as a known limitation in
        # docs/retrieval-ab-test-report.md, not silently treated as exact.
        retrieved_titles=citation_titles,
        image_paths=(),  # spike does not map images (spec §8.3/gemini_file_search.py)
        latency_seconds=latency,
        llm_calls=1,
        cost_usd=None,  # google-genai usage_metadata not surfaced by the spike adapter
    )


def _corpus_titles(settings: Any) -> frozenset[str]:
    from agent_service.documents import load_source_chunks

    chunks = load_source_chunks(settings.data_dir, settings.chunk_size, settings.chunk_overlap)
    return frozenset(chunk.title for chunk in chunks)


def _build_hybrid_service(settings: Any, index: Any) -> Any:
    from agent_service.knowledge import HybridKnowledgeService
    from langchain.chat_models import init_chat_model

    model = init_chat_model(settings.model) if settings.model else None
    return HybridKnowledgeService(settings, index, model)


def _bare_model_id(model: str | None) -> str | None:
    """Strip a LangChain provider prefix: "google_genai:gemini-x" -> "gemini-x"."""
    if not model:
        return None
    return model.split(":", 1)[1] if ":" in model else model


def _try_build_gemini_service(settings: Any) -> tuple[Any | None, str | None]:
    """Returns (service, skip_reason). Never raises -- degrades cleanly."""
    if not settings.gemini_file_search_store:
        return None, "GEMINI_FILE_SEARCH_STORE is not configured (settings.py)."
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        return None, "Neither GEMINI_API_KEY nor GOOGLE_API_KEY is set in the environment."
    try:
        from agent_service.gemini_file_search import GeminiFileSearchKnowledgeService
    except ImportError as exc:
        return None, f"google-genai SDK not installed ({exc}). Run: uv sync --extra spike"
    try:
        service = GeminiFileSearchKnowledgeService(
            api_key=None,
            file_search_store=settings.gemini_file_search_store,
            # settings.model is LangChain-flavoured ("google_genai:gemini-x"),
            # but google-genai wants the bare model id. Stripping the provider
            # prefix also keeps both backends on the SAME model, without which
            # the §18.7 comparison would not be like-for-like.
            model=_bare_model_id(settings.model) or "gemini-2.5-flash",
            top_k=settings.top_k,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"Failed to construct GeminiFileSearchKnowledgeService: {exc}"
    return service, None


async def run_backend(
    backend: str,
    cases: list[EvalCase],
    settings: Any,
    index: Any,
) -> tuple[dict[str, CaseRun], str | None]:
    """Runs every case against ``backend``. Returns (runs, skip_reason)."""
    if backend == "hybrid":
        service = _build_hybrid_service(settings, index)
        runs: dict[str, CaseRun] = {}
        for case in cases:
            print(f"  [hybrid] {case.id}: {case.query[:40]}...", flush=True)
            runs[case.id] = await _run_hybrid_case(service, index, settings, case)
        return runs, None

    if backend == "gemini":
        service, skip_reason = _try_build_gemini_service(settings)
        if service is None:
            return {}, skip_reason
        runs = {}
        for case in cases:
            print(f"  [gemini] {case.id}: {case.query[:40]}...", flush=True)
            runs[case.id] = await _run_gemini_case(service, case)
        return runs, None

    raise ValueError(f"Unknown backend: {backend!r}")


def _format_summary(backend: str, report: dict[str, Any]) -> str:
    def _pct(entry: dict[str, Any]) -> str:
        accuracy = entry["accuracy"]
        if accuracy is None:
            return "N/A (0 applicable cases)"
        return f"{accuracy * 100:.1f}% ({entry['passed']}/{entry['applicable_cases']})"

    lines = [
        f"=== {backend.upper()} ===",
        f"Total cases run: {report['total_cases']} (errors: {report['errors']})",
        f"Answer Accuracy:        {_pct(report['answer_accuracy'])}",
        f"Recall@K:                {_pct(report['recall_at_k'])}",
        f"Groundedness:            {_pct(report['groundedness'])}",
        f"Citation Accuracy:       {_pct(report['citation_accuracy'])}",
        f"No-answer Accuracy:      {_pct(report['no_answer_accuracy'])}",
        f"Error-code Accuracy:     {_pct(report['error_code_accuracy'])}",
        f"ACL Accuracy:            {_pct(report['acl_accuracy'])}",
        f"Image Match Accuracy:    {_pct(report['image_match_accuracy'])}",
        f"P50 Latency (s):         {report['p50_latency_seconds']}",
        f"P95 Latency (s):         {report['p95_latency_seconds']}",
        f"Avg LLM calls/query:     {report['avg_llm_calls_per_query']}",
        f"Avg cost/query (USD):    {report['avg_cost_usd_per_query']}",
        (
            f"Total cost (USD):        {report['total_cost_usd']} "
            f"(complete: {report['cost_complete']})"
        ),
    ]
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "eval" / "retrieval_eval_set.json",
    )
    parser.add_argument(
        "--backends",
        default="hybrid,gemini",
        help="Comma-separated subset of {hybrid,gemini}. gemini is skipped "
        "automatically (not an error) if it is not configured.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "outputs",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only run the first N cases (cost control while iterating).",
    )
    return parser.parse_args(argv)


async def _main_async(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # agent_service must be importable. If this script is invoked with the
    # repo-root .venv instead of agent_service/.venv, `agent_service` is a
    # namespace package pointing at the wrong directory (see
    # docs/retrieval-ab-test-report.md "How to run") -- fail loudly instead
    # of silently reporting bogus results.
    try:
        from agent_service.retrieval import HybridIndex
        from agent_service.settings import RagSettings
    except ImportError as exc:
        print(
            "error: could not import agent_service. Run this script with "
            "agent_service/.venv/bin/python, not the repo-root venv.\n"
            f"  ({exc})",
            file=sys.stderr,
        )
        return 2

    cases = load_eval_set(args.eval_set)
    if args.limit:
        cases = cases[: args.limit]

    settings = RagSettings.from_env()
    if not settings.index_path.exists():
        print(f"error: RAG index not found at {settings.index_path}.", file=sys.stderr)
        print("Build it first: cd agent_service && .venv/bin/rag-index", file=sys.stderr)
        return 2
    index = HybridIndex.load(settings.index_path, settings.embedding_model)
    known_titles = _corpus_titles(settings)

    requested_backends = [b.strip() for b in args.backends.split(",") if b.strip()]

    reports: dict[str, Any] = {}
    raw_runs: dict[str, dict[str, CaseRun]] = {}
    for backend in requested_backends:
        print(f"Running backend: {backend} ({len(cases)} cases)...")
        runs, skip_reason = await run_backend(backend, cases, settings, index)
        if skip_reason:
            print(f"  SKIPPED: {skip_reason}")
            reports[backend] = {"skipped": True, "reason": skip_reason}
            continue
        raw_runs[backend] = runs
        report = aggregate(cases, runs, known_titles)
        reports[backend] = report
        print(_format_summary(backend, report))
        print()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / f"retrieval-ab-test-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    artifact = {
        "generated_at_utc": timestamp,
        "eval_set": str(args.eval_set),
        "case_count": len(cases),
        "model": settings.model,
        "embedding_model": settings.embedding_model,
        "top_k": settings.top_k,
        "min_score": settings.min_score,
        "reports": reports,
        "case_runs": {
            backend: {
                case_id: {
                    "found": run.found,
                    "answer_preview": run.answer[:200],
                    "citation_titles": list(run.citation_titles),
                    "image_paths": list(run.image_paths),
                    "retrieved_titles": list(run.retrieved_titles),
                    "latency_seconds": run.latency_seconds,
                    "llm_calls": run.llm_calls,
                    "cost_usd": run.cost_usd,
                    "error": run.error,
                }
                for case_id, run in runs.items()
            }
            for backend, runs in raw_runs.items()
        },
    }
    results_path = output_dir / "results.json"
    results_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {results_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
