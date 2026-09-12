"""Standalone worker runner for AI Ops backoffice background tasks.

Allows running background workers (export sweeper, daily aggregations,
budget evaluation, retention sweeper, eval scheduler, freshness heartbeat,
and evaluation execution jobs) in a dedicated process separate from the
API HTTP server.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .api import create_app
from .settings import BackofficeSettings

logger = logging.getLogger("ai_ops_worker")


async def _start_health_server(
    host: str,
    port: int,
    stop_event: asyncio.Event,
    *,
    on_started: Any = None,
) -> None:
    """Lightweight HTTP healthcheck server for container orchestrators."""
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if line:
                body = b'{"status":"ok","worker":"ai_ops_worker"}\n'
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                    b"Connection: close\r\n\r\n" + body
                )
                writer.write(response)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    server = await asyncio.start_server(handle_client, host, port)
    actual_port = server.sockets[0].getsockname()[1] if server.sockets else port
    logger.info("Worker health check probe listening on http://%s:%s/healthz", host, actual_port)
    if on_started is not None:
        on_started(actual_port)
    try:
        await stop_event.wait()
    finally:
        server.close()
        await server.wait_closed()


async def _run_health_file_touch(path: Path, stop_event: asyncio.Event, interval: float = 10.0) -> None:
    """Periodically touch a health check file for container liveness probes."""
    while not stop_event.is_set():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(datetime.now(timezone.utc).isoformat() + "\n", encoding="utf-8")
        except Exception:
            logger.debug("Failed to touch worker health file: %s", path, exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue


async def run_standalone_workers(
    settings: BackofficeSettings | None = None,
    *,
    health_port: int | None = None,
    health_file: Path | None = None,
) -> None:
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

    resolved_port = health_port
    if resolved_port is None:
        raw_port = os.environ.get("AI_OPS_WORKER_PORT") or os.environ.get("PORT")
        if raw_port and raw_port.isdigit():
            resolved_port = int(raw_port)

    resolved_file = health_file
    if resolved_file is None:
        raw_file = os.environ.get("AI_OPS_WORKER_HEALTH_FILE")
        if raw_file:
            resolved_file = Path(raw_file).expanduser().resolve()

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
        tasks: list[asyncio.Task] = []
        if resolved_port is not None:
            tasks.append(asyncio.create_task(_start_health_server("0.0.0.0", resolved_port, stop_event)))
        if resolved_file is not None:
            tasks.append(asyncio.create_task(_run_health_file_touch(resolved_file, stop_event)))

        logger.info("AI Ops background workers are running. Waiting for shutdown signal...")
        await stop_event.wait()
        logger.info("Shutdown signal received. Stopping workers...")
        for t in tasks:
            t.cancel()
            with suppress(asyncio.CancelledError):
                await t

    logger.info("AI Ops background workers shutdown cleanly.")


def main() -> None:
    """CLI entrypoint for standalone worker runner."""
    try:
        asyncio.run(run_standalone_workers())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()
