import logging
from os import environ

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        "knowledge_portal.api:app",
        host=environ.get("KNOWLEDGE_PORTAL_HOST", "0.0.0.0"),
        port=int(environ.get("KNOWLEDGE_PORTAL_PORT", "8090")),
        log_level=environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
