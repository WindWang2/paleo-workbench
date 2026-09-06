"""L3 curve-processing toolbox dialog (data page context menu).

One dialog for every registered curve operation: op-specific parameter
editors (no more single "参数A" spin box mapping to σ/m/δ), a read-only
missing-interval diagnostic for the chosen curve, and honest error
reporting. Saving always goes through ``apply_curve_operation`` → a NEW
DERIVED catalog version; the RAW payload is never touched.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.workflow.curve_interpretation import (
    CURVE_OPERATIONS,
    OPERATION_SCOPE,
)
from paleo_workbench.workflow.curve_operations import missing_interval_report

logger = logging.getLogger(__name__)

_OPERATION_LABELS: dict[str, str] = {
    "despike": "去尖峰（滚动中值 + 稳健 MAD 阈值）",
    "smooth": "平滑（居中滑动平均，NaN 保持）",
    "median_filter": "中值滤波",
    "normalize": "归一化（z-score / min-max）",
    "clip_outliers": "离群值裁剪（界限或百分位）",
    "baseline_shift": "基线校正（加常数偏移）",
    "unit_conversion": "单位换算（白名单精确因子）",
    "depth_shift": "深度平移（校正深度误差）",
    "resample": "重采样（全文件，保持曲线对齐）",
    "depth_unit_normalize": "深度单位归一（ft → m 等）",
    "derive_curve": "派生曲线计算器（受控表达式，无 eval）",
}


class CurveOperationDialog(QDialog):
    """Parameter editor for one curve operation on one catalog version."""

    def __init__(self, service: DataCatalogService, version_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._version_id = version_id
        self.setWindowTitle("曲线处理工具箱 → 派生版本")
        self.result_summary: str = ""

        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.operation_combo = QComboBox()
        for op_id, label in _OPERATION_LABELS.items():
            if op_id in CURVE_OPERATIONS:
                self.operation_combo.addItem(label, op_id)
        self.operation_combo.currentIndexChanged.connect(self._rebuild_parameter_rows)
        form.addRow("操作", self.operation_combo)

        self.curve_edit = QLineEdit("GR")
        self.curve_edit.setToolTip("曲线助记符（如 GR / RT / DEN）；文件级操作忽略此项")
        form.addRow("曲线", self.curve_edit)

        self._param_host = QWidget()
        self._param_form = QFormLayout(self._param_host)
        self._param_form.setContentsMargins(0, 0, 0, 0)
        form.addRow(self._param_host)

        diag_button = QPushButton("缺失区间诊断（只读，不产生版本）")
        diag_button.clicked.connect(self._run_diagnostics)
        form.addRow("", diag_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._rebuild_parameter_rows()

    # -- parameter editors ----------------------------------------------------

    def _rebuild_parameter_rows(self) -> None:
        while self._param_form.count():
            item = self._param_form.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        op = self.operation_combo.currentData()
        file_scope = OPERATION_SCOPE.get(op) in {"file", "derive"}
        self.curve_edit.setEnabled(not file_scope or op == "derive_curve")
        self.curve_edit.setToolTip(
            "派生曲线操作此处填输入文件中任一曲线（用于校验）"
            if file_scope
            else "曲线助记符（如 GR / RT / DEN）"
        )
        self._rows: dict[str, QWidget] = {}
        for row in self._parameter_rows(op):
            label, name, editor = row
            self._rows[name] = editor
            self._param_form.addRow(label, editor)

    def _spin(self, value: float, decimals: int = 3, minimum: float = -1e6, maximum: float = 1e6, suffix: str = "") -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setDecimals(decimals)
        box.setRange(minimum, maximum)
        box.setValue(value)
        if suffix:
            box.setSuffix(suffix)
        return box

    def _parameter_rows(self, op: str) -> list[tuple[str, str, QWidget]]:
        if op == "despike":
            sigma = self._spin(3.0, 1, 0.1, 20.0, " σ")
            window = self._spin(3, 0, 1, 101, " 样点")
            return [("阈值 σ", "threshold_sigma", sigma), ("窗口", "window", window)]
        if op == "smooth":
            window = self._spin(5, 0, 1, 4095, " 样点")
            return [("窗口", "window", window)]
        if op == "median_filter":
            window = self._spin(5, 0, 1, 255, " 样点")
            return [("窗口", "window", window)]
        if op == "normalize":
            method = QComboBox()
            method.addItem("z-score", "zscore")
            method.addItem("min-max [0,1]", "minmax")
            return [("方法", "method", method)]
        if op == "clip_outliers":
            pct = self._spin(1.0, 1, 0.01, 49.9, " %")
            pct.setToolTip("对称百分位带 [p, 100-p]；留空界限则用百分位")
            return [("百分位", "percentile", pct)]
        if op == "baseline_shift":
            delta = self._spin(0.0)
            return [("偏移量", "delta", delta)]
        if op == "unit_conversion":
            source = QLineEdit("g/cm3")
            target = QLineEdit("kg/m3")
            hint = QLabel("白名单对：m↔ft, g/cm3↔kg/m3, us/m↔us/ft, mm↔in, mv↔v, %↔v/v")
            hint.setStyleSheet("color: gray;")
            return [("源单位", "from_unit", source), ("目标单位", "to_unit", target), ("", "_hint", hint)]
        if op == "depth_shift":
            delta = self._spin(0.0, 3, -1e5, 1e5, " m")
            return [("平移 Δm（正=加深）", "delta_m", delta)]
        if op == "resample":
            step = self._spin(0.125, 4, 1e-6, 1e4, " m")
            return [("新步长", "step", step)]
        if op == "depth_unit_normalize":
            target = QComboBox()
            target.addItem("m（米）", "m")
            target.addItem("ft（英尺）", "ft")
            return [("目标单位", "target_unit", target)]
        if op == "derive_curve":
            expression = QLineEdit("0.5 * (GR + 10)")
            expression.setToolTip(
                "受控表达式：曲线名 + 四则运算 + min/max/log/sqrt/where/clip 等白名单函数"
            )
            mnemonic = QLineEdit("DERV")
            unit = QLineEdit("")
            return [
                ("表达式", "expression", expression),
                ("结果曲线名", "result_mnemonic", mnemonic),
                ("结果单位（可空）", "result_unit", unit),
            ]
        return []

    def _collect_parameters(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for name, editor in self._rows.items():
            if name == "_hint" or isinstance(editor, QLabel):
                continue
            if isinstance(editor, QDoubleSpinBox):
                params[name] = editor.value()
            elif isinstance(editor, QComboBox):
                params[name] = editor.currentData()
            elif isinstance(editor, QLineEdit):
                params[name] = editor.text().strip()
        return params

    # -- diagnostics -----------------------------------------------------------

    def _run_diagnostics(self) -> None:
        curve = self.curve_edit.text().strip() or "GR"
        try:
            version = self._service.get_version(self._version_id)
            path = self._service.resolve_path(version)
            import lasio

            las = lasio.read(str(path))
            if curve not in las.curves:
                QMessageBox.warning(self, "缺失区间诊断", f"曲线 {curve!r} 不在该文件中。")
                return
            depth = np.asarray(las.curves[las.curves[0].mnemonic].data, dtype=float)
            values = np.asarray(las.curves[curve].data, dtype=float)
            report = missing_interval_report(depth, values)
        except Exception as exc:  # noqa: BLE001 - dialog-level error surface
            QMessageBox.warning(self, "缺失区间诊断", f"读取失败: {exc}")
            return
        lines = [
            f"曲线 {curve}（{depth.size} 样点）",
            f"缺失样点: {report.missing_samples} ({report.missing_fraction:.1%})",
            f"最大连续缺口: {report.largest_gap:.2f}（深度轴单位）",
        ]
        if report.intervals:
            preview = "、".join(f"{a:g}–{b:g}" for a, b in report.intervals[:8])
            more = "" if len(report.intervals) <= 8 else f" …等 {len(report.intervals)} 段"
            lines.append(f"缺口区间: {preview}{more}")
        else:
            lines.append("缺口区间: 无（首末有效样点之间连续）")
        QMessageBox.information(self, "缺失区间诊断", "\n".join(lines))


def run_curve_operation_dialog(
    parent: QWidget | None, service: DataCatalogService, catalog_version_id: str
) -> str | None:
    """Modal toolbox; returns the new DERIVED version id or None."""
    dialog = CurveOperationDialog(service, catalog_version_id, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    from paleo_workbench.workflow.curve_interpretation import apply_curve_operation

    operation = dialog.operation_combo.currentData()
    curve = dialog.curve_edit.text().strip() or "GR"
    parameters = dialog._collect_parameters()
    try:
        result = apply_curve_operation(
            service, catalog_version_id, operation=operation, curve=curve, parameters=parameters
        )
    except Exception as exc:  # noqa: BLE001 - dialog-level error surface
        logger.debug("curve operation failed", exc_info=True)
        QMessageBox.warning(parent, "曲线处理", f"操作失败: {exc}")
        return None
    QMessageBox.information(
        parent,
        "曲线处理",
        f"已生成派生版本（{result.operation}）\n"
        f"输入版本: {result.input_version_ids[0][:18]}…\n"
        f"输出版本: {result.output_version_id[:18]}…\nRun: {result.run_id[:18]}…",
    )
    return result.output_version_id
