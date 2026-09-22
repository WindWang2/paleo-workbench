"""Mainline Base API Routes"""

from __future__ import annotations

import os

from src.config import package_version


def get_health_status():
    try:
        import paleo_workbench  # noqa: F401

        status = "healthy"
    except Exception:
        status = "unhealthy"
    return {
        "status": status,
        "service": "paleo-workbench",
        "branch": os.environ.get("PALEO_WORKBENCH_BRANCH", "").strip() or "unknown",
    }


def get_system_info():
    return {
        "version": package_version(),
        "environment": os.environ.get("PALEO_WORKBENCH_ENV", "production"),
    }
