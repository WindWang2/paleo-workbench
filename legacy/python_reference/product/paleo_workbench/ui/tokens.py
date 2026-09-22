"""Backwards-compatible re-export of design tokens.

The canonical module moved to ``paleo_workbench.tokens`` so non-UI layers
(viz hosts) can use tokens without depending on the ui package.
"""
from paleo_workbench.tokens import *  # noqa: F401,F403
