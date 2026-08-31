from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPointF, QPoint, QRect, Qt
from PySide6.QtGui import QMouseEvent, QShortcut
from PySide6.QtWidgets import QApplication

from paleo_workbench.ui import app_shell as app_shell_module
from paleo_workbench.ui.app_shell import (
    _SIDEBAR_FLOAT_KEY,
    AppShell,
    PAGE_INDEX_DATA,
)
from paleo_workbench.ui import tokens
from paleo_workbench.ui.sidebar import (
    SIDEBAR_DEFAULT_WIDTH,
    SIDEBAR_MAX_WIDTH,
    SIDEBAR_MIN_WIDTH,
)
from paleo_workbench.project.models import (
    ExportArtifact,
    PaleoMapDocument,
    ProjectDocument,
    ResourceItem,
)


def test_app_shell_assembles_all_zones(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.menu_bar is not None
    assert not hasattr(shell, "header_toolbar")
    assert shell.menu_bar.search_box.objectName() == "SearchBox"
    assert shell.icon_rail is not None
    assert shell.sidebar is not None
    assert shell.page_stack is not None
    assert shell.status_bar is not None


def test_app_shell_has_eleven_pages(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    # 11 pages: 井位地图 absorbed into the Data page as a collapsible panel.
    assert shell.page_stack.count() == 11


def test_app_shell_default_page_is_zero(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.currentIndex() == 0


def test_app_shell_icon_rail_switches_page(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.icon_rail.nav_buttons[4].click()
    assert shell.page_stack.currentIndex() == 4
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[4]


def test_app_shell_geological_modeling_3d_page_navigation(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    # Click 11th button (index 10: 井震联合)
    shell.icon_rail.nav_buttons[10].click()
    assert shell.page_stack.currentIndex() == 10
    geomodel_page = shell.page_stack.widget(10)
    assert geomodel_page.objectName() == "GeologicalModeling3DPage"
    assert geomodel_page.model_tree is not None
    assert geomodel_page.gl_widget is not None
    assert geomodel_page.btn_run is not None


def test_app_shell_hides_sidebar_on_data_page_and_restores_on_navigation(qtbot):
    """#1047: the sidebar keeps user state across page switches.

    It used to be unconditionally hidden on every navigation; now visible
    stays visible, a user collapse survives switches, and context updates
    continue in both cases.
    """
    shell = AppShell()
    qtbot.addWidget(shell)

    shell.icon_rail.nav_buttons[1].click()
    assert shell.page_stack.currentIndex() == PAGE_INDEX_DATA
    # page switch must NOT forcibly hide the sidebar anymore
    assert not shell.sidebar.isHidden()

    # user collapse survives navigation
    shell.sidebar.toggle_collapse()
    assert shell.sidebar.is_collapsed is True
    shell.icon_rail.nav_buttons[0].click()
    shell.icon_rail.nav_buttons[1].click()
    assert shell.sidebar.is_collapsed is True

    # expanding again also survives
    shell.sidebar.toggle_collapse()
    assert shell.sidebar.is_collapsed is False
    shell.icon_rail.nav_buttons[0].click()
    assert shell.sidebar.is_collapsed is False
    assert not shell.sidebar.isHidden()



def test_app_shell_data_sidebar_receives_resource_counts(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    resources = [
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
        )
    ]
    artifacts = [
        ExportArtifact(
            linked_id="map_1",
            format="PDF",
            output_path="/tmp/map.pdf",
        )
    ]

    shell.update_data_page({}, resources, artifacts)

    texts = "\n".join(label.text() for label in shell.sidebar._content_labels)
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[0]
    assert "项目总览" in texts
    assert "资源 1" not in texts
    assert "阅读器: empty" not in texts


def test_app_shell_switching_to_data_renders_cached_context(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    resources = [
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
        )
    ]
    artifacts = [
        ExportArtifact(
            linked_id="map_1",
            format="PDF",
            output_path="/tmp/map.pdf",
        )
    ]

    shell.update_data_page({}, resources, artifacts)
    shell.icon_rail.nav_buttons[1].click()

    texts = "\n".join(label.text() for label in shell.sidebar._content_labels)
    assert "资源 1" in texts
    assert "成果 1" in texts
    assert "异常 0" in texts
    assert "阅读器: empty" in texts


def test_app_shell_set_project_name(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.set_project_name("HZ26 Demo")
    assert "HZ26 Demo" in shell.status_bar.status_label.text()


def test_app_shell_mapping_sidebar_shows_map_name(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    docs = [
        PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2"),
    ]
    shell.update_mapping_page(docs)
    shell.icon_rail.nav_buttons[8].click()

    texts = "\n".join(label.text() for label in shell.sidebar._content_labels)
    assert shell.sidebar.context_label.text() == "编图"
    assert "图件: ZJ2 Map" in texts
    assert "层位: ZJ2" in texts
    assert "状态: 已保存" in texts


def test_app_shell_object_name(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.objectName() == "AppShell"


def test_app_shell_syncs_data_page_context_to_sidebar(tmp_path, qtbot):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources.append(resource)
    shell = AppShell(project=project)
    qtbot.addWidget(shell)
    page = shell.page_stack.widget(1)

    page._set_selected_asset(resource)
    qtbot.waitUntil(lambda: page.reader_panel.current_mode == "text", timeout=3000)

    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[0]
    assert "项目总览" in " ".join(label.text() for label in shell.sidebar._content_labels)

    shell.icon_rail.nav_buttons[1].click()

    text = " ".join(label.text() for label in shell.sidebar._content_labels)
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[1]
    assert "当前选择: notes.txt" in text
    assert "阅读器: text" in text


def test_app_shell_initializes_sidebar_on_home_context(tmp_path, qtbot):
    path = tmp_path / "resource-1.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    project.resources.append(
        ResourceItem(
            name="resource-1.txt",
            path=str(path),
            type="document",
            format="txt",
        )
    )

    shell = AppShell(project=project)
    qtbot.addWidget(shell)

    text = " ".join(label.text() for label in shell.sidebar._content_labels)
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[0]
    assert "项目总览" in text
    assert "资源 1" not in text


def test_app_shell_update_data_page_preserves_sidebar_selection(tmp_path, qtbot):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources.append(resource)
    shell = AppShell(project=project)
    qtbot.addWidget(shell)
    page = shell.page_stack.widget(1)

    page._set_selected_asset(resource)
    qtbot.waitUntil(lambda: page.reader_panel.current_mode == "text", timeout=3000)
    shell.update_data_page({}, project.resources, project.export_artifacts)
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[0]

    shell.icon_rail.nav_buttons[1].click()

    text = " ".join(label.text() for label in shell.sidebar._content_labels)
    assert "资源 1" in text
    assert "当前选择: notes.txt" in text
    assert "格式: document / txt" in text
    assert "阅读器: text" in text


def test_app_shell_retains_data_sidebar_context_when_navigating_back(tmp_path, qtbot):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources.append(resource)
    shell = AppShell(project=project)
    qtbot.addWidget(shell)
    page = shell.page_stack.widget(1)

    page._set_selected_asset(resource)
    qtbot.waitUntil(lambda: page.reader_panel.current_mode == "text", timeout=3000)
    shell.icon_rail.nav_buttons[4].click()
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[4]
    shell.icon_rail.nav_buttons[1].click()

    text = " ".join(label.text() for label in shell.sidebar._content_labels)
    assert shell.sidebar.context_label.text() == "数据"
    assert "资源 1" in text
    assert "当前选择: notes.txt" in text
    assert "阅读器: text" in text
    assert "当前选择: 未选择" not in text
    assert "阅读器: empty" not in text


def test_app_shell_has_workflow_stepper(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert hasattr(shell, "workflow_stepper")
    assert shell.workflow_stepper is not None
    assert shell.workflow_stepper.objectName() == "WorkflowStepper"


def test_app_shell_embeds_stepper_in_command_header(qtbot):
    """M2: the workflow stepper lives inside the 36px menu-bar command row."""
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.workflow_stepper.parent() is shell.menu_bar
    assert shell.menu_bar._header_center is shell.workflow_stepper


def test_app_shell_stepper_switches_stage_and_recalls_subpage(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    # Landing page (首页 = index 0) belongs to stage 1: the stepper starts
    # at the FIRST stage on launch, not the last one.
    assert shell.workflow_stepper.active_stage_index == 0
    assert shell.page_stack.currentIndex() == 0

    # Click Stepper Stage 1 (综合解释) -> remembered page 测井预测 (2)
    shell.workflow_stepper.stage_buttons[1].click()
    assert shell.page_stack.currentIndex() == 2
    assert shell.workflow_stepper.active_stage_index == 1

    # Click Stepper Stage 2 (古地理编图) -> should switch to PAGE_INDEX_MAPPING (8)
    shell.workflow_stepper.stage_buttons[2].click()
    assert shell.page_stack.currentIndex() == 8
    assert shell.workflow_stepper.active_stage_index == 2

    # Switch subpage within Stage 2 to PAGE_INDEX_VISUALIZATION (6)
    shell._switch_page(6)
    assert shell.page_stack.currentIndex() == 6

    # Stage 0 recalls its remembered page (首页, the landing page)…
    shell.workflow_stepper.stage_buttons[0].click()
    assert shell.page_stack.currentIndex() == 0

    # …then back to Stage 2 -> should recall PAGE_INDEX_VISUALIZATION (6)
    shell.workflow_stepper.stage_buttons[2].click()
    assert shell.page_stack.currentIndex() == 6


# --- Command palette (Ctrl+K) ----------------------------------------------

def _palette_escape_event():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    return QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )


def test_command_palette_lists_pages_and_stages(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    # No shell.show(): offscreen GL pages crash on native-window exposure
    # (suite convention); isHidden() tracks popup state without a window.

    shell.command_palette.popup()
    assert not shell.command_palette.isHidden()
    # 11 pages + 4 stages
    assert shell.command_palette.result_list.count() == 15

    shell.command_palette.filter_input.setText("编图")
    assert 0 < shell.command_palette.result_list.count() < 15


def test_command_palette_page_result_navigates(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    shell.command_palette.popup()
    shell.command_palette.filter_input.setText("地震预测")
    shell.command_palette._activate_item(
        shell.command_palette.result_list.currentItem()
    )

    assert shell.page_stack.currentIndex() == 3
    assert shell.command_palette.isHidden()


def test_command_palette_stage_result_respects_memory(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell._switch_page(6)  # 可视化 becomes the 古地理编图 stage's remembered page

    shell.command_palette.popup()
    # "古地理编图" matches only the stage ❸ command (page hints differ).
    shell.command_palette.filter_input.setText("古地理编图")
    shell.command_palette._activate_item(
        shell.command_palette.result_list.currentItem()
    )

    assert shell.page_stack.currentIndex() == 6
    assert shell.command_palette.isHidden()


def test_command_palette_escape_dismisses(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    palette = shell.command_palette

    # Esc works from the filter box…
    palette.popup()
    assert palette.eventFilter(palette.filter_input, _palette_escape_event()) is True
    assert palette.isHidden()

    # …and from the result list (r1 p3: keyboard users on the list keep Esc).
    palette.popup()
    assert palette.eventFilter(palette.result_list, _palette_escape_event()) is True
    assert palette.isHidden()


def test_ctrl_k_toggles_command_palette(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    keys = [
        sc.key().toString() for sc in shell.findChildren(QShortcut)
    ]
    assert "Ctrl+K" in keys

    shell._toggle_command_palette()
    assert not shell.command_palette.isHidden()
    shell._toggle_command_palette()
    assert shell.command_palette.isHidden()


def test_switch_page_dismisses_palette(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.command_palette.popup()
    shell._switch_page(1)
    assert shell.command_palette.isHidden()


# --- Sidebar float / resize / 面板 menu (M7) ---------------------------------


@pytest.fixture
def float_store(monkeypatch):
    """Real M4 FloatController + in-memory LayoutPersistence stand-in.

    Keeps QSettings clean and skips when the framework branch
    (feat/float-panel-framework) has not been merged into this worktree yet.
    The stand-in mirrors the LayoutPersistence class interface.
    """
    framework = app_shell_module._load_float_framework()
    if framework is None:
        pytest.skip("M4 float framework not merged yet")
    controller_cls = framework[0]
    store: dict = {}

    def save_float(key, geometry):
        store[key] = {
            "floating": True,
            "geometry": QRect(geometry),
            "docked_sizes": None,
            "visible": True,
        }

    def save_dock(key, sizes):
        state = store.setdefault(
            key,
            {
                "floating": False,
                "geometry": None,
                "docked_sizes": None,
                "visible": True,
            },
        )
        state["floating"] = False
        state["geometry"] = None
        state["docked_sizes"] = tuple(sizes)

    def save_docked_sizes(key, sizes):
        state = store.setdefault(
            key,
            {
                "floating": False,
                "geometry": None,
                "docked_sizes": None,
                "visible": True,
            },
        )
        state["docked_sizes"] = tuple(sizes)

    def save_visibility(key, visible):
        state = store.setdefault(
            key,
            {
                "floating": False,
                "geometry": None,
                "docked_sizes": None,
                "visible": True,
            },
        )
        state["visible"] = bool(visible)

    def load(key):
        from paleo_workbench.ui.layout_persistence import PanelLayoutRecord

        state = store.get(key)
        if state is None:
            return PanelLayoutRecord()
        return PanelLayoutRecord(
            floating=state["floating"],
            geometry=state["geometry"],
            docked_sizes=state["docked_sizes"],
            visible=state["visible"],
        )

    def clear(key):
        store.pop(key, None)

    fake_instance = SimpleNamespace(
        save_float=save_float,
        save_dock=save_dock,
        save_docked_sizes=save_docked_sizes,
        save_visibility=save_visibility,
        load=load,
        clear=clear,
    )
    monkeypatch.setattr(
        app_shell_module,
        "_load_float_framework",
        lambda: (controller_cls, lambda settings=None: fake_instance),
    )
    return store


@pytest.fixture
def windowed_platform(monkeypatch):
    """Clear the offscreen env so the float guard unblocks.

    The Qt platform plugin was already chosen at QApplication creation — no
    real window can appear because the tests never call show().
    """
    monkeypatch.setenv("QT_QPA_PLATFORM", "")


def test_shell_has_sidebar_resize_handle_between_sidebar_and_pages(
    qtbot, float_store
):
    shell = AppShell()
    qtbot.addWidget(shell)
    handle = shell.sidebar_resize_handle
    assert handle.parent() is shell
    assert not handle.isHidden()
    middle = shell._middle_layout
    assert (
        middle.indexOf(shell.sidebar)
        < middle.indexOf(handle)
        < middle.indexOf(shell.page_stack)
    )
    assert shell.sidebar.user_width() == SIDEBAR_DEFAULT_WIDTH


def _mouse_event(event_type, handle, global_x):
    local = handle.rect().center()
    return QMouseEvent(
        event_type,
        local,
        QPointF(global_x, local.y()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_handle_drag_resizes_sidebar_within_bounds(qtbot, float_store):
    """Press → move → release on the handle applies a clamped docked width."""
    shell = AppShell()
    qtbot.addWidget(shell)
    handle = shell.sidebar_resize_handle
    sidebar_left = shell.sidebar.mapToGlobal(QPoint(0, 0)).x()

    def drag_to(width):
        global_x = sidebar_left + width
        QApplication.sendEvent(handle, _mouse_event(QEvent.Type.MouseButtonPress, handle, global_x))
        QApplication.sendEvent(handle, _mouse_event(QEvent.Type.MouseMove, handle, global_x))
        QApplication.sendEvent(handle, _mouse_event(QEvent.Type.MouseButtonRelease, handle, global_x))

    drag_to(500)
    assert shell.sidebar.user_width() == SIDEBAR_MAX_WIDTH
    drag_to(50)
    assert shell.sidebar.user_width() == SIDEBAR_MIN_WIDTH
    drag_to(230)
    assert shell.sidebar.user_width() == 230


def test_panels_menu_actions_emit_shell_signals(qtbot, float_store):
    shell = AppShell()
    qtbot.addWidget(shell)
    float_requests, reset_requests = [], []
    shell.menu_bar.sidebar_float_requested.connect(
        lambda: float_requests.append(True)
    )
    shell.menu_bar.reset_panels_layout_requested.connect(
        lambda: reset_requests.append(True)
    )
    shell.menu_bar.float_sidebar_action.trigger()
    shell.menu_bar.reset_panels_layout_action.trigger()
    assert float_requests == [True]
    assert reset_requests == [True]


def test_float_actions_inert_without_framework(qtbot, monkeypatch):
    monkeypatch.setattr(app_shell_module, "_load_float_framework", lambda: None)
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.sidebar_float_controller is None
    shell.sidebar.float_btn.click()
    shell._toggle_sidebar_float()
    shell.menu_bar.reset_panels_layout_action.trigger()
    assert shell.sidebar.parent() is shell
    assert shell.sidebar.user_width() == SIDEBAR_DEFAULT_WIDTH


def test_float_stays_inert_under_offscreen(qtbot, float_store, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.sidebar.float_btn.click()
    shell.menu_bar.float_sidebar_action.trigger()
    assert not shell.sidebar_is_floated()
    assert shell.sidebar.parent() is shell


def test_sidebar_float_round_trip(qtbot, float_store, windowed_platform):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert not shell.sidebar_is_floated()

    shell.sidebar.float_btn.click()
    assert shell.sidebar_is_floated()
    panel = shell.sidebar.window()
    assert panel.isWindow() and panel is not shell
    assert shell._middle_layout.indexOf(shell.sidebar) == -1
    assert shell.sidebar_resize_handle.isHidden()
    assert shell.menu_bar.float_sidebar_action.isChecked()
    float_state = float_store[_SIDEBAR_FLOAT_KEY]
    assert float_state["floating"] is True
    assert isinstance(float_state["geometry"], QRect)

    shell.menu_bar.float_sidebar_action.trigger()
    assert not shell.sidebar_is_floated()
    assert shell.sidebar.parent() is shell
    assert shell._middle_layout.indexOf(shell.sidebar) == 1
    assert shell._middle_layout.indexOf(shell.sidebar_resize_handle) == 2
    assert not shell.sidebar_resize_handle.isHidden()
    assert not shell.menu_bar.float_sidebar_action.isChecked()
    dock_state = float_store[_SIDEBAR_FLOAT_KEY]
    assert dock_state["floating"] is False
    assert dock_state["docked_sizes"] == (SIDEBAR_DEFAULT_WIDTH,)


def test_reset_panels_layout_while_floated_persists_defaults(
    qtbot, float_store, windowed_platform
):
    """p2-1 r1: resetting from a FLOATED state must persist the defaults.

    The dock transition re-records the pre-reset width; the reset must
    therefore write the default width to the store afterwards."""
    float_store[_SIDEBAR_FLOAT_KEY] = {
        "floating": False,
        "geometry": None,
        "docked_sizes": (250,),
        "visible": True,
    }
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.sidebar.user_width() == 250
    shell._toggle_sidebar_float()
    assert shell.sidebar_is_floated()

    shell.menu_bar.reset_panels_layout_action.trigger()

    assert not shell.sidebar_is_floated()
    assert shell.sidebar.parent() is shell
    assert shell.sidebar.user_width() == SIDEBAR_DEFAULT_WIDTH
    state = float_store[_SIDEBAR_FLOAT_KEY]
    assert state["floating"] is False
    assert state["docked_sizes"] == (SIDEBAR_DEFAULT_WIDTH,)


def test_drag_finish_persists_sidebar_width(qtbot, float_store):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.sidebar_resize_handle.drag_finished.emit(230)
    assert float_store[_SIDEBAR_FLOAT_KEY]["docked_sizes"] == (230,)
    shell.sidebar_resize_handle.drag_finished.emit(10_000)
    assert float_store[_SIDEBAR_FLOAT_KEY]["docked_sizes"] == (SIDEBAR_MAX_WIDTH,)


def test_shell_restores_persisted_sidebar_width(qtbot, float_store):
    float_store[_SIDEBAR_FLOAT_KEY] = {
        "floating": False,
        "geometry": None,
        "docked_sizes": (240,),
        "visible": True,
    }
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.sidebar.user_width() == 240


def test_shell_restores_floated_state_on_windowed_platform(
    qtbot, float_store, windowed_platform
):
    float_store[_SIDEBAR_FLOAT_KEY] = {
        "floating": True,
        "geometry": QRect(100, 100, 300, 500),
        "docked_sizes": (200,),
        "visible": True,
    }
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.sidebar_is_floated()
    assert shell.sidebar.window().isWindow()
    assert shell.menu_bar.float_sidebar_action.isChecked()
    shell._toggle_sidebar_float()  # menu/dock path returns it
    assert shell.sidebar.parent() is shell


def test_reset_panels_layout_clears_persisted_keys(
    qtbot, float_store, windowed_platform
):
    float_store[_SIDEBAR_FLOAT_KEY] = {
        "floating": False,
        "geometry": None,
        "docked_sizes": (250,),
        "visible": True,
    }
    float_store["other:page"] = {"floating": True, "geometry": None}
    shell = AppShell()
    qtbot.addWidget(shell)

    shell.menu_bar.reset_panels_layout_action.trigger()

    # this shell's key is re-persisted with the DEFAULTS (p2-1 r1: the store
    # must match the reset); other consumers' keys are not touched
    state = float_store[_SIDEBAR_FLOAT_KEY]
    assert state["floating"] is False
    assert state["docked_sizes"] == (SIDEBAR_DEFAULT_WIDTH,)
    assert float_store["other:page"] == {"floating": True, "geometry": None}
    assert shell.sidebar.user_width() == SIDEBAR_DEFAULT_WIDTH
    assert shell.sidebar.is_collapsed is False
    assert not shell.sidebar_is_floated()
    assert shell.sidebar.parent() is shell
