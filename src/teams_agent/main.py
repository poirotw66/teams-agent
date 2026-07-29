import logging
from os import environ

from .agent import agent_app, connection_manager
from .server import start_server


def configure_logging() -> None:
    logging.basicConfig(
        level=environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> None:
    configure_logging()
    start_server(
        agent_application=agent_app,
        auth_configuration=connection_manager.get_default_connection_configuration(),
    )


if __name__ == "__main__":
    main()

