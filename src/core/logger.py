"""Core Logging Module"""
import logging

def setup_logger():
    logger = logging.getLogger("paleo_main")
    # Honor config.DEBUG instead of a hardcoded INFO level (ISSUE-030).
    try:
        from src.config import config

        level = logging.DEBUG if config.DEBUG else logging.INFO
    except Exception:
        level = logging.INFO
    logger.setLevel(level)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger

logger = setup_logger()
