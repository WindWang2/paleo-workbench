"""Work Package B2 — 工作区预设 / QSettings 统一迁移的契约测试。

覆盖：

- 6 个布局预设的 id / 标题 / 描述齐全，``preset_ids()`` 顺序稳定；
- ``apply_layout_preset`` 后 dock 可见性逐键符合可见性矩阵；
- ``current_preset_id`` 应用后记录、手调 dock 显隐后失效（自定义）；
- app bar「工作区」下拉 → ``workspace_preset_requested`` → shell 应用；
- ``migrate_legacy_layout_settings``：WorkstationV3 / paleo-workbench 旧键
  → (PaleoWorkbench, Workstation) 新键，迁移后旧键删除；
- 布局状态版本栅栏：未知/更新版本一律忽略走默认布局。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings
from PySide6.QtWidgets import QStackedWidget

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.layout_persistence import (
    SETTINGS_APP,
    SETTINGS_ORG,
    LayoutPersistence,
    migrate_legacy_layout_settings,
)
from paleo_workbench.ui.layout_presets import list_presets
from paleo_workbench.ui.workstation.shell import WorkstationFrame

EXPECTED_PRESET_IDS = [
    "composite_default",
    "well_interpretation",
    "seismic_interpretation",
    "well_seismic_joint",
    "integrated",
    "review",
]

#: 可见性矩阵键 → WorkstationFrame dock 属性。
_DOCK_ATTRS = {
    "nav": "nav_dock",
    "inspector": "inspector_dock",
    "agent": "agent_dock",
    "tasks": "task_dock",
    "logs": "logs_dock",
    "console": "console_dock",
    "composite_layer": "composite_layer_dock",
    "composite_input": "composite_input_dock",
    "composite_linked": "composite_linked_dock",
    "well": "well_dock",
    "seismic": "seismic_dock",
    "hub": "hub_dock",
}


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    project.resources.append(
        ResourceItem(name="A12.Las", path="wells/A12.Las", type="well_log", format="las")
    )
    project.stratigraphy.target_horizon = "D63"
    return project


def _frame(qtbot, tmp_path) -> WorkstationFrame:
    frame = WorkstationFrame(_project(tmp_path), QStackedWidget())
    qtbot.addWidget(frame)
    return frame


# --- 注册表 ------------------------------------------------------------


def test_preset_registry_ids_labels_descriptions_complete():
    presets = list_presets()
    assert [p.id for p in presets] == EXPECTED_PRESET_IDS
    for preset in presets:
        assert preset.label.strip(), f"{preset.id} 缺标题"
        assert preset.description.strip(), f"{preset.id} 缺描述"


def test_preset_ids_order_is_stable():
    assert WorkstationFrame.preset_ids() == EXPECTED_PRESET_IDS
    # 与注册表同源同序（app bar 下拉依赖该顺序）。
    assert WorkstationFrame.preset_ids() == [p.id for p in list_presets()]


# --- 应用矩阵 ----------------------------------------------------------


def test_apply_each_preset_matches_visibility_matrix(qtbot, tmp_path):
    frame = _frame(qtbot, tmp_path)
    for preset_id in EXPECTED_PRESET_IDS:
        frame.apply_layout_preset(preset_id)
        matrix = frame.layout_preset_visibility(preset_id)
        assert matrix is not None
        for key, attr in _DOCK_ATTRS.items():
            dock = getattr(frame, attr)
            assert dock.isHidden() is not matrix[key], (
                f"preset {preset_id}: dock {key} 可见性与矩阵不符"
            )
        assert frame.explorer.isHidden() is not matrix["explorer_expanded"]
        assert frame.current_preset_id == preset_id


def test_apply_unknown_preset_is_noop(qtbot, tmp_path):
    frame = _frame(qtbot, tmp_path)
    frame.apply_layout_preset("composite_default")
    before = [d.isHidden() for d in frame._shell_docks()]
    frame.apply_layout_preset("no_such_preset")
    assert [d.isHidden() for d in frame._shell_docks()] == before
    assert frame.current_preset_id == "composite_default"


# --- current_preset_id 追踪 ---------------------------------------------


def test_current_preset_id_invalidated_by_manual_dock_toggle(qtbot, tmp_path):
    frame = _frame(qtbot, tmp_path)
    assert frame.current_preset_id is None

    frame.apply_layout_preset("integrated")
    assert frame.current_preset_id == "integrated"

    # 用户手动关掉一个矩阵里可见的 dock → 布局变「自定义」。
    frame.well_dock.hide()
    assert frame.current_preset_id is None
    assert frame.app_bar.workspace_combo.currentText() == "自定义"


def test_hub_dock_toggle_does_not_invalidate_preset(qtbot, tmp_path):
    """功能页 hub 浮窗由导航管理，不属于工作区预设矩阵。"""
    frame = _frame(qtbot, tmp_path)
    frame.apply_layout_preset("composite_default")
    frame.hub_dock.show()
    frame.hub_dock.hide()  # 显隐信号不得使预设失效
    assert frame.current_preset_id == "composite_default"


# --- app bar「工作区」下拉 ----------------------------------------------


def test_app_bar_workspace_combo_drives_preset(qtbot, tmp_path):
    frame = _frame(qtbot, tmp_path)
    combo = frame.app_bar.workspace_combo
    labels = [preset.label for preset in list_presets()]
    # 首项「自定义」，其后按注册表顺序列出全部预设。
    assert combo.itemText(0) == "自定义"
    assert [combo.itemText(i) for i in range(1, combo.count())] == labels

    combo.setCurrentIndex(combo.findText("审核"))
    assert frame.current_preset_id == "review"
    assert not frame.composite_input_dock.isHidden()

    combo.setCurrentIndex(0)  # 选「自定义」本身不发预设请求
    assert frame.current_preset_id == "review"


# --- QSettings 统一迁移 --------------------------------------------------


def test_migrate_moves_legacy_window_state_and_removes_old_keys():
    legacy = QSettings("PaleoWorkbench", "WorkstationV3")
    legacy.clear()
    legacy.setValue("layout/windowState.v4", QByteArray(b"fake-state-blob"))
    legacy.setValue("layout/inspector_user_hidden", True)
    legacy.sync()
    target = QSettings(SETTINGS_ORG, SETTINGS_APP)
    target.clear()
    target.sync()

    assert migrate_legacy_layout_settings() is True

    target.sync()
    assert target.value("layout/window_state") == QByteArray(b"fake-state-blob")
    assert target.value("layout/inspector_user_hidden", False, type=bool) is True
    assert target.value("layout/state_version", 0, type=int) == 4
    legacy.sync()
    assert "layout/windowState.v4" not in legacy.allKeys()
    assert "layout/inspector_user_hidden" not in legacy.allKeys()


def test_migrate_moves_legacy_panel_layout_group():
    legacy = QSettings("PaleoWorkbench", "paleo-workbench")
    legacy.clear()
    legacy.setValue("panel_layout/mapping:bottom/floating", True)
    legacy.setValue("panel_layout/mapping:bottom/visible", False)
    legacy.setValue("panel_layout/mapping:bottom/geometry", "10,20,300,400")
    legacy.sync()
    target = QSettings(SETTINGS_ORG, SETTINGS_APP)
    target.clear()
    target.sync()

    assert migrate_legacy_layout_settings() is True

    # 键前缀不变；默认后端的 LayoutPersistence 读到迁移后的数据。
    assert LayoutPersistence().load("mapping:bottom").floating is True
    assert LayoutPersistence().load("mapping:bottom").visible is False
    legacy.sync()
    assert not any(key.startswith("panel_layout") for key in legacy.allKeys())


def test_migrate_is_noop_without_legacy_data():
    QSettings("PaleoWorkbench", "WorkstationV3").clear()
    QSettings("PaleoWorkbench", "paleo-workbench").clear()
    target = QSettings(SETTINGS_ORG, SETTINGS_APP)
    target.clear()
    target.sync()

    assert migrate_legacy_layout_settings() is False


def test_migrate_does_not_overwrite_existing_new_state():
    legacy = QSettings("PaleoWorkbench", "WorkstationV3")
    legacy.clear()
    legacy.setValue("layout/windowState.v4", QByteArray(b"legacy-blob"))
    legacy.sync()
    target = QSettings(SETTINGS_ORG, SETTINGS_APP)
    target.clear()
    target.setValue("layout/window_state", QByteArray(b"newer-blob"))
    target.sync()

    migrate_legacy_layout_settings()

    target.sync()
    assert target.value("layout/window_state") == QByteArray(b"newer-blob")


# --- 状态版本栅栏 --------------------------------------------------------


def test_restore_skips_unknown_state_version(qtbot, tmp_path, monkeypatch):
    frame = _frame(qtbot, tmp_path)
    frame._settings = QSettings(str(tmp_path / "ws.ini"), QSettings.Format.IniFormat)
    frame._settings.clear()
    restore_calls: list[object] = []
    monkeypatch.setattr(
        frame._dock_host, "restoreState", lambda data: restore_calls.append(data) or True
    )

    frame._settings.setValue("layout/window_state", QByteArray(b"blob"))
    frame._settings.setValue("layout/state_version", 99)  # 来自更新的应用
    frame._settings.sync()
    frame._restore_layout()
    assert restore_calls == []

    frame._settings.setValue("layout/state_version", 4)
    frame._settings.sync()
    frame._restore_layout()
    assert len(restore_calls) == 1
