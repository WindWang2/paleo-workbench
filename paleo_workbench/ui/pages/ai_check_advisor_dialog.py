"""AI Check Advisor Dialog — premium glassmorphism styled consistency report.

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
        self.setWindowTitle("AI 地质数据一致性核复顾问")
        self.resize(550, 650)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #0f172a;
                color: #f8fafc;
            }}
            QTextBrowser {{
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #334155;
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

        header = QLabel("AI 专家诊断与数据复核报告")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #38bdf8;")
        layout.addWidget(header)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        layout.addWidget(self.browser)

        # Construct dynamic HTML report
        has_errors = any(x["type"] == "error" for x in bh_report.get("issues", []))
        bh_badge = "<span style='background: #ef4444; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>不通过 (FAIL)</span>" if has_errors else "<span style='background: #f59e0b; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>警告 (WARNING)</span>"

        has_fault_warnings = len(fault_report.get("issues", [])) > 0
        fault_badge = "<span style='background: #f59e0b; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>有冲突 (WARNING)</span>" if has_fault_warnings else "<span style='background: #10b981; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>通过 (PASS)</span>"

        html = f"""
        <h3 style='color: #f1f5f9; border-bottom: 1px solid #475569; padding-bottom: 4px;'>📊 核对概要 (Summary)</h3>
        <table style='width: 100%; border-collapse: collapse; margin-top: 8px; margin-bottom: 16px;'>
            <tr style='background: #334155; color: #f8fafc;'>
                <th style='padding: 8px; text-align: left;'>复核模块</th>
                <th style='padding: 8px; text-align: center;'>已检项</th>
                <th style='padding: 8px; text-align: center;'>诊断状态</th>
            </tr>
            <tr>
                <td style='padding: 8px; border-bottom: 1px solid #334155;'>钻孔分层一致性</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid #334155;'>{bh_report.get('checked_boreholes', 0)} 个钻孔</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid #334155;'>{bh_badge}</td>
            </tr>
            <tr>
                <td style='padding: 8px; border-bottom: 1px solid #334155;'>平行/共面断层核实</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid #334155;'>{fault_report.get('checked_faults', 0)} 条断层</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid #334155;'>{fault_badge}</td>
            </tr>
        </table>

        <h3 style='color: #f1f5f9; border-bottom: 1px solid #475569; padding-bottom: 4px;'>🚨 诊断问题明细 (Issues)</h3>
        """

        # Boreholes details
        html += "<h4 style='color: #f87171; margin-bottom: 4px;'>📍 钻孔层位异常：</h4><ul style='margin-top: 0; padding-left: 20px; color: #cbd5e1;'>"
        for iss in bh_report.get("issues", []):
            color = "#ef4444" if iss["type"] == "error" else "#f59e0b"
            badge = "❌ 错误" if iss["type"] == "error" else "⚠️ 警告"
            html += f"<li><b>{iss['borehole']}</b>: <span style='color: {color};'>{badge}</span> - {iss['message']}</li>"
        if not bh_report.get("issues", []):
            html += "<li>✅ 钻孔间距及分层深度完全一致，无冲突。</li>"
        html += "</ul>"

        # Faults details
        html += "<h4 style='color: #fbbf24; margin-bottom: 4px;'>📁 共面断层预警：</h4><ul style='margin-top: 0; padding-left: 20px; color: #cbd5e1;'>"
        for iss in fault_report.get("issues", []):
            html += f"<li>🔗 <b>{' & '.join(iss['faults'])}</b>: {iss['message']}</li>"
        if not fault_report.get("issues", []):
            html += "<li>✅ 未检测到重叠或共面冲突的断层面。</li>"
        html += "</ul>"

        # AI Suggestions section
        html += """
        <h3 style='color: #818cf8; border-bottom: 1px solid #475569; padding-bottom: 4px;'>🤖 AI 推荐优化方案 (Optimization Tips)</h3>
        <div style='background: #1e1b4b; border-left: 4px solid #818cf8; padding: 12px; border-radius: 6px; margin-top: 8px;'>
            <p style='color: #a5b4fc; font-weight: bold; margin: 0 0 8px 0;'>💡 建模优化建议：</p>
            <ol style='margin: 0; padding-left: 20px; color: #e2e8f0; line-height: 1.6;'>
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
