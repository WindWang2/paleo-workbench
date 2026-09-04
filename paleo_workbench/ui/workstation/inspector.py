from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.project.domain import normalize_well_name

# 未知 kind 落入通用键值表时，从 payload.object 上提取的标量字段（有则显示）。
_OBJECT_ATTR_ROWS = (
    "name",
    "type",
    "format",
    "path",
    "crs",
    "status",
    "description",
    "geometry_kind",
    "survey_type",
    "vertical_domain",
)

_VERTICAL_DOMAIN_LABELS = {"time": "Time (TWT)", "depth": "Depth"}


class WorkstationInspector(QFrame):
    """Contextual properties, interpretation, style, and provenance."""

    style_changed = Signal(dict)

    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationInspector")
        self.setMinimumWidth(280)
        # 不设最大宽度：dock 加宽或浮动放大时内容要占满面板。
        self._project = project
        self._current = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QLabel("检查器", self)
        self.header.setObjectName("WorkstationInspectorHeader")
        outer.addWidget(self.header)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("WorkstationInspectorTabs")
        outer.addWidget(self.tabs, 1)

        self.properties_page, self.properties_form = self._form_page()
        self.interpretation_page, self.interpretation_form = self._form_page()
        self.tabs.addTab(self.properties_page, "属性")
        self.tabs.addTab(self.interpretation_page, "解释")

        self.style_page = QWidget(self)
        style_layout = QFormLayout(self.style_page)
        style_layout.setContentsMargins(8, 8, 8, 8)
        style_layout.setSpacing(6)
        self.style_color = QComboBox(self.style_page)
        self.style_color.addItems(["层位绿", "联动蓝", "解释橙", "断层红"])
        self.style_width = QSpinBox(self.style_page)
        self.style_width.setRange(1, 8)
        self.style_width.setValue(2)
        self.style_label = QCheckBox("显示标签", self.style_page)
        self.style_label.setChecked(True)
        style_layout.addRow("颜色", self.style_color)
        style_layout.addRow("线宽", self.style_width)
        style_layout.addRow("标注", self.style_label)
        self.tabs.addTab(self.style_page, "样式")

        self.history_page = QWidget(self)
        history_layout = QVBoxLayout(self.history_page)
        history_layout.setContentsMargins(8, 8, 8, 8)
        self.history_list = QListWidget(self.history_page)
        history_layout.addWidget(self.history_list)
        self.tabs.addTab(self.history_page, "历史")

        self.style_color.currentTextChanged.connect(self._emit_style)
        self.style_width.valueChanged.connect(self._emit_style)
        self.style_label.toggled.connect(self._emit_style)
        if project is None:
            self.show_empty()
        else:
            self.show_project(project)

    @staticmethod
    def _form_page() -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(8, 8, 8, 8)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return page, form

    @staticmethod
    def _clear_form(form: QFormLayout) -> None:
        while form.rowCount():
            form.removeRow(0)

    @staticmethod
    def _readonly(value: object, *, unit: str = "") -> QLineEdit:
        missing = value is None or str(value).strip() in ("", "—")
        text = "—" if missing else str(value)
        if not missing and unit:
            try:
                text = f"{float(text):g} {unit}"
            except ValueError:
                text = f"{text} {unit}"
        edit = QLineEdit(text)
        edit.setReadOnly(True)
        edit.setObjectName("WorkstationInspectorValue")
        edit.setProperty("missing", missing)
        return edit

    @staticmethod
    def _yes_no(value: object) -> str:
        if value is None:
            return ""
        return "是" if bool(value) else "否"

    def set_project(self, project) -> None:
        self._project = project
        self.show_project(project)

    def show_payload(self, payload) -> None:
        payload = payload or {}
        if not isinstance(payload, dict):
            self.show_generic({"object": payload})
            return
        kind = payload.get("kind") or ""
        obj = payload.get("object")
        if kind == "well":
            self.show_well(obj)
        elif kind in {"horizon", "interpretation"}:
            self.show_horizon(str(payload.get("name") or ""), obj)
        elif kind == "layer":
            self.show_layer(str(payload.get("layer_type") or "图层"), obj)
        elif kind == "project":
            self.show_project(obj)
        elif kind in {"seismic"} or (
            kind == "resource" and str(getattr(obj, "type", "") or "") == "seismic"
        ):
            self.show_seismic(obj, str(payload.get("name") or ""))
        elif kind == "resource":
            self.show_resource(obj)
        elif kind == "map_component":
            self.show_map_component(payload)
        else:
            # 未知 kind：通用键值表，不丢弃（B4）。
            self.show_generic(payload)

    def show_empty(self) -> None:
        """空态：无选择时显示「未选择对象」。"""
        self._current = None
        self.header.setText("检查器")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        self.properties_form.addRow("状态", self._readonly("未选择对象"))
        self._set_history([])

    def show_project(self, project) -> None:
        self._current = project
        self.header.setText("检查器 · 工程")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        if project is None:
            self.properties_form.addRow("状态", self._readonly("未打开工程"))
            return
        meta = getattr(project, "meta", None)
        coordinate = getattr(project, "coordinate", None)
        self.properties_form.addRow("工程名", self._readonly(getattr(meta, "name", "")))
        self.properties_form.addRow("区域", self._readonly(getattr(meta, "region", "")))
        self.properties_form.addRow("CRS", self._readonly(getattr(coordinate, "project_crs", "")))
        self.properties_form.addRow("井", self._readonly(f"{len(getattr(project, 'wells', None) or [])} 口"))
        self.properties_form.addRow(
            "地震", self._readonly(f"{len(getattr(project, 'seismic_surveys', None) or [])} 个")
        )
        self.interpretation_form.addRow("目标层位", self._readonly(self._target_horizon()))
        self._set_history(["工程上下文已绑定", "工作区布局可保存和恢复"])

    def show_well(self, well) -> None:
        if well is None:
            return
        self._current = well
        name = str(getattr(well, "name", "") or "未命名井")
        self.header.setText(f"检查器 · 井 {name}")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        x = getattr(well, "project_x", None)
        y = getattr(well, "project_y", None)
        self.properties_form.addRow("井名", self._readonly(name))
        self.properties_form.addRow("坐标 X", self._readonly("—" if x is None else f"{x:,.2f}"))
        self.properties_form.addRow("坐标 Y", self._readonly("—" if y is None else f"{y:,.2f}"))
        self.properties_form.addRow("KB 高程", self._readonly(getattr(well, "kb", None) or "—", unit="m"))
        self.properties_form.addRow("总深度", self._readonly(getattr(well, "td", None) or "—", unit="m"))
        self.interpretation_form.addRow("活动层位", self._readonly(self._target_horizon()))
        # 联动状态只反映传入数据里真实存在的成分（坐标/轨迹），不编造。
        self.interpretation_form.addRow("联动状态", self._readonly(self._well_link_state(well)))
        self._set_history([f"已选择井 {name}", "选择通过共享 SelectionContext 发布"])

    def show_resource(self, resource) -> None:
        if resource is None:
            return
        self._current = resource
        name = str(getattr(resource, "name", "") or "未命名数据")
        self.header.setText(f"检查器 · {name}")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        self.properties_form.addRow("名称", self._readonly(name))
        self.properties_form.addRow("类型", self._readonly(getattr(resource, "type", "")))
        self.properties_form.addRow("格式", self._readonly(getattr(resource, "format", "")))
        self.properties_form.addRow("路径", self._readonly(getattr(resource, "path", "")))
        self.properties_form.addRow("状态", self._readonly(getattr(resource, "status", "")))
        self.interpretation_form.addRow("活动层位", self._readonly(self._target_horizon()))
        self._set_history(["项目数据对象", "存储详情可在数据目录高级视图中查看"])

    def show_horizon(self, name: str, obj=None) -> None:
        self._current = obj or name
        self.header.setText(f"检查器 · {name or '层位'}")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        # 只显示资源/实体上真实存在的属性；没有的字段显示 "—"，不编造拾取值。
        self.properties_form.addRow("名称", self._readonly(name))
        self.properties_form.addRow(
            "类型", self._readonly(getattr(obj, "entity_kind", None) or getattr(obj, "type", None))
        )
        self.properties_form.addRow("格式", self._readonly(getattr(obj, "format", None)))
        self.properties_form.addRow("路径", self._readonly(getattr(obj, "path", None)))
        self.properties_form.addRow("CRS", self._readonly(getattr(obj, "crs", None)))
        domain = str(getattr(obj, "vertical_domain", "") or "")
        self.properties_form.addRow(
            "域", self._readonly(_VERTICAL_DOMAIN_LABELS.get(domain, domain))
        )
        self.interpretation_form.addRow("层位", self._readonly(name))
        self.interpretation_form.addRow("状态", self._readonly(getattr(obj, "status", None)))
        self.interpretation_form.addRow(
            "解释版本", self._readonly(getattr(self._interpretation_meta(), "interpretation_version", None))
        )
        history_rows = [f"层位 {name}" if name else "层位"]
        shape = list(getattr(obj, "shape", None) or [])
        if len(shape) >= 2:
            history_rows.append(f"构件 {shape[0]} × {shape[1]}")
        artifact = str(getattr(obj, "artifact_path", "") or "")
        if artifact:
            history_rows.append(artifact)
        self._set_history(history_rows)

    def show_seismic(self, obj=None, name: str = "") -> None:
        """地震数据：survey 或 type=='seismic' 资源；范围仅在实际存在时显示。"""
        if obj is None and not name:
            return
        self._current = obj
        label = str(getattr(obj, "name", "") or name or "地震数据")
        self.header.setText(f"检查器 · {label}")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        survey = self._survey_for(obj, label)
        survey_type = str(getattr(survey, "survey_type", "") or "")
        self.properties_form.addRow("名称", self._readonly(label))
        self.properties_form.addRow(
            "类型",
            self._readonly(
                {"3d": "三维 (3D)", "2d": "二维 (2D)"}.get(survey_type, "地震数据")
            ),
        )
        self.properties_form.addRow("格式", self._readonly(getattr(obj, "format", None)))
        self.properties_form.addRow("路径", self._readonly(getattr(obj, "path", None)))
        self.properties_form.addRow("Inline 范围", self._readonly(self._seismic_axis_text(obj, survey, "inline_range")))
        self.properties_form.addRow(
            "Crossline 范围", self._readonly(self._seismic_axis_text(obj, survey, "crossline_range"))
        )
        self.interpretation_form.addRow("活动层位", self._readonly(self._target_horizon()))
        self._set_history([f"地震数据 {label}"])

    def show_map_component(self, payload) -> None:
        """图件组件（W4 composer inspector 的最小入口）。"""
        payload = payload or {}
        obj = payload.get("object")
        self._current = obj or payload
        name = str(
            payload.get("name")
            or getattr(obj, "name", "")
            or "图件组件"
        )
        self.header.setText(f"检查器 · {name}")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        component_type = payload.get("component_type")
        if component_type is None:
            component_type = getattr(obj, "component_type", None)
        position = payload.get("position")
        if position is None:
            position = getattr(obj, "position", None)
        visible = payload.get("visible")
        if visible is None:
            visible = getattr(obj, "visible", None)
        self.properties_form.addRow("名称", self._readonly(name))
        self.properties_form.addRow("组件类型", self._readonly(component_type))
        self.properties_form.addRow("位置", self._readonly(self._position_text(position)))
        self.properties_form.addRow("可见", self._readonly(self._yes_no(visible)))
        self._set_history([f"图件组件 {name}"])

    def show_layer(self, layer_type: str, obj=None) -> None:
        self._current = obj or layer_type
        self.header.setText(f"检查器 · {layer_type}")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        self.properties_form.addRow("类型", self._readonly(layer_type))
        self.properties_form.addRow("作用域", self._readonly("当前文档"))
        visible = getattr(obj, "visible", None)
        self.properties_form.addRow("可见", self._readonly(self._yes_no(visible)))
        features = getattr(obj, "features", None)
        if features is not None:
            self.properties_form.addRow("要素数", self._readonly(len(features)))

    def show_generic(self, payload) -> None:
        """未知 kind 的通用键值表：显示 payload 的标量键值，不丢弃。"""
        rows: list[tuple[str, Any]] = []
        seen: set[str] = set()

        def add_row(key: str, value: Any) -> None:
            if key in seen:
                return
            seen.add(key)
            rows.append((key, value))

        if isinstance(payload, dict):
            obj = payload.get("object")
            for key in sorted(payload):
                if key == "object":
                    continue
                value = payload[key]
                if isinstance(value, (str, int, float, bool)) or value is None:
                    add_row(key, value)
                else:
                    add_row(key, self._compact_text(value))
            if obj is not None and not isinstance(obj, (str, int, float, bool)):
                for attr in _OBJECT_ATTR_ROWS:
                    value = getattr(obj, attr, None)
                    if value is None or isinstance(value, (dict, list)):
                        continue
                    add_row(attr, value)
                features = getattr(obj, "features", None)
                if features is not None:
                    add_row("feature_count", len(features))
        else:
            add_row("对象类型", type(payload).__name__)
        if isinstance(payload, dict):
            name = str(payload.get("name") or "")
        else:
            name = str(getattr(payload, "name", "") or "")
        self.header.setText(f"检查器 · {name}" if name else "检查器")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        if not rows:
            rows.append(("状态", "无属性"))
        for key, value in rows:
            if isinstance(value, bool):
                text = self._yes_no(value)
            elif value is None:
                text = None
            elif isinstance(value, float):
                text = f"{value:g}"
            else:
                text = str(value)
            self.properties_form.addRow(key, self._readonly(text))
        self._set_history([])

    def set_style(self, values: dict) -> None:
        """程序化同步样式控件显示（不发 style_changed；真实样式接线由宿主完成）。"""
        values = values or {}
        widgets = (self.style_color, self.style_width, self.style_label)
        blocked = [widget.blockSignals(True) for widget in widgets]
        try:
            color = str(values.get("color") or "")
            if color and self.style_color.findText(color) < 0:
                self.style_color.addItem(color)
            if color:
                self.style_color.setCurrentText(color)
            try:
                self.style_width.setValue(int(values.get("width", self.style_width.value())))
            except (TypeError, ValueError):
                pass
            labels = values.get("labels")
            if labels is not None:
                self.style_label.setChecked(bool(labels))
        finally:
            for widget, was_blocked in zip(widgets, blocked):
                widget.blockSignals(was_blocked)

    # ------------------------------------------------------------------
    # 内部：真实数据提取
    # ------------------------------------------------------------------

    def _target_horizon(self) -> str:
        stratigraphy = getattr(self._project, "stratigraphy", None)
        return str(getattr(stratigraphy, "target_horizon", "") or "")

    def _interpretation_meta(self):
        return getattr(self._project, "stratigraphy", None)

    def _well_link_state(self, well) -> str:
        """井可联动的数据成分：井位坐标 / 轨迹——来自传入数据，缺则留空。"""
        parts = []
        if (
            getattr(well, "project_x", None) is not None
            or getattr(well, "surface_x", None) is not None
        ):
            parts.append("井位坐标")
        if self._well_has_trajectory(well):
            parts.append("轨迹")
        return " / ".join(parts)

    def _well_has_trajectory(self, well) -> bool:
        well_id = str(getattr(well, "id", "") or "")
        for link in list(getattr(self._project, "entity_asset_links", None) or []):
            if (
                str(getattr(link, "entity_id", "") or "") == well_id
                and str(getattr(link, "role", "") or "") == "trajectory"
            ):
                return True
        metadata = getattr(well, "metadata", None) or {}
        return bool(metadata.get("has_trajectory") or metadata.get("trajectory"))

    def _survey_for(self, obj, label: str):
        """资源/名称 → 匹配的 SeismicSurveyEntity（找不到返回 None）。"""
        if obj is not None and hasattr(obj, "inline_range") and hasattr(obj, "survey_type"):
            return obj
        surveys = list(getattr(self._project, "seismic_surveys", None) or [])
        if not surveys:
            return None
        keys = set()
        for candidate in (label, str(getattr(obj, "name", "") or "")):
            if candidate:
                keys.add(normalize_well_name(candidate))
                keys.add(normalize_well_name(Path(str(candidate)).stem))
        for survey in surveys:
            if survey.match_keys() & keys:
                return survey
        return None

    def _seismic_axis_text(self, obj, survey, key: str) -> str:
        values = list(getattr(survey, key, None) or []) if survey is not None else []
        if not values and obj is not None:
            summary = getattr(obj, "parsed_summary", None) or {}
            values = list(summary.get(key) or summary.get(f"{key}s") or [])
        if len(values) >= 2:
            step = ""
            if len(values) >= 3 and values[2]:
                step = f"（步长 {values[2]:g}）"
            return f"{values[0]:g} – {values[1]:g}{step}"
        return ""

    @staticmethod
    def _position_text(position) -> str:
        if position is None:
            return ""
        if isinstance(position, (list, tuple)):
            try:
                return ", ".join(f"{float(value):g}" for value in position)
            except (TypeError, ValueError):
                pass
        return str(position)

    @staticmethod
    def _compact_text(value) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
        return text if len(text) <= 80 else f"{text[:77]}…"

    def _set_history(self, rows: list[str]) -> None:
        self.history_list.clear()
        self.history_list.addItems(rows)

    def _emit_style(self, *_args) -> None:
        self.style_changed.emit(
            {
                "color": self.style_color.currentText(),
                "width": self.style_width.value(),
                "labels": self.style_label.isChecked(),
            }
        )
