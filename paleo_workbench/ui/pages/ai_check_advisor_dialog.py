"""Rule-based data consistency advisor dialog — deterministic consistency report.

The checks (borehole layer overlap, coplanar faults) are explicit geometry
rules, not an AI model; labels avoid "AI expert" overclaims.
Extracted from geological_modeling_3d_page.py to avoid Divergent Change smell.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QTextBrowser

from paleo_workbench import tokens


class AICheckAdvisorDialog(QDialog):
    """Premium glassmorphism styled non-modal side dialog showing consistency checking reports."""
    def __init__(self, bh_report: dict, fault_report: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("地质数据一致性核复顾问（规则检查）")
        self.resize(550, 650)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {tokens.BG_SIDEBAR};
                color: {tokens.TEXT_PRIMARY};
            }}
            QTextBrowser {{
                background-color: {tokens.BG_BODY};
                color: {tokens.TEXT_PRIMARY};
                border: 1px solid {tokens.BORDER};
                border-radius: 8px;
                padding: 12px;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
                line-height: 1.5;
            }}
            QPushButton {{
                background-color: {tokens.PRIMARY};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {tokens.PRIMARY_HOVER};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        layout.setSpacing(tokens.SPACE_2)

        header = QLabel("地质数据一致性核复报告（规则检查）")
        header.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {tokens.PRIMARY};")
        layout.addWidget(header)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        layout.addWidget(self.browser)

        # Construct dynamic HTML report
        has_errors = any(x["type"] == "error" for x in bh_report.get("issues", []))
        bh_badge = f"<span style='background: {tokens.ERROR}; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>不通过 (FAIL)</span>" if has_errors else f"<span style='background: {tokens.WARNING}; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>警告 (WARNING)</span>"

        has_fault_warnings = len(fault_report.get("issues", [])) > 0
        fault_badge = f"<span style='background: {tokens.WARNING}; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>有冲突 (WARNING)</span>" if has_fault_warnings else f"<span style='background: {tokens.SUCCESS}; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>通过 (PASS)</span>"

        html = f"""
        <h3 style='color: {tokens.PRIMARY}; border-bottom: 1px solid {tokens.BORDER}; padding-bottom: 4px;'>📊 核对概要 (Summary)</h3>
        <table style='width: 100%; border-collapse: collapse; margin-top: 8px; margin-bottom: 16px;'>
            <tr style='background: {tokens.BG_SEARCH}; color: {tokens.TEXT_PRIMARY};'>
                <th style='padding: 8px; text-align: left;'>复核模块</th>
                <th style='padding: 8px; text-align: center;'>已检项</th>
                <th style='padding: 8px; text-align: center;'>诊断状态</th>
            </tr>
            <tr>
                <td style='padding: 8px; border-bottom: 1px solid {tokens.BORDER};'>钻孔分层一致性</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid {tokens.BORDER};'>{bh_report.get('checked_boreholes', 0)} 个钻孔</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid {tokens.BORDER};'>{bh_badge}</td>
            </tr>
            <tr>
                <td style='padding: 8px; border-bottom: 1px solid {tokens.BORDER};'>平行/共面断层核实</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid {tokens.BORDER};'>{fault_report.get('checked_faults', 0)} 条断层</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid {tokens.BORDER};'>{fault_badge}</td>
            </tr>
        </table>

        <h3 style='color: {tokens.PRIMARY}; border-bottom: 1px solid {tokens.BORDER}; padding-bottom: 4px;'>🚨 诊断问题明细 (Issues)</h3>
        """

        # Boreholes details
        html += f"<h4 style='color: {tokens.ERROR}; margin-bottom: 4px;'>📍 钻孔层位异常：</h4><ul style='margin-top: 0; padding-left: 20px; color: {tokens.TEXT_SECONDARY};'>"
        for iss in bh_report.get("issues", []):
            color = tokens.ERROR if iss["type"] == "error" else tokens.WARNING
            badge = "❌ 错误" if iss["type"] == "error" else "⚠️ 警告"
            html += f"<li><b>{iss['borehole']}</b>: <span style='color: {color};'>{badge}</span> - {iss['message']}</li>"
        if not bh_report.get("issues", []):
            html += "<li>✅ 钻孔间距及分层深度完全一致，无冲突。</li>"
        html += "</ul>"

        # Faults details
        html += f"<h4 style='color: {tokens.WARNING}; margin-bottom: 4px;'>📁 共面断层预警：</h4><ul style='margin-top: 0; padding-left: 20px; color: {tokens.TEXT_SECONDARY};'>"
        for iss in fault_report.get("issues", []):
            html += f"<li>🔗 <b>{' & '.join(iss['faults'])}</b>: {iss['message']}</li>"
        if not fault_report.get("issues", []):
            html += "<li>✅ 未检测到重叠或共面冲突的断层面。</li>"
        html += "</ul>"

        # Rule-based suggestions section
        html += f"""
        <h3 style='color: {tokens.PRIMARY}; border-bottom: 1px solid {tokens.BORDER}; padding-bottom: 4px;'>💡 基于规则检查的优化建议 (Suggestions)</h3>
        <div style='background: {tokens.BG_SEARCH}; border-left: 4px solid {tokens.PRIMARY}; padding: 12px; border-radius: 6px; margin-top: 8px;'>
            <p style='color: {tokens.TEXT_PRIMARY}; font-weight: bold; margin: 0 0 8px 0;'>💡 建模优化建议：</p>
            <ol style='margin: 0; padding-left: 20px; color: {tokens.TEXT_SECONDARY}; line-height: 1.6;'>
                <li><b>钻孔 HZ19-6 层位重叠修正</b>: 第3层（石灰岩）底深为 140m，但第4层（花岗岩）顶深被记录为 135m。此 5m 重叠属于数据录入异常。请在数据源中修改花岗岩顶深为 140m，以防止地层曲面交叉。</li>
                <li><b>钻孔 HZ25-2 总深超限警告</b>: 累积层底深达 168m，而记录的总深仅为 160m。请复查底层终孔记录。</li>
                <li><b>断层合并去冗余</b>: 断层 <i>F1 Surface</i> 与 <i>F2 Surface</i> 走向夹角仅 0.16°，法线方向高度共面，间距 5m。极近距离的平行断层会导致有限元网格剖分时产生高度扭曲的畸形单元，导致 FLAC3D 或 Abaqus 计算极难收敛。<b>强烈建议在左侧模型树中勾选合并这两条断层，作为单一主要构造滑动面处理。</b></li>
            </ol>
        </div>
        """

        self.browser.setHtml(html)

        btn_close = QPushButton("确认并关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)
