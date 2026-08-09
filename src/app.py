"""Mainline Application Entrypoint"""
from src.config import config
from src.core.logger import logger
from src.api.routes import get_health_status, get_system_info

def main():
    logger.info(f"Starting {config.APP_NAME} v{config.VERSION} on {config.HOST}:{config.PORT} [Branch: main]")
    print(f"Health Status: {get_health_status()}")
    print(f"System Info: {get_system_info()}")

if __name__ == "__main__":
    main()
