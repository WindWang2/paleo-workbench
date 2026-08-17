"""Mainline System Configuration"""
from __future__ import annotations

import importlib.metadata
import os


def package_version() -> str:
    try:
        return importlib.metadata.version("paleo-workbench")
    except importlib.metadata.PackageNotFoundError:
        from paleo_workbench import __version__

        return __version__


class Config:
    APP_NAME: str = "Paleo-Workbench API"
    VERSION: str = package_version()
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    HOST: str = "0.0.0.0"
    PORT: int = 8000


config = Config()
