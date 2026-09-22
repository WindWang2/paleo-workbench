"""CRS 域失配一次性引导对话框（拓扑编辑迁移 M0 §6，决议 #1285）。

进入编辑被进前域校验阻止（声明 CRS 的有效坐标域不覆盖数据实际坐标
范围）时呈现：受影响图层列表 + 失配事实，一键「改为本地坐标（清除
声明）」后由调用方清除声明并重试进入编辑（画布随之切到本地坐标
渲染）。「取消」保持现状（不进入编辑）。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

__all__ = ["CrsGuidanceDialog"]


class CrsGuidanceDialog(QDialog):
    """一次性引导：一键改声明为本地/清除、查看受影响层、取消。"""

    def __init__(self, verdict, *, affected_layers=None, parent=None):
        super().__init__(parent)
        self.setObjectName("CrsGuidanceDialog")
        self.setWindowTitle("坐标系声明与数据不符")
        self.cleared = False  # True = 用户选择「改为本地坐标（清除声明）」

        layout = QVBoxLayout(self)
        intro = QLabel(
            "进入编辑前检查发现：工程/图层声明的坐标系与数据的实际坐标"
            "范围不符。继续编辑会把数据写进错误的坐标帧。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        reason = QLabel(verdict.reason)
        reason.setWordWrap(True)
        layout.addWidget(reason)

        # 受影响层：调用方给出 (layer_id, 显示名) 序列；缺省按失配事实列出。
        layers = QListWidget(self)
        rows = [
            f"{display}（{layer_id}）"
            for layer_id, display in (affected_layers or ())
        ] or [
            f"声明 {mismatch.crs}：{mismatch.describe()}"
            for mismatch in verdict.mismatches
        ]
        for row in rows:
            layers.addItem(row)
        layers.addItem(f"当前声明 CRS：{verdict.declared_crs or '（图层声明）'}")
        layout.addWidget(QLabel("受影响图层："))
        layout.addWidget(layers, 1)

        fix_button = QPushButton("改为本地坐标（清除声明）并进入编辑")
        fix_button.setDefault(True)
        fix_button.clicked.connect(self._clear_declaration)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(fix_button)
        layout.addWidget(cancel_button)

    def _clear_declaration(self) -> None:
        self.cleared = True
        self.accept()
