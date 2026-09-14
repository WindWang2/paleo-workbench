"""验证：在 app 当前的「天文比例尺」视野下，QGIS 画布到底渲染不渲染。

复刻 app 启动后的真实状态：CompositeDocument(project_area) → 不缩放、
直接用启动恢复的范围导出 PNG → 再用 zoom_to_full_extent 导一张对照。

如果第一张空白、第二张有内容 → 问题是「启动恢复了一个远离数据的范围」。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

PROJECT = Path(r"C:\Users\wangj.KEVIN\projects\data\project_area\project_area.paleo.json")

from paleo_workbench.project.manager import ProjectManager  # noqa: E402
from paleo_workbench.ui.workstation.composite_document import CompositeDocument  # noqa: E402

project = ProjectManager(PROJECT).load()
doc = CompositeDocument(project)
doc.resize(1200, 800)
doc.show()
app.processEvents()
import time
time.sleep(1)
app.processEvents()

canvas = doc.canvas
stack = canvas.stack
addr = canvas.canvas_address

print(f"startup extent: {stack.canvas_extent(addr)}")
print(f"startup scale : {stack.canvas_scale(addr)}")

# 1) 启动范围直接导出（app 当前就是这个视野）
p1 = ROOT / ".workbuddy" / "view_startup.png"
canvas.export_png(str(p1))
print(f"startup png -> {p1}")

# 2) 缩放到全图（数据范围）
stack.zoom_to_full_extent(addr)
app.processEvents()
time.sleep(1)
app.processEvents()
print(f"full extent: {stack.canvas_extent(addr)}")
print(f"full scale : {stack.canvas_scale(addr)}")
p2 = ROOT / ".workbuddy" / "view_full.png"
canvas.export_png(str(p2))
print(f"full png -> {p2}")
print("DONE")
