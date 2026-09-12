"""Standalone worker runner for AI Ops backoffice background tasks.

Allows running background workers (export sweeper, daily aggregations,
budget evaluation, retention sweeper, eval scheduler, freshness heartbeat,
and evaluation execution jobs) in a dedicated process separate from the
API HTTP server.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .api import create_app
from .settings import BackofficeSettings

logger = logging.getLogger("ai_ops_worker")


async def run_standalone_workers(settings: BackofficeSettings | None = None) -> None:
    """Run all AI Ops background workers until cancelled or terminated."""
    resolved_settings = settings or BackofficeSettings.from_env()
    # Force workers_enabled=True in the dedicated worker process
    if not resolved_settings.workers_enabled:
        resolved_settings = BackofficeSettings(
            **{**resolved_settings.__dict__, "workers_enabled": True}
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )
    logger.info("Initializing AI Ops dedicated background worker process...")

    app = create_app(resolved_settings)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            # In non-UNIX environments or threads, signal handler may not be supported
            pass

    logger.info("Entering background worker lifespan...")
    async with app.router.lifespan_context(app):
        logger.info("AI Ops background workers are running. Waiting for shutdown signal...")
        await stop_event.wait()
        logger.info("Shutdown signal received. Stopping workers...")

    logger.info("AI Ops background workers shutdown cleanly.")


def main() -> None:
    """CLI entrypoint for standalone worker runner."""
    try:
        asyncio.run(run_standalone_workers())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()
