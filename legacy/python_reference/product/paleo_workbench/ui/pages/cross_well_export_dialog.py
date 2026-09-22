"""Export options dialog for the cross-well correlation section."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class CrossWellExportDialog(QDialog):
    """Pick export format, DPI, width and PDF page size."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("导出连井剖面")
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.format_combo = QComboBox()
        self.format_combo.addItem("SVG 矢量图", "svg")
        self.format_combo.addItem("PNG 位图", "png")
        self.format_combo.addItem("PDF 文档", "pdf")
        self.format_combo.currentIndexChanged.connect(self._update_enabled)
        form.addRow("格式", self.format_combo)

        self.dpi_combo = QComboBox()
        for dpi in (96, 150, 300):
            self.dpi_combo.addItem(str(dpi), dpi)
        self.dpi_combo.setCurrentIndex(1)  # 150
        form.addRow("DPI", self.dpi_combo)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(0, 20000)
        self.width_spin.setSingleStep(100)
        self.width_spin.setSpecialValueText("自然宽度")
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(0)
        form.addRow("宽度", self.width_spin)

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItem("内容尺寸", None)
        self.page_size_combo.addItem("A4", "A4")
        self.page_size_combo.addItem("Letter", "LETTER")
        self.page_size_combo.currentIndexChanged.connect(self._update_enabled)
        form.addRow("纸张", self.page_size_combo)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_enabled()

    def _update_enabled(self) -> None:
        fmt = self.format_combo.currentData()
        self.dpi_combo.setEnabled(fmt in ("png", "pdf"))
        self.page_size_combo.setEnabled(fmt == "pdf")
        self.width_spin.setEnabled(
            not (fmt == "pdf" and self.page_size_combo.currentData() is not None)
        )

    def options(self) -> dict:
        fmt = self.format_combo.currentData()
        page_size = self.page_size_combo.currentData() if fmt == "pdf" else None
        width_px = self.width_spin.value() or None
        if page_size is not None:
            width_px = None
        return {
            "fmt": fmt,
            "dpi": self.dpi_combo.currentData(),
            "width_px": width_px,
            "page_size": page_size,
        }
