"""#630: catalog generator must write into this checkout, not a hardcoded home path."""

from __future__ import annotations

from pathlib import Path


def test_outdir_is_repo_local_svg_output():
    # Do not import build_catalog: the module writes catalog.json on import.
    src_path = Path(__file__).resolve().parents[1] / "build_catalog.py"
    src = src_path.read_text(encoding="utf-8")
    assert "/home/kevin/projects/paleo_project/svg_output" not in src
    assert "Path(__file__)" in src
    assert 'parent / "svg_output"' in src or "parent / 'svg_output'" in src
