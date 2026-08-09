"""Mainline System Configuration"""
import os

class Config:
    APP_NAME: str = "Paleo-Workbench API"
    VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

config = Config()
