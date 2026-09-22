#!/usr/bin/env python
"""Offscreen visual QA for the workstation composite document.

Builds a real project with wells/resources, opens the PaleoWorkbenchWindow,
creates a geological vector layer with features, exercises the composite UI
(toolbar, layer manager, identify results, status bar), and dumps PNG
screenshots at 1366×768 and 1920×1080 plus dialog shots.

Run:
    QT_QPA_PLATFORM=offscreen python scripts/visual_qa_composite.py --out /tmp/qa
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _project(tmp: Path):
    from paleo_workbench.project.domain import WellEntity
    from paleo_workbench.project.models import ProjectDocument, ResourceItem

    project = ProjectDocument.new("Visual QA 工区", region="HZ26")
    project.meta.project_root = str(tmp)
    project.coordinate.project_crs = "EPSG:4326 / WGS84"
    for name, x, y in (("A12", 113.52, 21.31), ("B7", 113.61, 21.24), ("C3", 113.44, 21.18)):
        project.wells.append(WellEntity(name=name, surface_x=x, surface_y=y, project_x=x, project_y=y))
    project.resources.extend(
        [
            ResourceItem(name="A12.Las", path="wells/A12.Las", type="well_log", format="las"),
            ResourceItem(name="D63.dat", path="horizons/D63.dat", type="horizon", format="dat"),
        ]
    )
    project.stratigraphy.target_horizon = "D63"
    return project


def _populate_composite(window):
    from paleo_workbench.mapping.vector_layer import VectorFeature

    composite = window.app_shell.workstation.composite
    controller = composite.edit_controller
    faults = controller.create_layer("断层线", "line", template="fault")
    controller.start_editing()
    faults.edit_session.add_feature(
        VectorFeature(
            "f1",
            {"type": "LineString", "coordinates": [[113.40, 21.15], [113.55, 21.30], [113.68, 21.38]]},
            {"name": "F1", "fault_type": "正断层", "confidence": "高", "strike": 45.0},
        )
    )
    controller.save_edits()
    facies = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(facies.id)
    controller.start_editing()
    facies.edit_session.add_feature(
        VectorFeature(
            "facies-1",
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [113.44, 21.16],
                        [113.60, 21.16],
                        [113.62, 21.26],
                        [113.46, 21.28],
                        [113.44, 21.16],
                    ]
                ],
            },
            {"facies": "三角洲", "lithology": "砂岩", "confidence": "中", "horizon": "D63"},
        )
    )
    controller.save_edits()
    composite._sync_composition()
    return composite


def _grab(widget, path: Path) -> None:
    import PySide6.QtGui as QtGui

    pixmap = QtGui.QPixmap(widget.size())
    widget.render(pixmap)
    pixmap.save(str(path))
    print(f"wrote {path} ({widget.width()}x{widget.height()})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str, default="/tmp/paleo-visual-qa")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    import tempfile

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="paleo-qa-"))

    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow(project=_project(tmp))
    window.show()
    app.processEvents()

    composite = _populate_composite(window)

    # 1920×1080：综合编修默认布局。
    window.resize(1920, 1080)
    app.processEvents()
    QTimer.singleShot(120, lambda: app.processEvents())
    app.processEvents()
    _grab(window, out / "composite_1920.png")

    # 识别结果面板 + 状态栏。
    composite._identify_with_results((113.52, 21.25))
    app.processEvents()
    _grab(window, out / "composite_1920_identify.png")

    # 图层属性对话框（legacy 符号系统路径 + 标注 tab）。
    layer_id = composite.edit_controller.active_layer_id
    from PySide6.QtWidgets import QDialog

    dialog_opened = {}

    class _DialogShot(QTimer):
        pass

    # 打开对话框后截图（非阻塞：直接构建 dialog 而不 exec）。
    from paleo_workbench.ui.workstation.composite_document import _LayerPropertiesAdapter
    from paleo_workbench.ui.map_layer_properties import MapLayerPropertiesDialog
    from paleo_workbench.ui.workstation.composite_editing import schema_fields

    controller = composite.edit_controller
    layer = controller.active_layer
    adapter = _LayerPropertiesAdapter(layer, opacity=0.85, metadata={"geometry_kind": "polygon"})
    fields = tuple(f.name for f in schema_fields(controller.layer_schema(layer.id)))
    dialog = MapLayerPropertiesDialog(
        adapter, style=dict(layer.style), parent=window, features=(), fields=fields
    )
    dialog.resize(560, 480)
    dialog.show()
    app.processEvents()
    _grab(dialog, out / "layer_properties_1920.png")
    for index in range(dialog.tabs.count()):
        if dialog.tabs.tabText(index) == "Labels":
            dialog.tabs.setCurrentIndex(index)
    app.processEvents()
    _grab(dialog, out / "layer_properties_labels.png")
    dialog.hide()

    # 属性表。
    from paleo_workbench.ui.workstation.composite_attribute_table import (
        CompositeAttributeTableDialog,
    )

    table = CompositeAttributeTableDialog(controller, layer_id, parent=window)
    table.resize(760, 420)
    table.show()
    app.processEvents()
    _grab(table, out / "attribute_table.png")
    table.hide()

    # 捕捉设置。
    from paleo_workbench.ui.workstation.composite_panels import SnappingSettingsDialog

    snap_dialog = SnappingSettingsDialog(controller, parent=window)
    snap_dialog.resize(620, 420)
    snap_dialog.show()
    app.processEvents()
    _grab(snap_dialog, out / "snapping_settings.png")
    snap_dialog.hide()

    # 1366×768：窄屏（检查器响应式隐藏后画布空间）。
    composite.identify_results.set_results(())
    window.resize(1366, 768)
    app.processEvents()
    QTimer.singleShot(80, lambda: None)
    app.processEvents()
    _grab(window, out / "composite_1366.png")

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
