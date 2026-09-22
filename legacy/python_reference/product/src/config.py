"""Mainline System Configuration"""
from __future__ import annotations

import importlib.metadata
import os


def package_version() -> str:
    try:
        return importlib.metadata.version("paleo-workbench")
    except importlib.metadata.PackageNotFoundError:
        try:
            from paleo_workbench import __version__

            return __version__
        except Exception:
            # Not installed AND the package itself is not importable (e.g.
            # src/ diagnostics run from a source tree without deps): a
            # static sentinel keeps Config importable instead of raising.
            return "0.0.0+unknown"


class Config:
    APP_NAME: str = "Paleo-Workbench API"
    VERSION: str = package_version()
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    HOST: str = "0.0.0.0"
    PORT: int = 8000


config = Config()
