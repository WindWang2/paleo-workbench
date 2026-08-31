"""Composition authoring panel (P0-D UI): template → components → export.

A right-dock workbench panel over the composition core
(:mod:`paleo_workbench.mapping.composer.components`). Every mutation goes
through the :class:`CompositionEditSession` (one undo/redo history), the
preview re-renders from the session revision (never a stale cache), and
exports honor the physical-size + DPI contract. The panel is deliberately
style-plain: professional cartography authoring, not dashboard chrome.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.composer.components import (
    CompositionEditSession,
    CompositionFactory,
    bind_template,
)
from paleo_workbench.mapping.composer.export import export_composition
from paleo_workbench.mapping.composer.models import (
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.renderer import composer_renderer
from paleo_workbench.mapping.composer.templates import (
    TEMPLATE_LIBRARY,
    instantiate_template,
)
from paleo_workbench.ui import tokens

logger = logging.getLogger(__name__)

# Chinese labels for the component vocabulary.
ELEMENT_TYPE_LABELS: dict[ElementType, str] = {
    ElementType.MAIN_MAP: "主图",
    ElementType.LEGEND: "图例",
    ElementType.NORTH_ARROW: "指北针",
    ElementType.SCALE_BAR: "比例尺",
    ElementType.GRID: "坐标网格",
    ElementType.TITLE: "图名",
    ElementType.ANNOTATION: "注释",
    ElementType.TIMESCALE: "年代地层",
    ElementType.TEXT: "文本",
    ElementType.IMAGE: "图像",
    ElementType.INSET_MAP: "附图",
    ElementType.STAT_CHART: "统计图",
    ElementType.METADATA: "责任表",
    ElementType.COLORBAR: "色标",
}

_TEXT_PROPERTY_TYPES = {
    ElementType.TITLE: ("text", "font_size"),
    ElementType.TEXT: ("text", "font_size"),
    ElementType.ANNOTATION: ("text", "font_size"),
}

_RANGED_PROPERTY_TYPES = {
    ElementType.COLORBAR: ("title", "min", "max"),
    ElementType.SCALE_BAR: ("length_km",),
    ElementType.STAT_CHART: ("title",),
    ElementType.METADATA: (),
    ElementType.IMAGE: (),
    ElementType.INSET_MAP: (),
}


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
        self.element_list.setToolTip("组图组件（双击重命名不可用；右键菜单支持复制/层级）")
        self.element_list.currentRowChanged.connect(self._on_element_selected)
        self.element_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.element_list.customContextMenuRequested.connect(self._on_element_menu)
        outer.addWidget(self.element_list, 2)

        element_row = QHBoxLayout()
        self.add_btn = QToolButton()
        self.add_btn.setText("＋组件")
        self.add_btn.setToolTip("添加组图组件")
        self.add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        add_menu = QMenu(self.add_btn)
        for etype, label in ELEMENT_TYPE_LABELS.items():
            add_menu.addAction(label, lambda checked=False, t=etype: self._add_element(t))
        self.add_btn.setMenu(add_menu)
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
        self.text_edit = QLineEdit()
        self.text_edit.editingFinished.connect(self._apply_text_property)
        self.property_form.addRow("文本", self.text_edit)
        self.font_spin = self._mm_spin(1.0, 72.0)
        self.font_spin.valueChanged.connect(self._apply_font_size)
        self.property_form.addRow("字号", self.font_spin)
        self.min_spin = QDoubleSpinBox()
        self.min_spin.setRange(-1e12, 1e12)
        self.min_spin.valueChanged.connect(lambda v: self._apply_ranged("min", v))
        self.property_form.addRow("最小值", self.min_spin)
        self.max_spin = QDoubleSpinBox()
        self.max_spin.setRange(-1e12, 1e12)
        self.max_spin.valueChanged.connect(lambda v: self._apply_ranged("max", v))
        self.property_form.addRow("最大值", self.max_spin)

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

    # ------------------------------------------------------------------
    # element operations
    # ------------------------------------------------------------------

    def _add_element(self, etype: ElementType) -> None:
        if self.session is None:
            return
        element = self.session.add_element(etype)
        self._refresh_all()
        self._select_element(element.id)

    def _delete_selected(self) -> None:
        session = self._require_session()
        if session is None:
            return
        element_id = self._selected_element_id()
        if element_id:
            session.remove_element(element_id)
            self._refresh_all()

    def _duplicate_selected(self) -> None:
        session = self._require_session()
        if session is None:
            return
        element_id = self._selected_element_id()
        if element_id:
            clone = session.duplicate_element(element_id)
            self._refresh_all()
            if clone is not None:
                self._select_element(clone.id)

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
        if title_elem is not None:
            title_elem.properties["text"] = title
        self._refresh_preview()
        self.composition_changed.emit(session.revision)

    def _apply_geometry(self, field: str, value: float) -> None:
        session = self._require_session()
        if session is None:
            return
        element_id = self._selected_element_id()
        if not element_id:
            return
        element = session.document.get_element(element_id)
        if element is None:
            return
        if field == "x":
            element.x_mm = float(value)
        elif field == "y":
            element.y_mm = float(value)
        elif field == "w":
            element.width_mm = max(1.0, float(value))
        elif field == "h":
            element.height_mm = max(1.0, float(value))
        self._refresh_preview()
        self.composition_changed.emit(session.revision)

    def _apply_text_property(self) -> None:
        session = self._require_session()
        element_id = self._selected_element_id()
        if session is None or not element_id:
            return
        element = session.document.get_element(element_id)
        if element is not None and element.element_type in _TEXT_PROPERTY_TYPES:
            session.configure_element(element_id, {"text": self.text_edit.text()})
            self._refresh_preview()
            self.composition_changed.emit(session.revision)

    def _apply_font_size(self, value: float) -> None:
        session = self._require_session()
        element_id = self._selected_element_id()
        if session is None or not element_id:
            return
        element = session.document.get_element(element_id)
        if element is not None and element.element_type in _TEXT_PROPERTY_TYPES:
            session.configure_element(element_id, {"font_size": float(value)})
            self._refresh_preview()
            self.composition_changed.emit(session.revision)

    def _apply_ranged(self, key: str, value: float) -> None:
        session = self._require_session()
        element_id = self._selected_element_id()
        if session is None or not element_id:
            return
        element = session.document.get_element(element_id)
        if element is None or element.element_type not in _RANGED_PROPERTY_TYPES:
            return
        if key in _RANGED_PROPERTY_TYPES[element.element_type]:
            session.configure_element(element_id, {key: float(value)})
            self._refresh_preview()
            self.composition_changed.emit(session.revision)

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
        toggle = menu.addAction("显示/隐藏")
        duplicate = menu.addAction("复制组件")
        front = menu.addAction("置顶")
        back = menu.addAction("置底")
        chosen = menu.exec(self.element_list.mapToGlobal(pos))
        if chosen is toggle:
            element.visible = not element.visible
            self._refresh_all()
        elif chosen is duplicate:
            self.session.duplicate_element(element_id)
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

    def _refresh_property_editor(self) -> None:
        session = self._require_session()
        element_id = self._selected_element_id()
        element = (
            session.document.get_element(element_id)
            if session is not None and element_id
            else None
        )
        has = element is not None
        for spin in (self.x_spin, self.y_spin, self.w_spin, self.h_spin):
            spin.setEnabled(has)
        self.text_edit.setEnabled(False)
        self.font_spin.setEnabled(False)
        self.min_spin.setEnabled(False)
        self.max_spin.setEnabled(False)
        if element is None:
            return
        self.x_spin.setValue(element.x_mm)
        self.y_spin.setValue(element.y_mm)
        self.w_spin.setValue(element.width_mm)
        self.h_spin.setValue(element.height_mm)
        if element.element_type in _TEXT_PROPERTY_TYPES:
            self.text_edit.setEnabled(True)
            self.text_edit.setText(str(element.properties.get("text") or ""))
            self.font_spin.setEnabled(True)
            self.font_spin.setValue(float(element.properties.get("font_size") or 4.0))
        if element.element_type is ElementType.COLORBAR:
            self.min_spin.setEnabled(True)
            self.max_spin.setEnabled(True)
            self.min_spin.setValue(float(element.properties.get("min") or 0.0))
            self.max_spin.setValue(float(element.properties.get("max") or 1.0))

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
