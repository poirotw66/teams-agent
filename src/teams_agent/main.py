import asyncio
import logging
from os import environ

from .agent import agent_app, agent_settings
from .server import configure_inbound_auth


def configure_logging() -> None:
    logging.basicConfig(
        level=environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def run() -> None:
    # `App.start` owns the uvicorn lifecycle for the FastAPI instance built in
    # `teams_agent.server`, and registers `POST /api/messages` on it during
    # `initialize()`. Cloud Run injects PORT; 3978 is the local default.
    await agent_app.initialize()
    configure_inbound_auth(agent_app, agent_settings)
    await agent_app.start(int(environ.get("PORT", "3978")))


def main() -> None:
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
