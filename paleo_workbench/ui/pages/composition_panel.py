"""Composition authoring panel (P0-D UI): template → components → export.

A right-dock workbench panel over the composition core
(:mod:`paleo_workbench.mapping.composer.components`). Every mutation goes
through the :class:`CompositionEditSession` (one undo/redo history), the
preview re-renders from the session revision (never a stale cache), and
exports honor the physical-size + DPI contract. The panel is deliberately
style-plain: professional cartography authoring, not dashboard chrome.

B5: the property editor is schema-driven — editors are generated from the
component registry's ``property_schema`` (str→QLineEdit、number→
QDoubleSpinBox、bool→QCheckBox、choices→QComboBox、text→QTextEdit、
list→JSON 框), so new components get a working inspector with zero
hand-written forms. Locked elements refuse mutations at the session layer
and show a lock affordance here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QByteArray, QEvent, Qt, Signal, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.composer.components import (
    ComposerError,
    CompositionEditSession,
    CompositionFactory,
    bind_template,
)
from paleo_workbench.mapping.composer.export import export_composition
from paleo_workbench.mapping.composer.models import (
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.registry import (
    CATEGORY_LABELS,
    all_specs,
    categories,
    get_spec,
    specs_by_category,
)
from paleo_workbench.mapping.composer.renderer import composer_renderer
from paleo_workbench.mapping.composer.templates import (
    TEMPLATE_LIBRARY,
    instantiate_template,
)
from paleo_workbench.ui import tokens

logger = logging.getLogger(__name__)

# 组件中文名来自注册表（单一事实源）。
ELEMENT_TYPE_LABELS: dict[ElementType, str] = {
    spec.element_type: spec.label for spec in all_specs()
}

# STAT_CHART 中 series 为 [{label, value}] 的图表类型 → 表格编辑；
# histogram（{values, bins}）与 rose（[{label, angle_deg, value}]）用 JSON 框。
_TABLE_SERIES_CHART_TYPES = {"bar", "hbar", "line", "scatter", "pie"}

# 表单顶部固定行数（图件标题 + X/Y/宽/高），schema 驱动行在其后动态增删。
_STATIC_FORM_ROWS = 5


class CompositionPanel(QFrame):
    """Authoring surface for one composition document."""

    composition_changed = Signal(int)  # session revision
    composition_exported = Signal(str)  # exported path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CompositionPanel")
        self.factory = CompositionFactory()
        self.session: CompositionEditSession | None = None
        self._suppress_item_signals = False
        self._suppress_geometry_signals = False
        self._suppress_schema_signals = False
        # 属性名 → (editor, getter)；schema 驱动表单的动态行。
        self._schema_editors: dict[str, QWidget] = {}
        self._schema_getters: dict[str, Callable[[], Any]] = {}
        self._schema_dirty: set[str] = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PANEL_PADDING, tokens.PANEL_PADDING, tokens.PANEL_PADDING, tokens.PANEL_PADDING
        )
        outer.setSpacing(tokens.SPACE_2)

        # -- template row --------------------------------------------------
        template_row = QHBoxLayout()
        self.template_combo = QComboBox()
        for template in TEMPLATE_LIBRARY.values():
            self.template_combo.addItem(f"{template.label}（{template.description}）", template.template_id)
        self.template_combo.setToolTip("从专业模板新建组图（版式 + 组件 + 绑定，非位图）")
        template_row.addWidget(self.template_combo, 1)
        self.new_from_template_btn = QPushButton("新建")
        self.new_from_template_btn.setObjectName("SecondaryButton")
        self.new_from_template_btn.clicked.connect(self._new_from_template)
        template_row.addWidget(self.new_from_template_btn)
        outer.addLayout(template_row)

        # -- history row -----------------------------------------------------
        history_row = QHBoxLayout()
        self.undo_btn = QToolButton()
        self.undo_btn.setText("撤销")
        self.undo_btn.setToolTip("撤销组图编辑")
        self.undo_btn.clicked.connect(self._undo)
        self.redo_btn = QToolButton()
        self.redo_btn.setText("重做")
        self.redo_btn.setToolTip("重做组图编辑")
        self.redo_btn.clicked.connect(self._redo)
        self.save_btn = QToolButton()
        self.save_btn.setText("保存JSON")
        self.save_btn.setToolTip("保存组图文档（JSON，含组件与绑定）")
        self.save_btn.clicked.connect(self._save_json)
        self.load_btn = QToolButton()
        self.load_btn.setText("打开JSON")
        self.load_btn.setToolTip("打开已保存的组图文档")
        self.load_btn.clicked.connect(self._load_json)
        for btn in (self.undo_btn, self.redo_btn, self.save_btn, self.load_btn):
            history_row.addWidget(btn)
        history_row.addStretch(1)
        outer.addLayout(history_row)

        # -- element list ------------------------------------------------------
        self.element_list = QListWidget()
        self.element_list.setToolTip("组图组件（右键菜单支持锁定/复制/层级）")
        self.element_list.currentRowChanged.connect(self._on_element_selected)
        self.element_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.element_list.customContextMenuRequested.connect(self._on_element_menu)
        outer.addWidget(self.element_list, 2)

        element_row = QHBoxLayout()
        self.add_btn = QToolButton()
        self.add_btn.setText("＋组件")
        self.add_btn.setToolTip("添加组图组件")
        self.add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._build_add_menu()
        self.delete_btn = QToolButton()
        self.delete_btn.setText("删除")
        self.delete_btn.setToolTip("删除选中组件（可撤销）")
        self.delete_btn.clicked.connect(self._delete_selected)
        self.duplicate_btn = QToolButton()
        self.duplicate_btn.setText("复制")
        self.duplicate_btn.setToolTip("复制选中组件")
        self.duplicate_btn.clicked.connect(self._duplicate_selected)
        self.front_btn = QToolButton()
        self.front_btn.setText("置顶")
        self.front_btn.clicked.connect(lambda: self._reorder("front"))
        self.back_btn = QToolButton()
        self.back_btn.setText("置底")
        self.back_btn.clicked.connect(lambda: self._reorder("back"))
        for btn in (self.add_btn, self.delete_btn, self.duplicate_btn, self.front_btn, self.back_btn):
            element_row.addWidget(btn)
        element_row.addStretch(1)
        outer.addLayout(element_row)

        # -- property editor ------------------------------------------------
        # 固定行：图件标题 + 几何；其下由 registry property_schema 动态生成。
        self.property_form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setToolTip("图件标题（写入图名组件）")
        self.title_edit.editingFinished.connect(self._apply_title)
        self.property_form.addRow("图件标题", self.title_edit)
        self.x_spin = self._mm_spin(0.0, 2000.0)
        self.y_spin = self._mm_spin(0.0, 2000.0)
        self.w_spin = self._mm_spin(1.0, 2000.0)
        self.h_spin = self._mm_spin(1.0, 2000.0)
        self.x_spin.valueChanged.connect(lambda v: self._apply_geometry("x", v))
        self.y_spin.valueChanged.connect(lambda v: self._apply_geometry("y", v))
        self.w_spin.valueChanged.connect(lambda v: self._apply_geometry("w", v))
        self.h_spin.valueChanged.connect(lambda v: self._apply_geometry("h", v))
        self.property_form.addRow("X (mm)", self.x_spin)
        self.property_form.addRow("Y (mm)", self.y_spin)
        self.property_form.addRow("宽 (mm)", self.w_spin)
        self.property_form.addRow("高 (mm)", self.h_spin)
        self.lock_hint = QLabel("组件已锁定（右键解锁后可编辑）")
        self.lock_hint.setObjectName("EmptyStateLabel")
        self.lock_hint.setVisible(False)
        self.property_form.addRow(self.lock_hint)

        editor_host = QWidget()
        editor_host.setLayout(self.property_form)
        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        editor_scroll.setWidget(editor_host)
        outer.addWidget(editor_scroll, 2)

        # -- preview ------------------------------------------------------------
        self.preview_label = QLabel("尚无组图")
        self.preview_label.setObjectName("EmptyStateLabel")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(120)
        outer.addWidget(self.preview_label, 3)

        # -- export row -----------------------------------------------------------
        export_row = QHBoxLayout()
        self.export_combo = QComboBox()
        self.export_combo.addItem("PNG", "png")
        self.export_combo.addItem("SVG", "svg")
        self.export_combo.addItem("PDF", "pdf")
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 1200)
        self.dpi_spin.setValue(300)
        self.dpi_spin.setSuffix(" dpi")
        self.dpi_spin.setToolTip("输出 DPI（物理尺寸由纸张决定）")
        self.export_btn = QPushButton("导出")
        self.export_btn.setObjectName("SecondaryButton")
        self.export_btn.clicked.connect(self._export)
        export_row.addWidget(self.export_combo, 1)
        export_row.addWidget(self.dpi_spin)
        export_row.addWidget(self.export_btn)
        outer.addLayout(export_row)

        self._new_from_template()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mm_spin(minimum: float, maximum: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(1)
        spin.setSingleStep(1.0)
        spin.setSuffix(" mm")
        return spin

    def _build_add_menu(self) -> None:
        """组件添加菜单按注册表分类组织（默认几何/属性同源）。"""
        add_menu = QMenu(self.add_btn)
        for category in categories():
            sub = add_menu.addMenu(CATEGORY_LABELS.get(category, category))
            for spec in specs_by_category(category):
                sub.addAction(
                    spec.label,
                    lambda checked=False, t=spec.element_type: self._add_element(t),
                )
        self.add_btn.setMenu(add_menu)

    def _require_session(self) -> CompositionEditSession | None:
        return self.session

    def _selected_element_id(self) -> str | None:
        item = self.element_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    # ------------------------------------------------------------------
    # document lifecycle
    # ------------------------------------------------------------------

    def _new_from_template(self) -> None:
        template_id = self.template_combo.currentData() or "single_factor"
        doc = instantiate_template(str(template_id))
        self.set_document(doc)

    def set_document(self, doc: MapCompositionDocument) -> None:
        self.session = CompositionEditSession(doc, self.factory)
        self.title_edit.setText(doc.title)
        self._refresh_all()

    def document(self) -> MapCompositionDocument | None:
        return self.session.document if self.session is not None else None

    def apply_bindings(self, binding_context: dict) -> int:
        """Resolve declarative data bindings (factor colormaps, statistics)."""
        if self.session is None:
            return 0
        resolved = bind_template(self.session.document, binding_context=binding_context)
        self._refresh_preview()
        return resolved

    def set_main_map(self, map_document) -> bool:
        """Bind the live map document into the composition's MAIN_MAP.

        The data connection is a BINDING, not an undoable content edit —
        the layout history owns geometry/properties; the data source is the
        host's current document. Unbind with ``map_document=None``.
        """
        session = self._require_session()
        if session is None:
            return False
        target = None
        for element in session.document.elements:
            if element.element_type is ElementType.MAIN_MAP:
                target = element
                break
        if target is None:
            target = session.add_element(ElementType.MAIN_MAP)
        target.properties["map_document"] = map_document
        self._refresh_preview()
        self.composition_changed.emit(session.revision)
        return True

    # ------------------------------------------------------------------
    # element operations
    # ------------------------------------------------------------------

    def _add_element(self, etype: ElementType, properties: dict | None = None):
        if self.session is None:
            return None
        element = self.session.add_element(etype, properties=properties)
        self._refresh_all()
        self._select_element(element.id)
        return element

    def _delete_selected(self) -> None:
        session = self._require_session()
        if session is None:
            return
        element_id = self._selected_element_id()
        if element_id:
            try:
                session.remove_element(element_id)
            except ComposerError:
                logger.debug("delete refused (locked): %s", element_id)
                return
            self._refresh_all()

    def _duplicate_selected(self) -> None:
        session = self._require_session()
        if session is None:
            return
        element_id = self._selected_element_id()
        if element_id:
            try:
                clone = session.duplicate_element(element_id)
            except ComposerError:
                logger.debug("duplicate refused (locked): %s", element_id)
                return
            self._refresh_all()
            if clone is not None:
                self._select_element(clone.id)

    def _toggle_lock(self, element_id: str) -> None:
        """锁定/解锁选中组件（右键菜单入口；session 层可撤销命令）。"""
        session = self._require_session()
        if session is None:
            return
        element = session.document.get_element(element_id)
        if element is None:
            return
        session.set_locked(element_id, not element.locked)
        self._refresh_all()

    def _reorder(self, mode: str) -> None:
        session = self._require_session()
        if session is None:
            return
        element_id = self._selected_element_id()
        if not element_id:
            return
        if mode == "front":
            session.bring_to_front(element_id)
        elif mode == "back":
            session.send_to_back(element_id)
        elif mode == "raise":
            session.raise_element(element_id)
        self._refresh_all()
        self._select_element(element_id)

    def _undo(self) -> None:
        if self.session is not None and self.session.undo():
            self._refresh_all()

    def _redo(self) -> None:
        if self.session is not None and self.session.redo():
            self._refresh_all()

    # ------------------------------------------------------------------
    # property editing
    # ------------------------------------------------------------------

    def _apply_title(self) -> None:
        session = self._require_session()
        if session is None:
            return
        title = self.title_edit.text().strip()
        session.document.title = title
        title_elem = next(
            (e for e in session.document.elements if e.element_type is ElementType.TITLE),
            None,
        )
        if title_elem is not None and not title_elem.locked:
            try:
                session.configure_element(title_elem.id, {"text": title})
            except ComposerError:
                pass
        self._refresh_preview()
        self.composition_changed.emit(session.revision)

    def _apply_geometry(self, field: str, value: float) -> None:
        """Move/scale through the edit session — never a raw field write,
        so every geometry change stays undoable (component contract)."""
        if self._suppress_geometry_signals:
            return
        session = self._require_session()
        if session is None:
            return
        element_id = self._selected_element_id()
        if not element_id:
            return
        element = session.document.get_element(element_id)
        if element is None or element.locked:
            return
        try:
            if field in ("x", "y"):
                session.move_element(
                    element_id,
                    float(value) if field == "x" else element.x_mm,
                    float(value) if field == "y" else element.y_mm,
                )
            else:
                session.scale_element(
                    element_id,
                    max(1.0, float(value)) if field == "w" else element.width_mm,
                    max(1.0, float(value)) if field == "h" else element.height_mm,
                )
        except ComposerError:
            return
        self._refresh_preview()
        self.composition_changed.emit(session.revision)

    # -- schema 驱动属性编辑 ----------------------------------------------

    def _on_schema_value_changed(self, name: str, value: Any) -> None:
        if self._suppress_schema_signals:
            return
        session = self._require_session()
        element_id = self._selected_element_id()
        if session is None or not element_id:
            return
        element = session.document.get_element(element_id)
        if element is None or element.locked:
            return
        try:
            session.configure_element(element_id, {name: value})
        except ComposerError:
            return
        self._schema_dirty.discard(name)
        self._refresh_preview()
        self.composition_changed.emit(session.revision)
        if name == "chart_type":
            # 表格/JSON 序列编辑器随图表类型切换；延迟重建避免在信号
            # 处理中删除发送者控件。
            QTimer.singleShot(0, self._refresh_property_editor)

    def _on_schema_json_changed(self, name: str, text: str) -> None:
        try:
            value = json.loads(text) if text.strip() else []
        except ValueError:
            logger.warning("属性 %s 的 JSON 无效，忽略", name)
            return
        self._on_schema_value_changed(name, value)

    def _mark_schema_dirty(self, name: str) -> None:
        if not self._suppress_schema_signals:
            self._schema_dirty.add(name)

    def _commit_schema_edits(self) -> None:
        """提交多行文本编辑器中未落盘的修改（失焦时自动调用）。"""
        for name in list(self._schema_dirty):
            getter = self._schema_getters.get(name)
            if getter is None:
                continue
            self._on_schema_value_changed(name, getter())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusOut:
            self._commit_schema_edits()
        return super().eventFilter(watched, event)

    def _make_editor(
        self, prop: dict[str, Any], value: Any, element
    ) -> tuple[QWidget, Callable[[], Any]]:
        name = str(prop.get("name"))
        ptype = str(prop.get("type") or "str")
        if ptype == "number":
            spin = QDoubleSpinBox()
            spin.setRange(float(prop.get("min", -1e9)), float(prop.get("max", 1e9)))
            spin.setDecimals(2)
            spin.setSingleStep(0.1)
            try:
                spin.setValue(float(0.0 if value is None else value))
            except (TypeError, ValueError):
                spin.setValue(0.0)
            spin.valueChanged.connect(lambda v, n=name: self._on_schema_value_changed(n, v))
            return spin, lambda s=spin: s.value()
        if ptype == "bool":
            box = QCheckBox()
            box.setChecked(bool(value))
            box.toggled.connect(lambda v, n=name: self._on_schema_value_changed(n, v))
            return box, lambda b=box: b.isChecked()
        if ptype == "choices":
            combo = QComboBox()
            choices = [str(c) for c in (prop.get("choices") or [])]
            combo.addItems(choices)
            current = str(value or (choices[0] if choices else ""))
            if current and current not in choices:
                combo.insertItem(0, current)
            combo.setCurrentText(current)
            combo.currentIndexChanged.connect(
                lambda _i, n=name, c=combo: self._on_schema_value_changed(n, c.currentText())
            )
            return combo, lambda c=combo: c.currentText()
        if ptype == "text":
            edit = QTextEdit()
            edit.setPlainText(str(value if value is not None else ""))
            edit.setMaximumHeight(64)
            edit.textChanged.connect(lambda n=name: self._mark_schema_dirty(n))
            edit.installEventFilter(self)
            return edit, lambda e=edit: e.toPlainText()
        if ptype == "list":
            if (
                element.element_type is ElementType.STAT_CHART
                and name == "series"
                and str(element.properties.get("chart_type") or "bar") in _TABLE_SERIES_CHART_TYPES
            ):
                return self._make_series_table_editor(element)
            line = QLineEdit()
            try:
                line.setText(json.dumps(value if value is not None else [], ensure_ascii=False))
            except (TypeError, ValueError):
                line.setText("[]")
            line.editingFinished.connect(
                lambda n=name, l=line: self._on_schema_json_changed(n, l.text())
            )
            return line, lambda l=line: l.text()
        # str（及其它未知类型）→ 单行文本。
        line = QLineEdit()
        line.setText(str(value if value is not None else ""))
        line.editingFinished.connect(
            lambda n=name, l=line: self._on_schema_value_changed(n, l.text())
        )
        return line, lambda l=line: l.text()

    def _make_series_table_editor(
        self, element
    ) -> tuple[QWidget, Callable[[], Any]]:
        """STAT_CHART 的 label/value 两列表格（增删行，直接 configure）。"""
        series = [
            dict(s) for s in (element.properties.get("series") or ()) if isinstance(s, dict)
        ]
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        table = QTableWidget(max(1, len(series)), 2)
        table.setHorizontalHeaderLabels(["标签", "数值"])
        table.verticalHeader().setVisible(False)
        table.setMaximumHeight(120)
        self._suppress_schema_signals = True
        for row, entry in enumerate(series):
            table.setItem(row, 0, QTableWidgetItem(str(entry.get("label", ""))))
            try:
                table.setItem(row, 1, QTableWidgetItem(f"{float(entry.get('value', 0.0)):g}"))
            except (TypeError, ValueError):
                table.setItem(row, 1, QTableWidgetItem("0"))
        for row in range(len(series), max(1, len(series))):
            for col in (0, 1):
                table.setItem(row, col, QTableWidgetItem(""))
        self._suppress_schema_signals = False

        def collect() -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            for row in range(table.rowCount()):
                label = (table.item(row, 0).text() if table.item(row, 0) else "").strip()
                raw = table.item(row, 1).text() if table.item(row, 1) else "0"
                if not label and not raw.strip():
                    continue
                try:
                    number = float(raw)
                except ValueError:
                    number = 0.0
                items.append({"label": label, "value": number})
            return items

        def on_cell_changed(*_args) -> None:
            if self._suppress_schema_signals:
                return
            self._on_schema_value_changed("series", collect())

        table.cellChanged.connect(on_cell_changed)

        def add_row() -> None:
            self._suppress_schema_signals = True
            table.insertRow(table.rowCount())
            row = table.rowCount() - 1
            table.setItem(row, 0, QTableWidgetItem(""))
            table.setItem(row, 1, QTableWidgetItem("0"))
            self._suppress_schema_signals = False
            self._on_schema_value_changed("series", collect())

        def remove_row() -> None:
            row = table.currentRow()
            if row < 0:
                row = table.rowCount() - 1
            if row >= 0:
                table.removeRow(row)
                self._on_schema_value_changed("series", collect())

        button_row = QHBoxLayout()
        add_btn = QToolButton()
        add_btn.setText("＋行")
        add_btn.clicked.connect(add_row)
        remove_btn = QToolButton()
        remove_btn.setText("－行")
        remove_btn.clicked.connect(remove_row)
        button_row.addWidget(add_btn)
        button_row.addWidget(remove_btn)
        button_row.addStretch(1)
        layout.addWidget(table)
        layout.addLayout(button_row)
        return container, collect

    # ------------------------------------------------------------------
    # list/preview refresh
    # ------------------------------------------------------------------

    def _refresh_all(self) -> None:
        self._refresh_list()
        self._refresh_history_state()
        self._refresh_property_editor()
        self._refresh_preview()

    def _refresh_list(self) -> None:
        session = self._require_session()
        if session is None:
            return
        self._suppress_item_signals = True
        selected = self._selected_element_id()
        self.element_list.clear()
        for element in reversed(session.document.elements):
            label = ELEMENT_TYPE_LABELS.get(element.element_type, element.element_type.value)
            raw_type = element.properties.get("_raw_element_type")
            if raw_type:
                # 前向兼容载体：显示真实（未知）类型名。
                label = f"{raw_type}（未支持）"
            if element.locked:
                label += "（锁定）"
            if not element.visible:
                label += "（隐藏）"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, element.id)
            item.setCheckState(
                Qt.CheckState.Checked if element.visible else Qt.CheckState.Unchecked
            )
            self.element_list.addItem(item)
        self._suppress_item_signals = False
        if selected:
            self._select_element(selected)

    def _select_element(self, element_id: str) -> None:
        for row in range(self.element_list.count()):
            item = self.element_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == element_id:
                self.element_list.setCurrentRow(row)
                break
        self._refresh_property_editor()

    def _on_element_selected(self, _row: int) -> None:
        if self._suppress_item_signals:
            return
        self._refresh_property_editor()

    def _on_element_menu(self, pos) -> None:
        item = self.element_list.itemAt(pos)
        if item is None or self.session is None:
            return
        element_id = item.data(Qt.ItemDataRole.UserRole)
        element = self.session.document.get_element(element_id)
        if element is None:
            return
        menu = QMenu(self)
        lock = menu.addAction("解锁" if element.locked else "锁定")
        toggle = menu.addAction("显示/隐藏")
        duplicate = menu.addAction("复制组件")
        front = menu.addAction("置顶")
        back = menu.addAction("置底")
        chosen = menu.exec(self.element_list.mapToGlobal(pos))
        if chosen is lock:
            self._toggle_lock(element_id)
        elif chosen is toggle:
            self.session.set_element_visible(element_id, not element.visible)
            self._refresh_all()
        elif chosen is duplicate:
            try:
                self.session.duplicate_element(element_id)
            except ComposerError:
                logger.debug("duplicate refused (locked): %s", element_id)
                return
            self._refresh_all()
        elif chosen is front:
            self.session.bring_to_front(element_id)
            self._refresh_all()
        elif chosen is back:
            self.session.send_to_back(element_id)
            self._refresh_all()

    def _refresh_history_state(self) -> None:
        session = self._require_session()
        if session is None:
            self.undo_btn.setEnabled(False)
            self.redo_btn.setEnabled(False)
            return
        self.undo_btn.setEnabled(session.can_undo())
        self.redo_btn.setEnabled(session.can_redo())

    def _clear_schema_rows(self) -> None:
        while self.property_form.rowCount() > _STATIC_FORM_ROWS + 1:  # + 锁定提示行
            self.property_form.removeRow(self.property_form.rowCount() - 1)
        self._schema_editors.clear()
        self._schema_getters.clear()
        self._schema_dirty.clear()

    def _refresh_property_editor(self) -> None:
        session = self._require_session()
        element_id = self._selected_element_id()
        element = (
            session.document.get_element(element_id)
            if session is not None and element_id
            else None
        )
        has = element is not None
        locked = has and element.locked
        editable = has and not locked
        self._suppress_geometry_signals = True
        for spin in (self.x_spin, self.y_spin, self.w_spin, self.h_spin):
            spin.setEnabled(editable)
        self.lock_hint.setVisible(bool(locked))
        self._clear_schema_rows()
        if element is None:
            self._suppress_geometry_signals = False
            return
        self.x_spin.setValue(element.x_mm)
        self.y_spin.setValue(element.y_mm)
        self.w_spin.setValue(element.width_mm)
        self.h_spin.setValue(element.height_mm)
        self._suppress_geometry_signals = False
        # schema 驱动行：编辑器由 registry property_schema 生成（零手写）。
        spec = get_spec(element.element_type)
        self._suppress_schema_signals = True
        try:
            for prop in spec.property_schema:
                name = str(prop.get("name"))
                editor, getter = self._make_editor(prop, element.properties.get(name), element)
                editor.setEnabled(editable)
                self._schema_editors[name] = editor
                self._schema_getters[name] = getter
                self.property_form.addRow(str(prop.get("label") or name), editor)
        finally:
            self._suppress_schema_signals = False

    def _refresh_preview(self) -> None:
        session = self._require_session()
        if session is None:
            self.preview_label.setText("尚无组图")
            self.preview_label.setPixmap(QPixmap())
            return
        try:
            svg = composer_renderer.render_to_svg(session.document)
        except Exception:
            logger.debug("composition preview failed", exc_info=True)
            self.preview_label.setText("预览渲染失败")
            self.preview_label.setPixmap(QPixmap())
            return
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not renderer.isValid():
            self.preview_label.setText("预览渲染失败")
            self.preview_label.setPixmap(QPixmap())
            return
        target = self.preview_label.size()
        if target.width() < 10 or target.height() < 10:
            target.setWidth(240)
            target.setHeight(160)
        pixmap = QPixmap(target)
        pixmap.fill(0xFFFFFFFF)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            renderer.render(painter)
        finally:
            painter.end()
        self.preview_label.setPixmap(pixmap)

    # ------------------------------------------------------------------
    # persistence / export
    # ------------------------------------------------------------------

    def _save_json(self) -> None:
        session = self._require_session()
        if session is None:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self, "保存组图文档", "composition.json", "Composition JSON (*.json)"
        )
        if not path:
            return
        Path(path).write_text(
            json.dumps(session.document.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_json(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "打开组图文档", "", "Composition JSON (*.json)"
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            doc = MapCompositionDocument.from_dict(payload)
        except (OSError, ValueError):
            logger.exception("composition load failed")
            return
        self.set_document(doc)

    def _export(self) -> None:
        session = self._require_session()
        if session is None:
            return
        fmt = self.export_combo.currentData() or "png"
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "导出组图",
            f"composition.{fmt}",
            f"(*.{fmt})",
        )
        if not path:
            return
        try:
            out = export_composition(session.document, path, fmt=fmt, dpi=float(self.dpi_spin.value()))
        except Exception:
            logger.exception("composition export failed")
            return
        self.composition_exported.emit(str(out))
