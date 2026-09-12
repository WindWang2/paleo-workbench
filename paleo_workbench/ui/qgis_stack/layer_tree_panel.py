"""QgisLayerTreePanel：QgsLayerTreeView 承载的图层管理面板。

LayerManagerPanel（QTreeWidget 自绘树）的 drop-in 替换——同名 16 个信号与
bind/select_layer/layer_by_id/set_layer_visible/set_layer_opacity/move_layer/
set_editing_layer/set_project_crs/_publish 接缝，``self._layers`` 保持可读。

树的用户操作（勾选/拖拽/重命名/右键菜单）直接落在 QgsProject（运行时权威），
经 C++ 回调回写 ``_layers`` 后由 ``notify_display_changed`` 落持久化权威；
程序化 reconcile 走 suppress 计数器，不回声。
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QLabel,
)

from paleo_workbench.mapping.crs_contract import panel_publish_crs
from paleo_workbench.ui.qgis_stack.tree_sync import parse_tree_change, parse_tree_events
from paleo_workbench.ui.qgis_stack.widgets import QgisLayerTreeHost

# 原生菜单（C++ provider 产词）里接受 evaluator 判词门禁的动作文案 →
# 菜单键。contextMenuAboutToShow 阶段按文案匹配（provider 不暴露键）。
_MENU_GATED_TEXTS = {
    "toggle_editing": "开始/停止编辑",
    "repair": "修复无效几何…",
    "remove_layer": "删除图层",
}


def _icon(name: str):
    """延迟导入：workstation/__init__ → composite_document → 本模块存在环。"""
    from paleo_workbench.ui.workstation.common import workstation_icon

    return workstation_icon(name)

# 菜单动作键 → 面板请求信号名（C++ menu provider 的自定义键）
_MENU_SIGNALS = {
    "create_layer": "create_layer_requested",
    "import_reference": "import_reference_requested",
    "remove_layer": "remove_layer_requested",
    "remove_reference": "remove_reference_requested",
    "refresh_reference": "refresh_reference_requested",
    "toggle_reference_snap": "toggle_reference_snap_requested",
    "attribute_table": "attribute_table_requested",
    "toggle_editing": "toggle_editing_requested",
    "properties": "properties_requested",
    "symbology": "symbology_requested",
    "labeling": "labeling_requested",
    "duplicate": "duplicate_layer_requested",
    # V5 分组（组上下文/根菜单，payload 为 group_id）
    "create_group": "create_group_requested",
    "remove_group": "remove_group_requested",
    "export": "export_layer_requested",
    "repair": "repair_layer_requested",
}


class QgisLayerTreePanel(QWidget):
    """QgsLayerTreeView 图层管理面板（QGIS 图层面板语义）。"""

    create_layer_requested = Signal()
    remove_layer_requested = Signal(str)
    # 无 rename_layer_requested：树上改名直接生效并经 _on_tree_change 回写
    # （QGIS 语义，rename 不经请求信号绕行）。
    import_reference_requested = Signal()
    remove_reference_requested = Signal(str)
    refresh_reference_requested = Signal(str)
    toggle_reference_snap_requested = Signal(str)
    attribute_table_requested = Signal(str)
    toggle_editing_requested = Signal(str)
    properties_requested = Signal(str)
    symbology_requested = Signal(str)
    labeling_requested = Signal(str)
    duplicate_layer_requested = Signal(str)
    export_layer_requested = Signal(str)
    repair_layer_requested = Signal(str)
    # 当前图层变化（无可编辑图层时携带 None）。
    active_layer_changed = Signal(object)
    # V7 §7：双击定位信号（原生树双击事件经树回调回传时发射；无桥环境
    # 由宿主 fallback 面板承担——同构信号）。
    zoom_to_layer_requested = Signal(str)
    # 树回写/显示增量后的持久化通知（CompositeDocument 接 notify_display_changed）。
    display_state_changed = Signal()
    # V5 分组请求（组上下文菜单；create 无参，remove 携带 group_id）。
    create_group_requested = Signal()
    remove_group_requested = Signal(str)
    # 组勾选/结构变化经 controller 处理后的额外持久化通知。
    group_state_changed = Signal()

    def __init__(self, parent: QWidget | None = None, *, menu_probe=None,
                 repair_probe=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self._manage_buttons: list[QToolButton] = []
        self._layers: list = []
        self._canvas = None
        self._project_crs = ""
        self._editing_layer_id: str | None = None
        self._selected_doc_id: str | None = None
        # V11 Goal §7（A1）：与 LayerManagerPanel 同构的 evaluator 探针——
        # 编辑/修复/删除入口的可用性来自 canonical evaluator（宿主注入
        # layer_menu_facts / _layer_repair_availability），不再只看
        # metadata["editable"] 旧旗标。None = 无宿主（独立用/测试）：回落
        # 旧行为（metadata 旗标）。
        self._menu_probe = menu_probe
        self._repair_probe = repair_probe
        # V5 分组编排（LayerGroupController；树事件经此回写领域状态）。
        self._group_controller = None
        # 程序化发布中（set_layer_snapshot / set_mirror_layer_order 经由原生
        # 树结构信号重入 _on_tree_selection）：此时的选中跳变是重排噪声，
        # 不得外发 active_layer_changed（否则数字化工具被回落 pan）。
        # 用户点击与 select_layer() 程序化置当前不受影响。
        self._publishing = False
        self.tree_host: QgisLayerTreeHost | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self._outer = outer

        manage_row = QHBoxLayout()
        for label, icon, tip, callback in (
            ("新建矢量图层", "map/tree-add-layer.svg", "新建点 / 线 / 面矢量图层",
             self.create_layer_requested.emit),
            ("导入参考图层", "map/tree-add-layer.svg",
             "导入外部矢量文件作为只读参考（GDAL）", self.import_reference_requested.emit),
            ("添加分组", "map/tree-add-group.svg",
             "新建图层组（可拖入图层）", self.create_group_requested.emit),
            ("删除图层", "map/tree-remove.svg", "删除当前矢量图层（编修图层）",
             self._on_remove_layer),
        ):
            button = QToolButton(self)
            button.setObjectName("WorkstationContextButton")
            button.setIcon(_icon(icon))
            button.setText(label)
            button.setToolTip(f"{label} — {tip}")
            # 纯图标：文字态会把面板最小宽度撑到四个按钮全宽之和，
            # dock 无法调窄（#用户反馈）。全名留在 tooltip。
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.clicked.connect(callback)
            manage_row.addWidget(button)
            self._manage_buttons.append(button)
            if label == "删除图层":
                self.remove_button = button
        self.remove_button.setEnabled(False)
        manage_row.addStretch(1)
        outer.addLayout(manage_row)

        opacity_row = QHBoxLayout()
        opacity_label = QLabel("不透明度", self)
        opacity_label.setObjectName("WorkstationPanelFootnote")
        opacity_row.addWidget(opacity_label)
        self.opacity = QSlider(Qt.Orientation.Horizontal, self)
        self.opacity.setRange(10, 100)
        self.opacity.setValue(100)
        opacity_row.addWidget(self.opacity, 1)
        outer.addLayout(opacity_row)
        self.opacity.valueChanged.connect(self._apply_opacity)

        # V7 §7：组级真实聚合摘要行；V8 M5 起行内状态经桥的通用行指示器
        # （set_row_indicators）投影——旧桥无该能力时仍只有本摘要行。
        self.group_status_label = QLabel("", self)
        self.group_status_label.setObjectName("WorkstationPanelFootnote")
        self.group_status_label.setWordWrap(True)
        outer.addWidget(self.group_status_label)
        self._decorations: dict = {}

    def set_layer_decorations(self, decorations: dict) -> None:
        """V7 §7：接收图层级呈现态；V8 M5 起同时投影为原生行指示器。

        桥有 ``set_row_indicators``（feature flag row_indicators）时按
        LayerPresentationState 的装饰词汇（dirty/stale/missing/…）逐行推
        送；旧桥诚实跳过（仅摘要行）。editing 仍由 set_editing_layer 的 ✏
        铅笔独占，不在此重复。
        """
        self._decorations = dict(decorations or {})
        self._push_native_row_indicators()
        self._update_group_status_label()

    @staticmethod
    def _indicator_kinds(state) -> list[str]:
        """LayerPresentationState → 行指示器 kinds（优先序同 _PRIORITY）。"""
        if state is None:
            return []
        maturity = getattr(state, "maturity", None)
        flags = [
            ("missing", bool(getattr(state, "missing", False))),
            ("dirty", bool(getattr(state, "dirty", False))),
            ("missing_input", bool(getattr(state, "missing_input", False))),
            ("superseded", bool(getattr(state, "superseded", False))),
            ("stale", bool(getattr(state, "stale", False))),
            ("degraded", bool(getattr(state, "degraded", False))),
            ("frozen", maturity == "frozen"),
            ("published", maturity == "published"),
            ("reviewed", maturity == "reviewed"),
        ]
        return [kind for kind, on in flags if on]

    def _push_native_row_indicators(self) -> None:
        """把装饰态投影到桥的原生行指示器（能力门控 + 幂等整组替换）。"""
        tree_host = getattr(self, "tree_host", None)
        canvas = getattr(self, "_canvas", None)
        if tree_host is None or canvas is None:
            return
        stack = getattr(canvas, "stack", None)
        if stack is None:
            return
        push = getattr(stack, "set_row_indicators", None)
        if not callable(push):
            return  # 旧桥：诚实跳过（group summary 仍呈现状态）
        import json

        for doc_id, state in self._decorations.items():
            kinds = self._indicator_kinds(state)
            try:
                push(
                    tree_host.tree_view_address,
                    str(doc_id),
                    json.dumps(kinds),
                )
            except Exception:
                # 指示器是纯呈现增强：失败不得影响数据/树权威。
                continue

    def set_group_summaries(self, summaries) -> None:
        """V7 §7：组级聚合摘要（问题组优先；干净组只计数）。"""
        self._group_summaries_cache = list(summaries or [])
        self._update_group_status_label()

    def _update_group_status_label(self) -> None:
        summaries = getattr(self, "_group_summaries_cache", None) or []
        problem = [s for s in summaries if getattr(s, "has_problems", False)]
        parts = []
        for summary in problem[:4]:
            parts.append(
                f"{summary.title}: {summary.summary_text()}"
            )
        if not parts:
            total = sum(int(getattr(s, "layers", 0)) for s in summaries)
            parts.append(f"{total} 层 · 组状态正常" if total else "暂无图层")
        self.group_status_label.setText(" · ".join(parts))

    # -- 静态判定（与旧面板同语义） ---------------------------------------------

    @staticmethod
    def is_editable_layer(layer) -> bool:
        return bool(getattr(layer, "metadata", {}) and layer.metadata.get("editable") == "true")

    @staticmethod
    def is_reference_layer(layer) -> bool:
        return bool(getattr(layer, "metadata", {}) and layer.metadata.get("reference") == "true")

    # -- 绑定 ---------------------------------------------------------------

    def bind(self, canvas, layers: list) -> None:
        self._canvas = canvas
        self._layers = list(layers)
        if self.tree_host is None and canvas is not None:
            self.tree_host = QgisLayerTreeHost(canvas.stack, canvas.canvas_address, self)
            self._outer.insertWidget(1, self.tree_host, 1)
            tree = self.tree_host.tree_view_address
            canvas.stack.set_tree_selection_callback(tree, self._on_tree_selection)
            canvas.stack.set_tree_change_callback(tree, self._on_tree_change)
            canvas.stack.set_tree_menu_callback(tree, self._on_tree_menu)
            # V11（A1）：原生菜单由 C++ provider 构建且不暴露键级门禁——
            # 在菜单弹出前（contextMenuAboutToShow）按判词门禁编辑/修复/
            # 删除项。旧桥无该信号时诚实跳过（判词消费只剩执行侧 re-gate）。
            try:
                self.tree_host.tree_view.contextMenuAboutToShow.connect(
                    self._on_native_menu_about_to_show)
            except (AttributeError, RuntimeError):
                pass
        self._publish()
        self.expand_layer_groups()

    def expand_layer_groups(self) -> None:
        """分组必须能点开：树创建/reconcile 后展开全部组。"""
        host = getattr(self, "tree_host", None)
        if host is None:
            return
        from paleo_workbench.ui.qgis_stack.widgets import configure_layer_tree_view

        configure_layer_tree_view(host.tree_view)

    def set_project_crs(self, crs: str) -> None:
        """注入项目 CRS 权威（ProjectDocument.coordinate → 渲染快照）。"""
        crs = str(crs or "")
        if crs and crs != self._project_crs:
            self._project_crs = crs

    def _make_snapshot(self):
        from paleo_workbench.mapping.map_render_backend import MapRenderSnapshot

        return MapRenderSnapshot(
            project_crs=panel_publish_crs(self._project_crs),
            layers=tuple(self._layers),
        )

    def _publish(self, *, reload_tree: bool = True) -> None:
        """推快照到画布；树由 reconcile 自动跟随（reload_tree 仅保签名兼容）。"""
        if self._canvas is None:
            return
        self._publishing = True
        try:
            # V11：宿主 settle 的 journal 提示随快照下推（O(changed) 差分）；
            # 无宿主/无提示 = None（回落全量比较）。parent 即宿主
            # CompositeDocument（_create_layer_manager 构造约定）。
            host = self.parent()
            edit_controller = getattr(host, "edit_controller", None)
            hints = edit_controller.snapshot_changed_hints()                 if hasattr(edit_controller, "snapshot_changed_hints") else None
            self._canvas.set_layer_snapshot(
                self._make_snapshot(), changed_hints=hints)
        finally:
            self._publishing = False

    # -- 查询/选择 ------------------------------------------------------------

    def layer_by_id(self, layer_id: str):
        for layer in self._layers:
            if layer.id == layer_id:
                return layer
        return None

    def tree_row_count(self) -> int:
        """树顶层行数（测试/状态检查用；未绑定时为 0）。"""
        if self.tree_host is None or self._canvas is None:
            return 0
        return self._canvas.stack.tree_view_row_count(self.tree_host.tree_view_address)

    def select_layer(self, layer_id: str) -> None:
        """按 id 置为当前图层（QGIS 语义：新建图层即成为当前图层）。"""
        if self.tree_host is None or self._canvas is None:
            return
        self._canvas.stack.tree_view_select_doc(
            self.tree_host.tree_view_address, str(layer_id))

    def set_editing_layer(self, layer_id: str | None) -> None:
        """标记正在编辑的图层。

        M3（M2 移交项）：QgsLayerTreeView 以图层指示器呈现 ✏ 编辑态
        （QGIS 桌面同款视觉机制，不改节点名避免写回权威污染）。
        """
        previous = getattr(self, "_editing_layer_id", None)
        if layer_id == previous:
            return
        self._editing_layer_id = layer_id
        if self.tree_host is None or self._canvas is None:
            return
        tree = self.tree_host.tree_view_address
        for doc_id, on in ((previous, False), (layer_id, True)):
            if not doc_id:
                continue
            try:
                self._canvas.stack.set_edit_indicator(tree, str(doc_id), on)
            except Exception:
                pass

    # -- 外部显示增量（CompositeDocument 属性应用路径） ---------------------------

    def set_layer_visible(self, layer_id: str, visible: bool) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        self._layers[self._layers.index(layer)] = replace(layer, visible=visible)
        if self._canvas is not None and self.tree_host is not None:
            try:
                self._canvas.stack.set_mirror_layer_visibility(str(layer_id), bool(visible))
            except Exception:
                pass
        self._notify_display_changed()

    def set_layer_opacity(self, layer_id: str, opacity: float) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        opacity = max(0.05, float(opacity))
        self._layers[self._layers.index(layer)] = replace(layer, opacity=opacity)
        if self._canvas is not None and self.tree_host is not None:
            try:
                self._canvas.stack.set_mirror_layer_opacity(str(layer_id), opacity)
            except Exception:
                pass
        self._notify_display_changed()

    def move_layer(self, layer_id: str, direction: int) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        index = self._layers.index(layer)
        target = index - direction
        if not 0 <= target < len(self._layers):
            return
        self._layers[index], self._layers[target] = (
            self._layers[target],
            self._layers[index],
        )
        self._push_mirror_order()
        self._notify_display_changed()

    def _push_mirror_order(self) -> None:
        """把 _layers 的顶层顺序（top-first）推到镜像树（程序化，不 echo）。

        V5 分组模式：root 平铺顺序不再是权威（组内顺序 + 放置由
        LayerGroupController reconcile），此处不再推送。
        """
        if self._canvas is None or self.tree_host is None:
            return
        if self._group_controller is not None:
            return
        self._publishing = True
        try:
            self._canvas.stack.set_mirror_layer_order(
                [str(layer.id) for layer in self._layers])
        except Exception:
            pass
        finally:
            self._publishing = False

    # -- 树回调 ---------------------------------------------------------------

    def _on_tree_selection(self, doc_id: str) -> None:
        # 程序化发布中的选中跳变是重排噪声：本地呈现可跟随，但不得外发
        # active_layer_changed（见 _publishing 注释）。
        if getattr(self, "_publishing", False):
            return
        self._selected_doc_id = doc_id or None
        self._sync_opacity(self._selected_doc_id)
        # V11（A1）：探针在场时删除按钮按 facts 门禁（editable 旗标或 RAW
        # 编排事实）；无探针保持旧行为（metadata 旗标）。
        if callable(self._menu_probe):
            allowed, _reason = self._remove_gate(str(doc_id or ""))
            self.remove_button.setEnabled(allowed)
        else:
            layer = self.layer_by_id(doc_id) if doc_id else None
            self.remove_button.setEnabled(
                layer is not None and self.is_editable_layer(layer))
        self.active_layer_changed.emit(doc_id or None)

    def set_group_controller(self, controller) -> None:
        """注入 LayerGroupController（V5 分组事件回写；None = 平铺模式）。"""
        self._group_controller = controller

    def set_layer_probes(self, *, menu_probe=None, repair_probe=None) -> None:
        """注入/更新 evaluator 探针（构造之后的宿主接线口；None = 不改）。"""
        if menu_probe is not None:
            self._menu_probe = menu_probe
        if repair_probe is not None:
            self._repair_probe = repair_probe

    # -- evaluator 判词消费（V11 Goal §7 / A1，与 LayerManagerPanel 同语义） ----

    def _layer_menu_facts(self, doc_id: str):
        """menu_probe 产事实（LayerMenuFacts 鸭型：toggle/repair 判词 +
        raw_protected 编排事实）；无探针/探针失败 = None（回落旧行为）。"""
        if not callable(self._menu_probe) or not doc_id:
            return None
        try:
            return self._menu_probe(str(doc_id))
        except Exception:
            return None

    def _layer_repair_verdict(self, doc_id: str, facts=None):
        """修复判词：facts 探针优先（已求值过），独立用回落 repair_probe。"""
        verdict = getattr(facts, "repair_geometry", None) if facts else None
        if verdict is None and callable(self._repair_probe) and doc_id:
            try:
                verdict = self._repair_probe(str(doc_id))
            except Exception:
                verdict = None
        return verdict

    def _remove_gate(self, doc_id: str, facts=None) -> tuple[bool, str | None]:
        """删除入口门禁：探针在场时按 facts（editable 旗标或 RAW 编排事实，
        与回退树菜单的出现语义一致——RAW 图层可删，删除不是要素编辑）；
        无探针 = 旧行为（metadata 旗标）。``facts`` 可传入已取事实避免重复
        探针求值。"""
        layer = self.layer_by_id(doc_id) if doc_id else None
        if layer is None:
            return False, None
        if facts is None:
            facts = self._layer_menu_facts(doc_id)
        if facts is None:
            return self.is_editable_layer(layer), None
        if self.is_editable_layer(layer) or bool(
                getattr(facts, "raw_protected", False)):
            return True, None
        return False, "仅编修图层 / RAW 图层可从文档删除"

    def _apply_menu_gating(self, menu, doc_id: str) -> None:
        """把 evaluator 判词投影到原生菜单项（禁用保持可见 + 判词 tooltip）。

        与回退树 ``LayerManagerPanel._on_context_menu`` 同判词源（宿主
        menu_probe）同一呈现语义（「不可用：{reason}」）；facts 只取一次
        （menu_probe 每次调用都是一次完整 evaluator 求值）。删除项走
        ``_remove_gate``（编排事实，非 toggle 判词——RAW 可删）。C++ 菜单
        默认不显示 QAction tooltip，须显式开（同回退树 R2-1）。
        """
        if menu is None or not doc_id or not callable(self._menu_probe):
            return
        facts = self._layer_menu_facts(doc_id)
        if facts is None:
            return
        verdicts = {
            "toggle_editing": getattr(facts, "toggle_editing", None),
            "repair": self._layer_repair_verdict(doc_id, facts=facts),
        }
        remove_allowed, remove_reason = self._remove_gate(doc_id, facts=facts)
        menu.setToolTipsVisible(True)
        for action in menu.actions():
            key = next(
                (k for k, text in _MENU_GATED_TEXTS.items()
                 if action.text() == text), None)
            if key is None:
                continue
            if key == "remove_layer":
                if not remove_allowed:
                    action.setEnabled(False)
                    if remove_reason:
                        action.setToolTip(f"不可用：{remove_reason}")
                continue
            verdict = verdicts.get(key)
            if verdict is not None and not verdict.enabled:
                action.setEnabled(False)
                action.setToolTip(f"不可用：{verdict.disabled_reason or '当前不可用'}")

    def _on_native_menu_about_to_show(self, menu) -> None:
        """原生菜单弹出前：右键已置当前图层（selection 回调先于本信号），
        以 ``_selected_doc_id`` 为门禁对象。"""
        self._apply_menu_gating(menu, self._current_doc_id() or "")

    def _on_tree_menu(self, key: str, doc_id: str) -> None:
        signal_name = _MENU_SIGNALS.get(str(key))
        if signal_name is None:
            return
        # V11：执行护栏（呈现门禁之外的防线；宿主仍有 execution re-gate）。
        # 判词禁用的动作不外发请求信号——菜单项已禁用，此处只拦键盘/陈旧
        # 菜单等旁路触发。
        if callable(self._menu_probe) and doc_id:
            facts = self._layer_menu_facts(str(doc_id))
            if facts is not None:
                if signal_name == "toggle_editing_requested":
                    verdict = getattr(facts, "toggle_editing", None)
                    if verdict is not None and not verdict.enabled:
                        return
                elif signal_name == "repair_layer_requested":
                    verdict = self._layer_repair_verdict(
                        str(doc_id), facts=facts)
                    if verdict is not None and not verdict.enabled:
                        return
                elif signal_name == "remove_layer_requested":
                    allowed, _reason = self._remove_gate(str(doc_id), facts=facts)
                    if not allowed:
                        return
        signal = getattr(self, signal_name)
        if signal_name in ("create_layer_requested", "import_reference_requested",
                           "create_group_requested"):
            signal.emit()
        elif doc_id:
            signal.emit(str(doc_id))

    def _on_tree_change(self, payload: str) -> None:
        """树用户操作回写 _layers（不回推画布，防回环）+ 落持久化权威。

        V5 schema 2：typed events（含组）与全层级 tree 结构快照经
        LayerGroupController 回写领域分组状态（拖拽/建组/删组/组勾选）。
        """
        batch = parse_tree_events(payload)
        changes = batch.changes
        if changes.empty and not batch.events and not batch.tree:
            return
        for doc_id, visible in changes.visibility.items():
            layer = self.layer_by_id(doc_id)
            if layer is not None and layer.visible != visible:
                self._layers[self._layers.index(layer)] = replace(layer, visible=visible)
        for doc_id, name in changes.renames.items():
            layer = self.layer_by_id(doc_id)
            if layer is not None and layer.name != name:
                self._layers[self._layers.index(layer)] = replace(layer, name=name)
        if changes.order:
            listed = [self.layer_by_id(doc) for doc in changes.order]
            listed = [layer for layer in listed if layer is not None]
            listed_ids = {layer.id for layer in listed}
            unlisted = [layer for layer in self._layers if layer.id not in listed_ids]
            self._layers = listed + unlisted
        group_touched = False
        if self._group_controller is not None:
            controller = self._group_controller
            # V11：过期回声（revision ≤ 已应用值）不进领域写回——程序化
            # 变更的迟到回显/窗口内竞态由修订号门控（旧桥 revision=0 恒通过）。
            if controller.echo_is_stale(batch.revision):
                return
            if batch.tree:
                controller.observe_tree_nodes(list(batch.tree))
                group_touched = True
            group_visibility = batch.group_visibility()
            if group_visibility:
                for group_id, visible in group_visibility.items():
                    controller.record_group_visibility_event(group_id, visible)
                group_touched = True
            group_renames = batch.group_renames()
            if group_renames:
                for group_id, name in group_renames.items():
                    controller.rename_user_group(group_id, name)
                group_touched = True
        if group_touched:
            self.group_state_changed.emit()
        self._notify_display_changed()

    def _notify_display_changed(self) -> None:
        """通知宿主把显示增量写回编辑权威与工程文档（不重组快照）。"""
        self.display_state_changed.emit()

    # -- 工具行 ---------------------------------------------------------------

    def _on_remove_layer(self) -> None:
        if not self._layers:
            return
        layer_id = self._current_doc_id()
        if layer_id is None:
            return
        # V11：与菜单/按钮同一门禁（探针 facts 优先，无探针回落 metadata）。
        allowed, _reason = self._remove_gate(str(layer_id))
        if allowed:
            self.remove_layer_requested.emit(str(layer_id))

    def _current_doc_id(self) -> str | None:
        """树当前图层的 doc_id（选择回调同步缓存，随 currentLayerChanged 更新）。"""
        return getattr(self, "_selected_doc_id", None)

    def _sync_opacity(self, doc_id: str | None) -> None:
        layer = self.layer_by_id(doc_id) if doc_id else None
        if layer is not None:
            self.opacity.blockSignals(True)
            self.opacity.setValue(int(layer.opacity * 100))
            self.opacity.blockSignals(False)

    def _apply_opacity(self, value: int) -> None:
        layer_id = self._current_doc_id()
        if layer_id is not None:
            self.set_layer_opacity(layer_id, value / 100.0)
