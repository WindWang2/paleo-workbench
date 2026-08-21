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
        self.setWindowTitle(f"Layer Properties — {layer.name}")
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

        general = QWidget(self)
        general_form = QFormLayout(general)
        self.name_edit = QLineEdit(str(layer.name), general)
        self.crs_edit = QLineEdit(str(layer.crs), general)
        self.opacity_spin = QDoubleSpinBox(general)
        self.opacity_spin.setRange(0.0, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(float(layer.opacity))
        general_form.addRow("Name", self.name_edit)
        general_form.addRow("CRS", self.crs_edit)
        general_form.addRow("Opacity", self.opacity_spin)
        self.tabs.addTab(general, "General")

        source = QWidget(self)
        source_form = QFormLayout(source)
        source_form.addRow("Source", QLabel(layer.source_ref or "managed", source))
        source_form.addRow("Layer type", QLabel(self._layer_type, source))
        self.tabs.addTab(source, "Source")

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
            symbology_form.addRow("Color ramp", self.color_ramp_combo)
            symbology_form.addRow("Range minimum", self.range_min_spin)
            symbology_form.addRow("Range maximum", self.range_max_spin)
            symbology_form.addRow("Gamma", self.gamma_spin)
            symbology_form.addRow("NoData", self.nodata_combo)
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
        self.tabs.addTab(symbology, "Symbology")

        labels = QWidget(self)
        labels_form = QFormLayout(labels)
        label_style = dict(style.get("labels") or {})
        self.label_field_edit = QLineEdit(str(label_style.get("field") or ""), labels)
        self.label_size_spin = QDoubleSpinBox(labels)
        self.label_size_spin.setRange(1.0, 96.0)
        self.label_size_spin.setValue(float(label_style.get("size") or 10.0))
        labels_form.addRow("Label field", self.label_field_edit)
        labels_form.addRow("Label size", self.label_size_spin)
        if self._is_scalar:
            self.label_field_edit.setEnabled(False)
            self.label_size_spin.setEnabled(False)
        self.tabs.addTab(labels, "Labels")

        rendering = QWidget(self)
        rendering_form = QFormLayout(rendering)
        rendering_form.addRow("Data revision", QLabel(str(layer.data_revision), rendering))
        rendering_form.addRow("Style revision", QLabel(str(layer.style_revision), rendering))
        self.tabs.addTab(rendering, "Rendering")

        metadata = QWidget(self)
        metadata_form = QFormLayout(metadata)
        metadata_form.addRow("Metadata", QLabel(str(dict(layer.metadata)), metadata))
        metadata_form.addRow("Provenance", QLabel(layer.provenance_ref or "managed", metadata))
        self.tabs.addTab(metadata, "Metadata / Provenance")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
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
            f"Authoritative style: {renderer_name}\n"
            + (
                "Editing opens the native QGIS symbology editor."
                if qgis_symbology_available()
                else "The QGIS bridge is not built; symbology editing is unavailable."
            ),
            symbology,
        )
        status.setWordWrap(True)
        form.addRow("", status)
        self.qgis_edit_button = QPushButton("Open QGIS Symbology Editor…", symbology)
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
        symbology_form.addRow("Fill / ramp", self.fill_edit)
        symbology_form.addRow("Stroke", self.stroke_edit)
        symbology_form.addRow("Stroke width", self.stroke_width_spin)
        symbology_form.addRow("Line pattern", self.line_pattern_combo)
        symbology_form.addRow("Marker", self.marker_combo)
        symbology_form.addRow("Marker size", self.marker_size_spin)
        symbology_form.addRow("Renderer", self.renderer_combo)
        symbology_form.addRow("Classification field", self.classification_field_edit)
        symbology_form.addRow("Classes (JSON)", self.classes_edit)
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
            return f"Invalid Classes JSON: {exc}"
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
