"""Composite save/restore pure helpers (Task 12) tests.

Task 12 of the free-graphics host work: ``CompositeView`` gains
save/restore for the paper layout — persisted panels are reconciled against
the live scene geometry (``reconcile_panels``), image assets are copied
into the workspace (``rewrite_image_paths``), and free-graphic records are
restored per item.

``composite_view`` imports PySide6 at module level, so these tests import
only the two module-level pure helpers. When PySide6 is unavailable (plain
``/usr/bin/python3`` / CI), the helpers are extracted from the module
source instead of importing the module; the helpers depend on nothing but
``pathlib``/``shutil``.
"""

from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

# Well Log Workstation moved out of this tree into the well-log-engine
# submodule (apps/wellplot-desktop). Put that app on sys.path so the real
# module is imported; the source-extraction fallback below covers checkouts
# where the submodule app is not importable (no PySide6 / partial checkout).
_WORKSTATION_APP = (
    Path(__file__).resolve().parents[1]
    / "well-log-engine"
    / "apps"
    / "wellplot-desktop"
)
if _WORKSTATION_APP.is_dir():
    sys.path.insert(0, str(_WORKSTATION_APP))

try:
    from well_log_workstation.composite_view import (
        reconcile_panels,
        rewrite_image_paths,
    )
except ImportError:
    # PySide6 not installed: pull the two pure functions out of the module
    # source (module-level imports of Qt never run in this path).
    def _extract_helpers() -> tuple:
        module_path = _WORKSTATION_APP / "well_log_workstation" / "composite_view.py"
        if not module_path.is_file():
            raise RuntimeError(
                f"composite_view.py not found under well-log-engine submodule "
                f"(expected {module_path}); run `git submodule update --init`"
            )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        names = {"reconcile_panels", "rewrite_image_paths"}
        body = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ]
        if len(body) != 2:
            raise RuntimeError(
                "composite_view.py pure helpers not found for source extraction"
            )
        namespace: dict = {"Path": Path, "shutil": shutil}
        module = ast.Module(body=body, type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "<composite_view helpers>", "exec"), namespace)
        return namespace["reconcile_panels"], namespace["rewrite_image_paths"]

    reconcile_panels, rewrite_image_paths = _extract_helpers()


def _panel(
    plot_id: str,
    rect_mm,
    *,
    slot: str = "main",
    source_plot_type: str = "single_well",
    render_mode: str = "live",
) -> dict:
    return {
        "plot_id": plot_id,
        "slot": slot,
        "source_plot_type": source_plot_type,
        "rect_mm": rect_mm,
        "render_mode": render_mode,
    }


def test_reconcile_panels_updates_geometry_from_scene() -> None:
    """The scene is the source of truth: live geometry overwrites the doc."""
    doc = [_panel("p1", [10.0, 10.0, 40.0, 20.0])]
    scene = [_panel("p1", [30.0, 30.0, 50.0, 25.0])]

    merged = reconcile_panels(doc, scene)

    assert len(merged) == 1
    assert merged[0]["rect_mm"] == [30.0, 30.0, 50.0, 25.0]
    assert merged[0]["plot_id"] == "p1"
    assert merged[0]["slot"] == "main"


def test_reconcile_panels_adds_scene_only_and_removes_doc_only() -> None:
    """Panels dropped from the paper disappear; new scene panels are kept."""
    doc = [
        _panel("gone", [1.0, 1.0, 2.0, 2.0]),
        _panel("kept", [5.0, 5.0, 6.0, 6.0]),
    ]
    scene = [
        _panel("kept", [7.0, 7.0, 8.0, 8.0]),
        _panel(
            "fresh",
            [9.0, 9.0, 3.0, 3.0],
            source_plot_type="fence_3d",
            render_mode="snapshot",
        ),
    ]

    merged = reconcile_panels(doc, scene)

    ids = [p["plot_id"] for p in merged]
    assert "gone" not in ids
    # Updated panels keep their doc order; brand-new ones follow after.
    assert ids.index("kept") < ids.index("fresh")
    kept = next(p for p in merged if p["plot_id"] == "kept")
    assert kept["rect_mm"] == [7.0, 7.0, 8.0, 8.0]
    fresh = next(p for p in merged if p["plot_id"] == "fresh")
    assert fresh["render_mode"] == "snapshot"
    assert fresh["source_plot_type"] == "fence_3d"


def test_rewrite_image_paths_copies_into_plot_assets(tmp_path) -> None:
    """Absolute image paths are copied under plots/assets/<plot_id>/."""
    src = tmp_path / "logo.png"
    src.write_bytes(b"fake-png")
    records = [
        {
            "kind": "image",
            "props": {"path": str(src)},
            "geometry": {"x": 1.0, "y": 1.0, "w": 2.0, "h": 2.0},
        }
    ]

    out = rewrite_image_paths(records, tmp_path, "c1")

    rel = out[0]["props"]["path"]
    assert rel.startswith("plots/assets/c1/")
    assert (tmp_path / rel).is_file()
    assert (tmp_path / rel).read_bytes() == b"fake-png"
    # The input record is never mutated.
    assert records[0]["props"]["path"] == str(src)


def test_rewrite_image_paths_leaves_non_image_and_relative_untouched(
    tmp_path,
) -> None:
    """Non-image records and already-relative paths pass through unchanged."""
    records = [
        {"kind": "text", "props": {"text": "hi", "align": "left"}, "geometry": {"x": 1.0, "y": 1.0}},
        {"kind": "image", "props": {"path": "plots/assets/c1/logo.png"}, "geometry": {"x": 1.0, "y": 1.0, "w": 2.0, "h": 2.0}},
        {"kind": "image", "props": {"path": str(tmp_path / "missing.png")}, "geometry": {"x": 1.0, "y": 1.0, "w": 2.0, "h": 2.0}},
    ]

    out = rewrite_image_paths(records, tmp_path, "c1")

    assert out[0] is records[0]  # text record passed through unchanged
    assert out[1]["props"]["path"] == "plots/assets/c1/logo.png"
    assert out[2]["props"]["path"] == str(tmp_path / "missing.png")
    assert len(out) == 3
