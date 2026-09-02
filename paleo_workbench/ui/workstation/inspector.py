from __future__ import annotations

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


class WorkstationInspector(QFrame):
    """Contextual properties, interpretation, style, and provenance."""

    style_changed = Signal(dict)

    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationInspector")
        self.setMinimumWidth(280)
        self.setMaximumWidth(420)
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

    def set_project(self, project) -> None:
        self._project = project
        self.show_project(project)

    def show_payload(self, payload) -> None:
        payload = payload or {}
        kind = payload.get("kind") if isinstance(payload, dict) else ""
        obj = payload.get("object") if isinstance(payload, dict) else payload
        if kind == "well":
            self.show_well(obj)
        elif kind == "resource":
            self.show_resource(obj)
        elif kind in {"horizon", "interpretation"}:
            self.show_horizon(str(payload.get("name") or "D63"), obj)
        elif kind == "layer":
            self.show_layer(str(payload.get("layer_type") or "图层"))
        elif kind == "project":
            self.show_project(obj)

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
        self.interpretation_form.addRow("联动状态", self._readonly("地图 / 地震 / 测井已联动"))
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
        self.properties_form.addRow("路径", self._readonly(getattr(resource, "path", "")))
        self.properties_form.addRow("生命周期", self._readonly(getattr(resource, "lifecycle", "原始输入")))
        self.interpretation_form.addRow("活动层位", self._readonly(self._target_horizon()))
        self._set_history(["项目数据对象", "存储详情可在数据目录高级视图中查看"])

    def show_horizon(self, name: str, obj=None) -> None:
        self._current = obj or name
        self.header.setText(f"检查器 · {name} 拾取点")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        self.properties_form.addRow("域", self._readonly("Time (TWT)"))
        self.properties_form.addRow("TWT", self._readonly("1436.0 ms"))
        self.properties_form.addRow("深度 (VD)", self._readonly("1352.3 m"))
        self.properties_form.addRow("IL / XL / CDP", self._readonly("1680 / 4200 / 1680"))
        self.interpretation_form.addRow("层位", self._readonly(name))
        self.interpretation_form.addRow("类型", self._readonly("层位解释"))
        self.interpretation_form.addRow("置信度", self._readonly("建议复核"))
        self.interpretation_form.addRow("解释版本", self._readonly("v1_current"))
        self._set_history([f"{name} · v1_current", "拾取来源与校验记录可追溯"])

    def show_layer(self, layer_type: str) -> None:
        self.header.setText(f"检查器 · {layer_type}")
        self._clear_form(self.properties_form)
        self._clear_form(self.interpretation_form)
        self.properties_form.addRow("作用域", self._readonly("当前文档"))
        self.properties_form.addRow("可见", self._readonly("是"))
        self.properties_form.addRow("数据源", self._readonly("项目数据对象"))

    def _target_horizon(self) -> str:
        stratigraphy = getattr(self._project, "stratigraphy", None)
        return str(getattr(stratigraphy, "target_horizon", "") or "D63")

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
