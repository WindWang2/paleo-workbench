"""Mainline Application Entrypoint"""
from src.config import config
from src.core.logger import logger
from src.api.routes import get_health_status, get_system_info

def main():
    # Diagnostic CLI only — nothing listens on HOST:PORT (ISSUE-032); say so
    # instead of logging a server start that never happens.
    logger.info(
        f"{config.APP_NAME} v{config.VERSION} diagnostics "
        f"[Branch: {get_health_status()['branch']}] (CLI run; no server on "
        f"{config.HOST}:{config.PORT})"
    )
    print(f"Health Status: {get_health_status()}")
    print(f"System Info: {get_system_info()}")

if __name__ == "__main__":
    main()
