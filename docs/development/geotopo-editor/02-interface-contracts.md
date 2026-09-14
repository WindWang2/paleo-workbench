# 02 · 接口契约 — pybind11 面 / 错误码 / JSON 载荷

状态：Accepted ｜ 本文档是 TDD 断言的钉子（tests 以此为唯一真源）。

---

## 1. 新子模块 `qgis_render_bridge.geotopo`

探测：`hasattr(qgis_render_bridge, "geotopo")`。全部函数返回 **JSON 信封字符串**（UTF-8）。

### 1.1 `polygonize_control_lines(lines_json, options_json="{}") -> str`

**入** `lines_json`：
```json
{"lines": [
   {"id": "shore_1", "path": [[x,y], [x,y], ...]},
   {"id": "fault_2", "path": [[x,y], ...]}
]}
```
**入** `options_json`：
```json
{"tolerance": 1e-6, "clip_envelope": [xmin, ymin, xmax, ymax] | null,
 "min_ring_area": 0.0}
```
**出（成功）**：
```json
{"status": "ok",
 "polygons": [
   {"geometry": {"type": "Polygon", "coordinates": [[[x,y], ...]]},
    "area": 12345.6, "centroid": [x, y],
    "source_lines": ["shore_1", "fault_2"],
    "ring_closed": true}
 ],
 "dropped_dangles": 2,
 "node_count": 2601, "edge_count": 5100,
 "elapsed_ms": 12.3}
```
- 外环 CCW（OGC）；`area` 为 CRS 平面面积（与图上米制一致，不做测地修正——见 04 限制）。
- 无界面（外包大框）一律剔除；`clip_envelope` 提供时同时剔除不完全在其内部的面。

### 1.2 `find_shared_arcs(polygon_a_json, polygon_b_json, tolerance=1e-6) -> str`

**出**：
```json
{"status": "ok", "arcs": [
   {"arc": [[x,y],...], "length": 9.5, "start": [x,y], "end": [x,y]}
]}
```
空 `arcs` = 无共边（非错误）。

### 1.3 `reshape_shared_arc(polygon_a_json, polygon_b_json, arc_json, curve_json, tolerance=1e-6) -> str`

**出（成功）**：
```json
{"status": "ok",
 "polygon_a": {"type":"Polygon","coordinates":[...]},
 "polygon_b": {...},
 "area_before": 200.0, "area_after": 200.0,
 "area_residual": 1.2e-14}
```
失败 → `PWB-GT-201/202/203/204`（见 §3），`polygon_a/b` 键缺省。

### 1.4 GIL

`polygonize_control_lines` / `reshape_shared_arc` 计算段 `py::gil_scoped_release`（≥1 ms 级运算不得持 GIL）。

---

## 2. `mapstack`（QgisMapStack）新方法

沿用既有约定：编辑操作返回**错误字符串**（`""` = 成功），JSON 参数为字符串。

### 2.1 `fault_cut_mirror_features(doc_id, curve_geojson, feature_ids_json="", options_json="{}") -> str`

- `feature_ids_json` 空 → 自动拾取穿越面；否则宿主 id 数组 `["f1","f2"]`。
- `options_json`：`{"mark_field": "fault_bounded", "side_field": null|"fault_side", "fault_tag": true}`。
- 行为：单宏内 splitFeatures + 属性克隆 + mark；`edit_gesture` 回执：
  `{"gesture": "fault_cut", "layer_doc_id": <面层>, "layers": [<面层>, <波及线层>...], "undo_text": "断层截断", "features": [<新旧宿主id>]}`
- 错误：`PWB-GT-101/102/103/104`（错误字符串前缀带码：`"PWB-GT-102: no features intersect the fault curve"`）。

### 2.2 `reshape_mirror_shared_boundary(doc_id_a, doc_id_b, feature_id_a, feature_id_b, arc_geojson, curve_geojson, tolerance=1e-6) -> str`

- 两层各一宏，一条 `boundary_reshape` 多层手势回执（layers=[a,b]）。
- 内部走 §1.3 校验（守恒三校验），失败返回对应 `PWB-GT-2xx`，**两侧零变更**。

### 2.3 `set_map_tool(canvas_addr, kind)` — kind 扩展

新增 `"faultCut"`、`"boundaryReshape"`（与既有 "vertex"/"move"/"addLine" 等并列；未知 kind 行为不变：返回错误字符串）。

---

## 3. 错误码总表（geotopo 域）

