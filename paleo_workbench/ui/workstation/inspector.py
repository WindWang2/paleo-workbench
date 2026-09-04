from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
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

    style_changed = Signal(dict)  # 兼容保留；真实样式编辑走 edit_style_requested
    edit_style_requested = Signal(str)

    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationInspector")
        self.setMinimumWidth(280)
        # 不设最大宽度：dock 加宽或浮动放大时内容要占满面板。
        self._project = project
        self._current = None
        self._current_payload: dict | None = None
        self._style_layer_id = ""

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
        style_layout = QVBoxLayout(self.style_page)
        style_layout.setContentsMargins(8, 8, 8, 8)
        style_layout.setSpacing(6)
        self.style_summary = QLabel(self.style_page)
        self.style_summary.setObjectName("WorkstationAgentConsent")
        self.style_summary.setWordWrap(True)
        style_layout.addWidget(self.style_summary)
        style_layout.addStretch(1)
        self.style_edit_button = QPushButton("在图层属性中编辑样式…", self.style_page)
        self.style_edit_button.setObjectName("SecondaryButton")
        self.style_edit_button.setVisible(False)
        self.style_edit_button.clicked.connect(self._request_style_edit)
        style_layout.addWidget(self.style_edit_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.tabs.addTab(self.style_page, "样式")

        self.history_page = QWidget(self)
        history_layout = QVBoxLayout(self.history_page)
        history_layout.setContentsMargins(8, 8, 8, 8)
        self.history_list = QListWidget(self.history_page)
        history_layout.addWidget(self.history_list)
        self.tabs.addTab(self.history_page, "历史")

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
        self._current_payload = payload if isinstance(payload, dict) else None
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
        self._update_style_page()

    def show_empty(self) -> None:
        """空态：无选择时显示「未选择对象」。"""
        self._current = None
        self.header.setText("检查器")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        self.properties_form.addRow("状态", self._readonly("未选择对象"))
        self._current_payload = None
        self._update_style_page()
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

    def _update_style_page(self) -> None:
        """样式页只反映真实情况：图层选择给事实 + 图层属性入口；其余诚实说明。"""
        payload = self._current_payload or {}
        kind = str(payload.get("kind") or "")
        layer_id = str(payload.get("layer_id") or payload.get("id") or "")
        if kind in ("layer", "user_vector_layer") and layer_id:
            facts = []
            name = str(payload.get("name") or payload.get("title") or "").strip()
            if name:
                facts.append(f"图层 {name}")
            geometry = str(payload.get("geometry_kind") or "").strip()
            if geometry:
                facts.append(f"几何 {geometry}")
            count = payload.get("feature_count")
            if isinstance(count, int):
                facts.append(f"{count} 个要素")
            self.style_summary.setText(
                "、".join(facts) + "\n\n样式、标注与渲染规则在图层属性中编辑（与编图画布同一套符号系统）。"
            )
            self.style_edit_button.setVisible(True)
            self._style_layer_id = layer_id
            return
        if kind == "map_component":
            self.style_summary.setText(
                "图件组件的样式（字体、颜色、位置）在编图组件面板中编辑。"
            )
            self.style_edit_button.setVisible(False)
            self._style_layer_id = ""
            return
        self.style_summary.setText(
            "当前选择没有可编辑的地图样式。\n\n图层样式：在资源树或图层面板选择图层；"
            "图件组件样式：在编图组件面板中选择组件。"
        )
        self.style_edit_button.setVisible(False)
        self._style_layer_id = ""

    def _request_style_edit(self) -> None:
        layer_id = str(getattr(self, "_style_layer_id", "") or "")
        if layer_id:
            self.edit_style_requested.emit(layer_id)

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


