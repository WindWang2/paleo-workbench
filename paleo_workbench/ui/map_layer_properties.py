"""One lightweight, renderer-neutral layer properties dialog."""

from __future__ import annotations

import json
from typing import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QScrollArea,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui import tokens

__all__ = ["MapLayerPropertiesDialog"]


class MapLayerPropertiesDialog(QDialog):
    """Edit layer presentation through one common General→Provenance layout.

    Callers remain responsible for applying the emitted payload to `MapScene` and
    `VectorLayer`; the dialog intentionally holds no parallel layer state.
    """

    properties_applied = Signal(str, object)

    def __init__(self, layer, *, style: Mapping[str, object] | None = None, parent=None,
                 features: tuple[Mapping[str, object], ...] = (),
                 fields: tuple[str, ...] = ()) -> None:
        super().__init__(parent)
        self.setObjectName("MapLayerPropertiesDialog")
        self.setWindowTitle(f"图层属性 — {layer.name}")
        self._layer_id = str(layer.id)
        self._layer_name = str(layer.name)
        self._layer_type = getattr(layer.type, "name", str(layer.type))
        self._is_scalar = self._layer_type == "ScalarGrid"
        self._style = dict(style or {})
        self._features = tuple(features)
        self._fields = tuple(str(name) for name in fields)
        self._crs = str(layer.crs)
        self._pending_qgis_style: dict[str, object] | None = None
        style = dict(style or {})

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        # -- 常规：基本信息 + 显示 + 版本（原 General/Source/Rendering 三张
        # 碎片 tab 合一；图层属性窗口从此 4 张整理过的页）。
        general = QWidget(self)
        general_layout = QVBoxLayout(general)
        general_layout.setSpacing(12)

        info_group = QGroupBox("基本信息", general)
        info_form = QFormLayout(info_group)
        info_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name_edit = QLineEdit(str(layer.name), general)
        self.crs_edit = QLineEdit(str(layer.crs), general)
        info_form.addRow("名称", self.name_edit)
        info_form.addRow("图层类型", QLabel(self._layer_type, info_group))
        info_form.addRow("数据来源", QLabel(layer.source_ref or "工程管理", info_group))
        info_form.addRow("坐标系", self.crs_edit)
        general_layout.addWidget(info_group)

        display_group = QGroupBox("显示", general)
        display_form = QFormLayout(display_group)
        self.opacity_spin = QDoubleSpinBox(general)
        self.opacity_spin.setRange(0.0, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(float(layer.opacity))
        display_form.addRow("不透明度（0–1）", self.opacity_spin)
        general_layout.addWidget(display_group)

        revision_group = QGroupBox("版本（只读）", general)
        revision_form = QFormLayout(revision_group)
        revision_form.addRow("数据修订", QLabel(str(layer.data_revision), revision_group))
        revision_form.addRow("样式修订", QLabel(str(layer.style_revision), revision_group))
        general_layout.addWidget(revision_group)
        general_layout.addStretch(1)
        self.tabs.addTab(general, "常规")

        symbology = QWidget(self)
        symbology_form = QFormLayout(symbology)
        if self._is_scalar:
            color_range = list(style.get("color_range") or (0.0, 1.0))
            if len(color_range) < 2:
                color_range = [0.0, 1.0]
            self.color_ramp_combo = QComboBox(symbology)
            self.color_ramp_combo.addItems(["default", "grayscale", "warm_cool"])
            self.color_ramp_combo.setCurrentText(str(style.get("color_ramp") or "default"))
            self.range_min_spin = QDoubleSpinBox(symbology)
            self.range_max_spin = QDoubleSpinBox(symbology)
            for control, value in ((self.range_min_spin, color_range[0]), (self.range_max_spin, color_range[1])):
                control.setRange(-1.0e18, 1.0e18)
                control.setDecimals(8)
                control.setValue(float(value))
            self.gamma_spin = QDoubleSpinBox(symbology)
            self.gamma_spin.setRange(0.01, 100.0)
            self.gamma_spin.setDecimals(4)
            self.gamma_spin.setValue(float(style.get("gamma") or 1.0))
            self.nodata_combo = QComboBox(symbology)
            self.nodata_combo.addItems(["transparent"])
            self.nodata_combo.setCurrentText(str(style.get("nodata") or "transparent"))
            symbology_form.addRow("色带", self.color_ramp_combo)
            symbology_form.addRow("值域最小", self.range_min_spin)
            symbology_form.addRow("值域最大", self.range_max_spin)
            symbology_form.addRow("伽马", self.gamma_spin)
            symbology_form.addRow("无数据值", self.nodata_combo)
        else:
            from paleo_workbench.mapping.qgis_style import (
                QgisStylePayload,
                qgis_bridge_available,
            )

            self._qgis_symbology = qgis_bridge_available()
            self._style_payload = QgisStylePayload.from_dict(style.get("qgis_style"))
            if self._qgis_symbology:
                self._build_qgis_symbology_tab(symbology)
            else:
                self._build_legacy_symbology_tab(symbology, style)
        self.tabs.addTab(symbology, "符号系统")

        labels = QWidget(self)
        labels_form = QFormLayout(labels)
        label_style = dict(style.get("labels") or {})
        self.label_field_edit = QLineEdit(str(label_style.get("field") or ""), labels)
        self.label_size_spin = QDoubleSpinBox(labels)
        self.label_size_spin.setRange(1.0, 96.0)
        self.label_size_spin.setValue(float(label_style.get("size") or 10.0))
        labels_form.addRow("标注字段", self.label_field_edit)
        labels_form.addRow("字号（pt）", self.label_size_spin)
        if self._is_scalar:
            self.label_field_edit.setEnabled(False)
            self.label_size_spin.setEnabled(False)
        self.tabs.addTab(labels, "标注")

        # 元数据：逐键格式化（替代原先的整包 dict 字符串倾倒）。
        metadata = QWidget(self)
        metadata_layout = QVBoxLayout(metadata)
        provenance_group = QGroupBox("来源", metadata)
        provenance_form = QFormLayout(provenance_group)
        provenance_form.addRow(
            "出处", QLabel(layer.provenance_ref or "工程管理", provenance_group))
        metadata_layout.addWidget(provenance_group)

        meta_dict = {str(k): v for k, v in dict(layer.metadata or {}).items()}
        if meta_dict:
            meta_group = QGroupBox("图层属性元数据（只读）", metadata)
            meta_form = QFormLayout(meta_group)
            meta_form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for key in sorted(meta_dict):
                value = meta_dict[key]
                value_label = QLabel("" if value is None else str(value), meta_group)
                value_label.setWordWrap(True)
                meta_form.addRow(key, value_label)
            scroll = QScrollArea(metadata)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            inner = QWidget()
            inner_layout = QVBoxLayout(inner)
            inner_layout.setContentsMargins(0, 0, 0, 0)
            inner_layout.addWidget(meta_group)
            scroll.setWidget(inner)
            metadata_layout.addWidget(scroll, 1)
        metadata_layout.addStretch(1)
        self.tabs.addTab(metadata, "元数据")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("应用")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        # 初始尺寸：表单分组直接铺开，无需手动拉大。
        self.resize(620, 560)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        buttons.accepted.connect(self._accept_after_apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_qgis_symbology_tab(self, symbology: QWidget) -> None:
        """Professional path: the native QGIS editors own symbology editing."""
        from paleo_workbench.ui.map_symbology_bridge import (
            qgis_symbology_available,
        )

        form = QFormLayout(symbology)
        renderer_name = "QGIS renderer"
        if self._style_payload is not None:
            info = self._renderer_info(self._style_payload.renderer_xml)
            if info is not None:
                renderer_name = str(info.get("type") or renderer_name)
        status = QLabel(
            f"当前权威样式：{renderer_name}\n"
            + (
                "点击下方按钮打开 QGIS 原生符号编辑器。"
                if qgis_symbology_available()
                else "QGIS 桥未构建——符号编辑不可用。"
            ),
            symbology,
        )
        status.setWordWrap(True)
        form.addRow("", status)
        self.qgis_edit_button = QPushButton("打开 QGIS 符号编辑器…", symbology)
        self.qgis_edit_button.setEnabled(qgis_symbology_available())
        self.qgis_edit_button.clicked.connect(self._open_qgis_editor)
        form.addRow("", self.qgis_edit_button)
        self.symbology_error_label = QLabel("")
        self.symbology_error_label.setWordWrap(True)
        self.symbology_error_label.setStyleSheet(
            f"color: {tokens.ERROR_RED}; font-size: 11px;"
        )
        self.symbology_error_label.hide()
        form.addRow("", self.symbology_error_label)
        # The pending payload produced by the native editor, applied on Apply/OK.
        self._pending_qgis_style: dict[str, object] | None = None

    def _renderer_info(self, renderer_xml: str) -> dict[str, object] | None:
        try:
            import qgis_render_bridge as native
        except ImportError:
            return None
        try:
            return dict(native.renderer_info(renderer_xml) or {})
        except Exception:  # noqa: BLE001 — display-only lookup must never raise
            return None

    def _open_qgis_editor(self) -> None:
        from paleo_workbench.ui.map_symbology_bridge import (
            SymbologyBridgeError,
            open_renderer_properties,
        )

        style = dict(self._style or {})
        payload_dict: dict[str, object] | None = None
        if self._pending_qgis_style is not None:
            payload_dict = dict(self._pending_qgis_style)
        elif self._style_payload is not None:
            payload_dict = self._style_payload.to_dict()
        if payload_dict is not None:
            style["qgis_style"] = payload_dict
        try:
            result = open_renderer_properties(
                self,
                title=f"Symbology — {self._layer_name}",
                features=self._features,
                crs=self._crs,
                fields=self._fields,
                style=style,
            )
        except SymbologyBridgeError as exc:
            self.symbology_error_label.setText(str(exc))
            self.symbology_error_label.show()
            return
        if result is None:
            return
        self._pending_qgis_style = dict(result["qgis_style"])
        opacity = float(result.get("opacity", 1.0))
        if 0.0 <= opacity <= 1.0:
            self.opacity_spin.setValue(opacity)
        self.apply()

    def _build_legacy_symbology_tab(self, symbology: QWidget, style: dict) -> None:
        """Fallback path (no QGIS bridge): the minimal quick-fields form."""
        from paleo_workbench.mapping.map_styles import LinePattern, MarkerSymbol

        symbology_form = QFormLayout(symbology)
        self.fill_edit = QLineEdit(str(style.get("fill") or ""), symbology)
        self.stroke_edit = QLineEdit(str(style.get("stroke") or ""), symbology)
        self.stroke_width_spin = QDoubleSpinBox(symbology)
        self.stroke_width_spin.setRange(0.0, 100.0)
        self.stroke_width_spin.setValue(float(style.get("stroke_width") or 1.0))
        self.line_pattern_combo = QComboBox(symbology)
        for pattern in LinePattern:
            self.line_pattern_combo.addItem(pattern.value, pattern.value)
        self.line_pattern_combo.setCurrentText(
            str(style.get("line_pattern") or LinePattern.SOLID.value)
        )
        self.marker_combo = QComboBox(symbology)
        for marker in MarkerSymbol:
            self.marker_combo.addItem(marker.value, marker.value)
        self.marker_combo.setCurrentText(
            str(style.get("marker") or MarkerSymbol.CIRCLE.value)
        )
        self.marker_size_spin = QDoubleSpinBox(symbology)
        self.marker_size_spin.setRange(0.5, 96.0)
        self.marker_size_spin.setValue(float(style.get("marker_size") or 6.0))
        self.renderer_combo = QComboBox(symbology)
        self.renderer_combo.addItems(["single", "categorized", "graduated"])
        self.renderer_combo.setCurrentText(str(style.get("renderer") or "single"))
        self.classification_field_edit = QLineEdit(str(style.get("field") or ""), symbology)
        self.classes_edit = QPlainTextEdit(symbology)
        self.classes_edit.setPlaceholderText('{"delta": "#6c8ebf"} or [{"lower": 0, "upper": 1, "color": "#6c8ebf"}]')
        if style.get("renderer") == "categorized":
            self.classes_edit.setPlainText(json.dumps(style.get("categories") or {}, ensure_ascii=False))
        elif style.get("renderer") == "graduated":
            self.classes_edit.setPlainText(json.dumps(style.get("ranges") or [], ensure_ascii=False))
        symbology_form.addRow("填充色 / 色带", self.fill_edit)
        symbology_form.addRow("边线色", self.stroke_edit)
        symbology_form.addRow("边线宽", self.stroke_width_spin)
        symbology_form.addRow("线型", self.line_pattern_combo)
        symbology_form.addRow("点标记", self.marker_combo)
        symbology_form.addRow("标记大小", self.marker_size_spin)
        symbology_form.addRow("渲染器", self.renderer_combo)
        symbology_form.addRow("分类字段", self.classification_field_edit)
        symbology_form.addRow("分级（JSON）", self.classes_edit)
        self.classes_error_label = QLabel("")
        self.classes_error_label.setWordWrap(True)
        self.classes_error_label.setStyleSheet(
            f"color: {tokens.ERROR_RED}; font-size: 11px;"
        )
        self.classes_error_label.hide()
        symbology_form.addRow("", self.classes_error_label)
        self.classes_edit.textChanged.connect(self.classes_error_label.hide)

    def payload(self) -> dict[str, object]:
        labels: dict[str, object] = {}
        if self.label_field_edit.text().strip():
            labels = {"field": self.label_field_edit.text().strip(), "size": self.label_size_spin.value()}
        if self._is_scalar:
            return {
                "name": self.name_edit.text().strip() or self._layer_id,
                "crs": self.crs_edit.text().strip(),
                "opacity": self.opacity_spin.value(),
                "scalar_style": {
                    "color_ramp": self.color_ramp_combo.currentText(),
                    "color_range": [self.range_min_spin.value(), self.range_max_spin.value()],
                    "gamma": self.gamma_spin.value(),
                    "nodata": self.nodata_combo.currentText(),
                },
            }
        if getattr(self, "_qgis_symbology", False):
            result: dict[str, object] = {
                "name": self.name_edit.text().strip() or self._layer_id,
                "crs": self.crs_edit.text().strip(),
                "opacity": self.opacity_spin.value(),
            }
            if self._pending_qgis_style is not None:
                result["qgis_style"] = dict(self._pending_qgis_style)
            # The native symbology editor owns renderer payloads only; Apply
            # must carry through the layer's existing label configuration or
            # every OK click silently wipes it (#929).
            existing_labels = (self._style or {}).get("labels")
            if isinstance(existing_labels, Mapping) and existing_labels:
                result["labels"] = dict(existing_labels)
            return result
        style: dict[str, object] = {
            "fill": self.fill_edit.text().strip(),
            "stroke": self.stroke_edit.text().strip(),
            "stroke_width": self.stroke_width_spin.value(),
            "line_pattern": self.line_pattern_combo.currentText(),
            "marker": self.marker_combo.currentText(),
            "marker_size": self.marker_size_spin.value(),
            "renderer": self.renderer_combo.currentText(),
            "field": self.classification_field_edit.text().strip(),
            "labels": labels,
        }
        classes = self.classes_edit.toPlainText().strip()
        if classes:
            try:
                parsed = json.loads(classes)
                if style["renderer"] == "categorized" and isinstance(parsed, dict):
                    style["categories"] = parsed
                elif style["renderer"] == "graduated" and isinstance(parsed, list):
                    style["ranges"] = parsed
            except json.JSONDecodeError:
                # Leave the current renderer classes unchanged; the host applies
                # a valid independent style change instead of corrupting state.
                pass
        return {
            "name": self.name_edit.text().strip() or self._layer_id,
            "crs": self.crs_edit.text().strip(),
            "opacity": self.opacity_spin.value(),
            "style": style,
        }

    def classes_json_error(self) -> str | None:
        """Human-readable parse error for the Classes (JSON) field, or None."""
        if self._is_scalar or getattr(self, "_qgis_symbology", False):
            return None
        classes = self.classes_edit.toPlainText().strip()
        if not classes:
            return None
        try:
            json.loads(classes)
        except json.JSONDecodeError as exc:
            return f"无效的分级 JSON：{exc}"
        return None

    def apply(self) -> None:
        error = self.classes_json_error()
        if error:
            self.classes_error_label.setText(error)
            self.classes_error_label.show()
            return
        self.properties_applied.emit(self._layer_id, self.payload())

    def _accept_after_apply(self) -> None:
        # Never close the dialog over a silently discarded structured input:
        # show an inline error next to the Classes field instead (#426).
        error = self.classes_json_error()
        if error:
            self.classes_error_label.setText(error)
            self.classes_error_label.show()
            return
        self.apply()
        self.accept()
