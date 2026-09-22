"""用 mock 真实生成的多边形复现「镜像层无效/不上画布」。

跑真 mock provider（80x80 栅格矢量化出的锯齿多边形）→ 走 app 的叠加
链路 → 检查镜像层 is_valid / 画布图层集 / 导出 PNG。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from paleo_workbench.project.manager import ProjectManager  # noqa: E402
from paleo_workbench.ui.workstation.composite_document import CompositeDocument  # noqa: E402

project = ProjectManager(
    r"C:\Users\wangj.KEVIN\projects\data\project_area\project_area.paleo.json").load()
doc = CompositeDocument(project)
doc.resize(1200, 800)
doc.show()
app.processEvents()
time.sleep(1)
app.processEvents()

# 用真 mock provider 生成相面多边形（栅格矢量化，可能含无效几何）
from paleo_workbench.prediction.mock_facies import ensure_mock_facies_models  # noqa: E402
from paleo_workbench.prediction.providers import get_provider  # noqa: E402

extent = [0.0, 0.0, 12793.0, 16406.0]
ring = [[328.15, 1264.18], [12843.24, 1264.18], [12843.24, 15882.8],
        [328.15, 15882.8], [328.15, 1264.18]]
crs = project.coordinate.project_crs

class _Svc:  # ensure_mock_facies_models 需要 catalog service；绕过，直接造 provider
    pass

# 直接实例化 mock provider（不经 catalog）
from paleo_workbench.prediction.mock_facies import MockSeismicFaciesProvider  # noqa: E402

provider = MockSeismicFaciesProvider()
payload = provider.run({}, {
    "target_horizon": "C3",
    "extent": extent, "_extent": extent,
    "clip_ring": ring, "_clip_ring": ring,
    "crs": crs, "_crs": crs,
    "grid_n": 80, "extent_source": "workarea",
})
spatial = payload["result_summary"]["spatial"]
features = spatial["features"]
print(f"mock produced {len(features)} polygon features, crs={spatial.get('crs')!r}")

# 几何有效性检查（shapely）
try:
    from shapely.geometry import shape
    invalid = 0
    for f in features:
        g = shape(f["geometry"])
        if not g.is_valid:
            invalid += 1
    print(f"shapely invalid geometries: {invalid}/{len(features)}")
except Exception as exc:
    print(f"shapely check failed: {exc}")

# 走 app 的叠加链路
from paleo_workbench.mapping.vector_layer import VectorFeature  # noqa: E402
from paleo_workbench.mapping_workspace.layer_roles import LayerRole  # noqa: E402
from paleo_workbench.ui.workstation.stage_actions import (  # noqa: E402
    _categorized_facies_style,
)

layer = doc.edit_controller.create_layer(
    "地震相面预测（mock）·C3", "polygon",
    role=LayerRole.SEISMIC_FACIES_PREDICTION)
doc.stage_controller.group_controller.register_layer(
    layer.id, LayerRole.SEISMIC_FACIES_PREDICTION)
doc.edit_controller.import_layer_features(layer.id, [
    VectorFeature(feature_id=f"f{i}", geometry=f["geometry"],
                  attributes=dict(f.get("properties") or {}))
    for i, f in enumerate(features)
])
style = _categorized_facies_style(
    [(f["geometry"], f.get("properties") or {}) for f in features])
if style:
    doc.edit_controller.set_layer_style(layer.id, style)
doc._sync_composition_now()
app.processEvents()
time.sleep(2)
app.processEvents()

stack = doc.canvas.stack
addr = doc.canvas.canvas_address
facts = stack.mirror_provider_facts(layer.id)
print(f"mirror: is_valid={facts.get('is_valid')} "
      f"feature_count={facts.get('feature_count')} crs={facts.get('crs')!r}")
print(f"canvas_layer_count={stack.canvas_layer_count(addr)}")

png = ROOT / ".workbuddy" / "mock_real.png"
doc.canvas.export_png(str(png))
print(f"png -> {png}")
print("DONE")