| 码 | 场景 | message 语义 |
|----|------|--------------|
| PWB-GT-001 | polygonize 输入非法（非折线/坐标 NaN） | `invalid control-line input: <detail>` |
| PWB-GT-002 | 容差非正/NaN | `tolerance must be positive` |
| PWB-GT-003 | JSON 解析失败 | `malformed json: <detail>` |
| PWB-GT-101 | fault cut：曲线无效 | `invalid fault curve` |
| PWB-GT-102 | fault cut：无穿越要素 | `no features intersect the fault curve` |
| PWB-GT-103 | fault cut：目标层不在编辑会话 | `layer <id> is not in an edit session` |
| PWB-GT-104 | fault cut：splitFeatures 引擎失败 | `split engine failed: <qgis msg>` |
| PWB-GT-201 | reshape：弧在容差内不唯一/未匹配 | `shared arc not found within tolerance` |
| PWB-GT-202 | reshape：新环非法（自交/不闭合） | `reshaped ring invalid: <detail>` |
| PWB-GT-203 | reshape：重叠校验失败 | `overlap check failed (area=<v>)` |
| PWB-GT-204 | reshape：守恒校验失败 | `area conservation failed (residual=<v>)` |
| PWB-GT-301 | 手势/会话状态非法 | `edit session state error: <detail>` |

错误信封（子模块函数）：`{"status":"error","code":"PWB-GT-2xx","message":"..."}`；mapstack 方法：字符串 `"PWB-GT-xxx: message"`（前缀可机读分割）。

---

## 4. Python host 面（mapping/）

### 4.1 `geotopo_service.py`

```python
def polygonize_control_lines(lines: list[dict], *, tolerance=1e-6,
                             clip_envelope=None) -> GeoTopoResult
# .engine ∈ {"qgis","shapely-fallback"}；.polygons: list[GeoTopoPolygon]；
# .dropped_dangles: int；失败抛 GeoTopoError(code, message)（码同 §3）。

def find_shared_arcs(a: dict, b: dict, *, tolerance=1e-6) -> list[SharedArc]
def reshape_shared_arc(a, b, arc, curve, *, tolerance=1e-6) -> ReshapePair
# shapely fallback 与桥实现契约一致（同一测试矩阵双跑，见 03 §F）。
```

### 4.2 `geological_invariants.py`

```python
class InvariantViolation:  # frozen
    code: str; severity: str  # "error"|"warning"
    message: str; layer_id: str; feature_ids: tuple[str, ...]; hint: str

class FaciesAdjacency:
    @classmethod builtin() / from_project(project)
    def may_touch(a: str, b: str) -> tuple[bool, str]      # (允许?, 缺失过渡说明)

def validate_facies_adjacency(records_by_layer, *, adjacency, min_shared_len=None) -> list[InvariantViolation]
def validate_dangling_faults(fault_records, polygon_records_by_layer, *, envelope=None, tolerance=1e-6) -> list[InvariantViolation]
def validate_isopath_continuity(isopath_records, erosion_records, *, tolerance=1e-6) -> list[InvariantViolation]
def run_geology_gate(records_by_layer, *, roles=None, project=None) -> list[InvariantViolation]
```
违规码：`facies_adjacency_gap` / `dangling_fault_unsealed` / `isopath_crosses_unconformity`（severity 皆为 error；warning 保留通道）。

### 4.3 `native_edit_session.py` 扩展

```python
def commit_all(self, *, gate, topology, geology=None, on_committed=None) -> tuple[bool, str]
# geology: Callable[[dict[str, list[dict]]], list[InvariantViolation]] | None
# 语义：返回非空 error 违规 → 全集拦截（与 topology 同为提交前置门）。
# 提交级补偿：第 k 层失败 → 已提交层按快照补偿恢复（D9），返回 (False, 原因)。

@property def compensations(self) -> list[str]   # 诊断：本次会话发生过的补偿事件层 id
```

### 4.4 `composite_editing.py` 扩展

- `activate_tool("fault_cut")` / `activate_tool("boundary_reshape")`（原生会话限定，非原生回退提示字符串）。
- `geometry_command("fault_cut_selected", curve=None)`：程序化截断入口（测试主通道）。
- `compound_macro(undo_text)` 上下文管理器：块内一切原生/Python 会话触达 → 单手势。
- `save_edits()` 增并联 geology 门（违规 error → `sessions_committed` 不发，`state_changed` 携带 `geology_violations`）。

---

## 5. 兼容性承诺（ABI 守卫）

1. 既有 `geometry` 子模块、mapstack 方法签名**零改动**（仅新增）。
2. capability_manifest 不变。
3. `PwbEditPickTool` 公共接口不变；新工具独立类。
4. POD 边界（字符串进出）不变；无新 Qt 类型跨界。
5. 无 pyd 环境：`geotopo_service` 自动 fallback；`composite_editing` 新工具入口返回 `(False, "requires native bridge")`，不 raise。
