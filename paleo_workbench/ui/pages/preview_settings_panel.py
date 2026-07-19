from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.preview_settings import (
    PreviewSettings,
    PreviewSettingsStore,
)


_MODE_CATEGORY = {
    "text": "text",
    "rich_text": "text",
    "web_document": "text",
    "table": "table",
    "well_log": "table",
    "seismic": "table",
    "image": "image",
    "geotiff": "image",
    "pdf": "pdf",
    "json_tree": "json",
    "media": "media",
    "geoviz": "geoviz",
}


class PreviewSettingsPanel(QFrame):
    """Compact category-based editor for every supported preview mode."""

    settings_applied = Signal(object)

    def __init__(
        self,
        parent=None,
        *,
        store: PreviewSettingsStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PreviewSettingsPanel")
        self._store = store or PreviewSettingsStore()
        self.setStyleSheet(
            f"QFrame#PreviewSettingsPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER}; border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3)
        outer.setSpacing(tokens.SPACE_2)

        heading = QHBoxLayout()
        title = QLabel("预览内容设置")
        title.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;")
        heading.addWidget(title)
        heading.addStretch()
        self.category_combo = QComboBox()
        self.category_combo.setObjectName("PreviewSettingsCategory")
        heading.addWidget(self.category_combo)
        outer.addLayout(heading)

        self.pages = QStackedWidget()
        outer.addWidget(self.pages)

        self._build_general_page()
        self._build_text_page()
        self._build_table_page()
        self._build_image_page()
        self._build_pdf_page()
        self._build_json_page()
        self._build_media_page()
        self._build_geoviz_page()
        self.category_combo.currentIndexChanged.connect(self.pages.setCurrentIndex)

        actions = QHBoxLayout()
        actions.addStretch()
        self.reset_btn = QPushButton("恢复推荐默认")
        self.reset_btn.setObjectName("SecondaryButton")
        self.apply_btn = QPushButton("应用")
        self.apply_btn.setObjectName("PrimaryButton")
        actions.addWidget(self.reset_btn)
        actions.addWidget(self.apply_btn)
        outer.addLayout(actions)

        self.apply_btn.clicked.connect(self._apply)
        self.reset_btn.clicked.connect(self._reset)
        self.set_settings(self._store.load())

    @staticmethod
    def _page() -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(tokens.SPACE_3)
        form.setVerticalSpacing(tokens.SPACE_2)
        return page, form

    @staticmethod
    def _spin(minimum: int, maximum: int, suffix: str = "") -> QSpinBox:
        control = QSpinBox()
        control.setRange(minimum, maximum)
        if suffix:
            control.setSuffix(suffix)
        return control

    def _add_page(self, key: str, label: str, page: QWidget) -> None:
        self.category_combo.addItem(label, key)
        self.pages.addWidget(page)

    def _build_general_page(self) -> None:
        page, form = self._page()
        self.font_size_spin = self._spin(8, 32, " pt")
        self.show_metadata_check = QCheckBox("显示类型、格式、状态和路径")
        form.addRow("内容字号", self.font_size_spin)
        form.addRow("元数据", self.show_metadata_check)
        self._add_page("general", "通用", page)

    def _build_text_page(self) -> None:
        page, form = self._page()
        self.text_limit_spin = self._spin(16, 4_096, " KiB")
        self.wrap_text_check = QCheckBox("自动换行")
        form.addRow("读取上限", self.text_limit_spin)
        form.addRow("长行", self.wrap_text_check)
        self._add_page("text", "文本 / 富文本", page)

    def _build_table_page(self) -> None:
        page, form = self._page()
        self.table_rows_spin = self._spin(20, 2_000, " 行")
        self.table_columns_spin = self._spin(5, 200, " 列")
        self.auto_fit_columns_check = QCheckBox("按内容调整列宽")
        form.addRow("最大行数", self.table_rows_spin)
        form.addRow("最大列数", self.table_columns_spin)
        form.addRow("列宽", self.auto_fit_columns_check)
        self._add_page("table", "表格 / 测井 / 地震", page)

    def _build_image_page(self) -> None:
        page, form = self._page()
        self.smooth_images_check = QCheckBox("平滑缩放")
        self.geotiff_thumbnail_spin = self._spin(128, 2_048, " px")
        self.show_geo_metadata_check = QCheckBox("显示 CRS、范围和栅格信息")
        form.addRow("图片", self.smooth_images_check)
        form.addRow("GeoTIFF 缩略图", self.geotiff_thumbnail_spin)
        form.addRow("GIS 元数据", self.show_geo_metadata_check)
        self._add_page("image", "图片 / GeoTIFF", page)

    def _build_pdf_page(self) -> None:
        page, form = self._page()
        self.pdf_fit_combo = QComboBox()
        self.pdf_fit_combo.addItem("适合整页", "page")
        self.pdf_fit_combo.addItem("适合页宽", "width")
        self.pdf_fit_combo.addItem("自定义缩放", "custom")
        self.pdf_zoom_spin = self._spin(25, 400, "%")
        form.addRow("打开方式", self.pdf_fit_combo)
        form.addRow("自定义缩放", self.pdf_zoom_spin)
        self._add_page("pdf", "PDF", page)

    def _build_json_page(self) -> None:
        page, form = self._page()
        self.json_limit_spin = self._spin(1, 64, " MiB")
        self.json_collapse_spin = self._spin(10, 10_000, " 项")
        self.json_depth_spin = self._spin(0, 8, " 层")
        form.addRow("解析上限", self.json_limit_spin)
        form.addRow("大数组折叠阈值", self.json_collapse_spin)
        form.addRow("初始展开深度", self.json_depth_spin)
        self._add_page("json", "JSON / GeoJSON", page)

    def _build_media_page(self) -> None:
        page, form = self._page()
        self.media_autoplay_check = QCheckBox("加载后自动播放")
        self.media_volume_spin = self._spin(0, 100, "%")
        form.addRow("播放", self.media_autoplay_check)
        form.addRow("默认音量", self.media_volume_spin)
        self._add_page("media", "音频媒体", page)

    def _build_geoviz_page(self) -> None:
        page, form = self._page()
        self.geoviz_curves_spin = self._spin(1, 64)
        self.geoviz_depth_spin = self._spin(100, 50_000)
        self.geoviz_slice_spin = self._spin(64, 4_096)
        self.geoviz_points_spin = self._spin(1_000, 1_000_000)
        self.geoviz_grid_spin = self._spin(32, 1_024)
        form.addRow("最大曲线数", self.geoviz_curves_spin)
        form.addRow("最大深度采样", self.geoviz_depth_spin)
        form.addRow("最大切片轴", self.geoviz_slice_spin)
        form.addRow("最大点数", self.geoviz_points_spin)
        form.addRow("表面网格", self.geoviz_grid_spin)
        self._add_page("geoviz", "GeoViz 专业预览", page)

    def settings(self) -> PreviewSettings:
        return PreviewSettings(
            font_size=self.font_size_spin.value(),
            show_metadata=self.show_metadata_check.isChecked(),
            text_limit_kib=self.text_limit_spin.value(),
            wrap_text=self.wrap_text_check.isChecked(),
            table_max_rows=self.table_rows_spin.value(),
            table_max_columns=self.table_columns_spin.value(),
            auto_fit_columns=self.auto_fit_columns_check.isChecked(),
            smooth_images=self.smooth_images_check.isChecked(),
            geotiff_thumbnail_px=self.geotiff_thumbnail_spin.value(),
            show_geo_metadata=self.show_geo_metadata_check.isChecked(),
            pdf_fit_mode=self.pdf_fit_combo.currentData(),
            pdf_zoom_percent=self.pdf_zoom_spin.value(),
            json_limit_mib=self.json_limit_spin.value(),
            json_array_collapse_threshold=self.json_collapse_spin.value(),
            json_expand_depth=self.json_depth_spin.value(),
            media_autoplay=self.media_autoplay_check.isChecked(),
            media_volume=self.media_volume_spin.value(),
            geoviz_max_curves=self.geoviz_curves_spin.value(),
            geoviz_max_depth_samples=self.geoviz_depth_spin.value(),
            geoviz_max_slice_axis=self.geoviz_slice_spin.value(),
            geoviz_max_points=self.geoviz_points_spin.value(),
            geoviz_surface_grid_size=self.geoviz_grid_spin.value(),
        )

    def set_settings(self, settings: PreviewSettings) -> None:
        self.font_size_spin.setValue(settings.font_size)
        self.show_metadata_check.setChecked(settings.show_metadata)
        self.text_limit_spin.setValue(settings.text_limit_kib)
        self.wrap_text_check.setChecked(settings.wrap_text)
        self.table_rows_spin.setValue(settings.table_max_rows)
        self.table_columns_spin.setValue(settings.table_max_columns)
        self.auto_fit_columns_check.setChecked(settings.auto_fit_columns)
        self.smooth_images_check.setChecked(settings.smooth_images)
        self.geotiff_thumbnail_spin.setValue(settings.geotiff_thumbnail_px)
        self.show_geo_metadata_check.setChecked(settings.show_geo_metadata)
        self.pdf_fit_combo.setCurrentIndex(
            max(0, self.pdf_fit_combo.findData(settings.pdf_fit_mode))
        )
        self.pdf_zoom_spin.setValue(settings.pdf_zoom_percent)
        self.json_limit_spin.setValue(settings.json_limit_mib)
        self.json_collapse_spin.setValue(settings.json_array_collapse_threshold)
        self.json_depth_spin.setValue(settings.json_expand_depth)
        self.media_autoplay_check.setChecked(settings.media_autoplay)
        self.media_volume_spin.setValue(settings.media_volume)
        self.geoviz_curves_spin.setValue(settings.geoviz_max_curves)
        self.geoviz_depth_spin.setValue(settings.geoviz_max_depth_samples)
        self.geoviz_slice_spin.setValue(settings.geoviz_max_slice_axis)
        self.geoviz_points_spin.setValue(settings.geoviz_max_points)
        self.geoviz_grid_spin.setValue(settings.geoviz_surface_grid_size)

    def set_preview_mode(self, mode: str) -> None:
        category = _MODE_CATEGORY.get(mode, "general")
        index = self.category_combo.findData(category)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)

    def _apply(self) -> None:
        settings = self.settings()
        self._store.save(settings)
        self.settings_applied.emit(settings)

    def _reset(self) -> None:
        settings = self._store.reset()
        self.set_settings(settings)
        self.settings_applied.emit(settings)
