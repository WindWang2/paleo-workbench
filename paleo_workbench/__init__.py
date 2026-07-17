"""Paleogeography map compilation workbench."""

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

__version__ = "0.1.0"

# ISS-ENV-01: prefer editable installs; fall back to checkout package roots.
ensure_geoviz_on_path()
