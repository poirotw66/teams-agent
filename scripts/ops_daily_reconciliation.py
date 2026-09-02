#!/usr/bin/env python3
"""Run daily AI Ops reconciliation checks against the configured event store.

Usage:
    cd agent_service
    uv run python ../scripts/ops_daily_reconciliation.py --days 30 --preset 30d

Exit code is non-zero when any reconciliation check fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent_service" / "src"))

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.services.reconciliation import (
    reconcile_costs_summary,
    reconcile_issues_summary,
    reconcile_operations_summary,
)
from ai_ops_backoffice.settings import BackofficeSettings


async def run(days: int, preset: str | None) -> int:
    settings = BackofficeSettings.from_env()
    query_service = BackofficeQueryService(settings)
    actor = ActorContext(
        user_id="ops.reconciliation",
        display_name="Ops Reconciliation",
        role="SYSTEM_ADMIN",
        owner_unit_ids=(settings.default_owner_unit_id,),
    )
    kwargs = {"days": days, "preset": preset}
    results = {
        "operations_summary": await reconcile_operations_summary(query_service, actor, **kwargs),
        "costs_summary": await reconcile_costs_summary(query_service, actor, **kwargs),
        "issues_summary": await reconcile_issues_summary(query_service, actor, **kwargs),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))
    failed = [name for name, payload in results.items() if not payload["allMatch"]]
    if failed:
        print(f"FAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("All reconciliation checks passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AI Ops daily reconciliation checks.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--preset", default="30d")
    args = parser.parse_args()
    return asyncio.run(run(days=args.days, preset=args.preset))


if __name__ == "__main__":
    raise SystemExit(main())
