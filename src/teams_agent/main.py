import asyncio
import logging
from os import environ

from .agent import agent_app


def configure_logging() -> None:
    logging.basicConfig(
        level=environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> None:
    configure_logging()
    # `App.start` owns the uvicorn lifecycle for the FastAPI instance built in
    # `teams_agent.server`, and registers `POST /api/messages` on it during
    # `initialize()`. Cloud Run injects PORT; 3978 is the local default.
    asyncio.run(agent_app.start(int(environ.get("PORT", "3978"))))


if __name__ == "__main__":
    main()
