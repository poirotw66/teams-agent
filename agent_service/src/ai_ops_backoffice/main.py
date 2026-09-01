import logging
from os import environ

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        "ai_ops_backoffice.api:app",
        host=environ.get("AI_OPS_BACKOFFICE_HOST", "0.0.0.0"),
        port=int(environ.get("AI_OPS_BACKOFFICE_PORT", "8092")),
        log_level=environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
