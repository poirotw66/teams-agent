"""Standalone worker runner for AI Ops backoffice background tasks.

Allows running background workers (export sweeper, daily aggregations,
budget evaluation, retention sweeper, eval scheduler, freshness heartbeat,
and evaluation execution jobs) in a dedicated process separate from the
API HTTP server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
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
    app: Any = None,
    health_provider: Any = None,
) -> None:
    """Lightweight HTTP healthcheck server for container orchestrators.

    Provides rich status at /healthz including liveness, loop status, uptime,
    heartbeats, and dependency state (Spec 7.3, A05-T1).
    """
    start_time = time.time()
    consecutive_errors = 0

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal consecutive_errors
        try:
            line = await reader.readline()
            if line:
                is_running = not stop_event.is_set()
                status_code = 200
                status_str = "OK"

                last_hb_str: str | None = None
                tracker = None
                last_hb: datetime | None = None
                dependencies_status: dict[str, Any] = {}

                if health_provider is not None:
                    try:
                        provider_data = health_provider()
                        if isinstance(provider_data, dict):
                            dependencies_status.update(provider_data)
                    except Exception as ex:
                        consecutive_errors += 1
                        dependencies_status["provider_error"] = str(ex)
                elif app is not None and hasattr(app, "state"):
                    tracker = getattr(app.state, "freshness_tracker", None)
                    if tracker is not None:
                        last_hb = getattr(tracker, "_last_worker_heartbeat", None)
                        if last_hb is not None:
                            last_hb_str = last_hb.isoformat()
                    settings = getattr(app.state, "settings", None)
                    if settings is not None:
                        dependencies_status["store_mode"] = getattr(settings, "ops_store_mode", "UNKNOWN")
                    job_worker = getattr(app.state, "job_worker", None)
                    if job_worker is not None:
                        dependencies_status["job_worker_running"] = getattr(job_worker, "_running", False)

                is_stalled = False
                if tracker is not None and last_hb is not None:
                    stale_thresh = getattr(tracker, "_worker_stale_threshold", 600.0)
                    elapsed_hb = time.time() - last_hb.timestamp()
                    if elapsed_hb > stale_thresh:
                        is_stalled = True
                        dependencies_status["stalled"] = True
                        dependencies_status["elapsed_since_heartbeat_seconds"] = round(elapsed_hb, 1)

                if not is_running or consecutive_errors >= 10 or is_stalled:
                    status_code = 503
                    status_str = "Service Unavailable"

                body_dict = {
                    "status": "ok" if status_code == 200 else ("stalled" if is_stalled else "degraded"),
                    "worker": "ai_ops_worker",
                    "process_alive": True,
                    "loop_running": is_running,
                    "uptime_seconds": round(time.time() - start_time, 2),
                    "last_heartbeat_at": last_hb_str,
                    "consecutive_errors": consecutive_errors,
                    "dependencies": dependencies_status,
                }
                body = json.dumps(body_dict).encode("utf-8") + b"\n"
                response = (
                    f"HTTP/1.1 {status_code} {status_str}\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode("ascii") + body
                writer.write(response)
                await writer.drain()
        except Exception:
            consecutive_errors += 1
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
            tasks.append(
                asyncio.create_task(
                    _start_health_server("0.0.0.0", resolved_port, stop_event, app=app)
                )
            )
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
