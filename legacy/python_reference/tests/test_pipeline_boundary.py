from __future__ import annotations

import ast
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1] / "paleo_workbench" / "pipeline"


def test_pipeline_modules_do_not_import_ui():
    forbidden = "paleo_workbench.ui"
    for path in PIPELINE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden), path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden), path
