#!/usr/bin/env python3
"""Re-run RAG evaluation questions and append token/cost estimates to a new CSV."""

from __future__ import annotations

import asyncio
import csv
import json
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent_service.contracts import (
    AgentRequest,
    ConversationIdentity,
    MessageContent,
    UserIdentity,
)
from agent_service.graph import RagAgent
from agent_service.retrieval import HybridIndex
from agent_service.settings import RagSettings

SOURCE_CSV = Path(
    "/Users/cfh00896102/Github/teams-agent/outputs/rag-evaluation-20260730/"
    "RAG評估結果_20260730.csv"
)
OUTPUT_DIR = Path(
    "/Users/cfh00896102/Github/teams-agent/outputs/rag-evaluation-20260731"
)
TZ = ZoneInfo("Asia/Taipei")

USAGE_COLUMNS = [
    "Input Tokens",
    "Output Tokens",
    "Total Tokens",
    "Embedding Tokens",
    "Estimated Cost USD",
    "Usage Models",
]


def load_questions(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def make_request(serial: str, question: str) -> AgentRequest:
    return AgentRequest(
        requestId=f"bu-eval-{serial}-{uuid4().hex[:12]}",
        channel="evaluation",
        conversation=ConversationIdentity(
            tenantId="local-eval",
            conversationId=f"eval-{serial}",
        ),
        user=UserIdentity(displayName="evaluator", groups=[]),
        message=MessageContent(text=question, locale="zh-TW"),
    )


async def evaluate_row(
    agent: RagAgent,
    row: dict[str, str],
) -> dict[str, str]:
    serial = row["序號"]
    question = row["問題"].strip()
    request = make_request(serial, question)
    started = time.perf_counter()
    error = ""
    status = "成功"
    http_status = "200"
    retries = "1"
    answer = ""
    citations_title = ""
    citations_url = ""
    citations_chunk = ""
    has_source = "否"
    image_count = "0"
    image_titles = ""
    trace_id = ""
    usage_fields = {
        "Input Tokens": "0",
        "Output Tokens": "0",
        "Total Tokens": "0",
        "Embedding Tokens": "0",
        "Estimated Cost USD": "",
        "Usage Models": "[]",
    }

    try:
        result = await agent.run(request)
        answer = result.answer
        trace_id = result.trace_id
        if result.citations:
            has_source = "是"
            citations_title = " | ".join(item.title for item in result.citations)
            citations_url = " | ".join(item.url or "" for item in result.citations)
            citations_chunk = " | ".join(
                item.chunkId or "" for item in result.citations
            )
        if result.images:
            image_count = str(len(result.images))
            image_titles = " | ".join(item.title for item in result.images)
        usage = result.usage
        usage_fields = {
            "Input Tokens": str(usage.input_tokens),
            "Output Tokens": str(usage.output_tokens),
            "Total Tokens": str(usage.total_tokens),
            "Embedding Tokens": str(usage.embedding_tokens),
            "Estimated Cost USD": (
                ""
                if usage.estimated_cost_usd is None
                else f"{usage.estimated_cost_usd:.8f}"
            ),
            "Usage Models": json.dumps(
                [
                    {
                        "model": item.model,
                        "input_tokens": item.input_tokens,
                        "output_tokens": item.output_tokens,
                        "total_tokens": item.total_tokens,
                        "estimated_cost_usd": item.estimated_cost_usd,
                    }
                    for item in usage.by_model
                ],
                ensure_ascii=False,
            ),
        }
    except Exception as exc:  # noqa: BLE001 - evaluation runner must continue
        status = "失敗"
        http_status = "503"
        error = str(exc)

    latency = round(time.perf_counter() - started, 3)
    tested_at = datetime.now(TZ).isoformat(timespec="seconds")
    return {
        "序號": serial,
        "問題": question,
        "RAG回答的答案": answer,
        "是否有參考來源文件": has_source,
        "來源文件": citations_title,
        "來源網址": citations_url,
        "來源Chunk ID": citations_chunk,
        "參考文件是否有誤?": "",
        "答案是否有誤?": "",
        "答案是否有幫助(1~5分)": "",
        "人工評估備註": "",
        "圖片數": image_count,
        "圖片標題": image_titles,
        "Trace ID": trace_id,
        "Request ID": request.requestId,
        "HTTP狀態": http_status,
        "測試狀態": status,
        "重試次數": retries,
        "延遲秒數": str(latency),
        "錯誤訊息": error,
        "測試時間": tested_at,
        **usage_fields,
    }


async def main() -> None:
    settings = RagSettings.from_env()
    index = HybridIndex.load(settings.index_path, settings.embedding_model)
    agent = RagAgent(settings, index)
    rows = load_questions(SOURCE_CSV)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(TZ).strftime("%Y%m%d")
    output_csv = OUTPUT_DIR / f"RAG評估結果_{stamp}.csv"
    output_summary = OUTPUT_DIR / f"RAG評估結果_{stamp}_summary.json"

    fieldnames = list(rows[0].keys())
    for column in USAGE_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)

    results: list[dict[str, str]] = []
    for row in rows:
        print(f"Evaluating #{row['序號']}: {row['問題'][:40]}...", flush=True)
        result = await evaluate_row(agent, row)
        results.append(result)
        print(
            f"  status={result['測試狀態']} tokens={result['Total Tokens']} "
            f"cost={result['Estimated Cost USD']} latency={result['延遲秒數']}s",
            flush=True,
        )

    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    successful = [row for row in results if row["測試狀態"] == "成功"]
    costs = [
        float(row["Estimated Cost USD"])
        for row in successful
        if row["Estimated Cost USD"]
    ]
    latencies = [float(row["延遲秒數"]) for row in successful]
    summary = {
        "source": str(SOURCE_CSV),
        "mode": "local-rag-agent",
        "model": settings.model,
        "embedding_model": settings.embedding_model,
        "tested_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "total": len(results),
        "successful": len(successful),
        "failed": len(results) - len(successful),
        "with_citations": sum(
            1 for row in successful if row["是否有參考來源文件"] == "是"
        ),
        "without_citations": sum(
            1 for row in successful if row["是否有參考來源文件"] != "是"
        ),
        "with_images": sum(1 for row in successful if int(row["圖片數"] or 0) > 0),
        "average_latency_seconds": (
            round(sum(latencies) / len(latencies), 3) if latencies else None
        ),
        "total_input_tokens": sum(int(row["Input Tokens"]) for row in successful),
        "total_output_tokens": sum(int(row["Output Tokens"]) for row in successful),
        "total_tokens": sum(int(row["Total Tokens"]) for row in successful),
        "total_embedding_tokens": sum(
            int(row["Embedding Tokens"]) for row in successful
        ),
        "total_estimated_cost_usd": round(sum(costs), 8) if costs else None,
        "average_estimated_cost_usd": (
            round(sum(costs) / len(costs), 8) if costs else None
        ),
        "output_csv": str(output_csv),
    }
    output_summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
