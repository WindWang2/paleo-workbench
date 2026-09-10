# 04 — Decisions（V10）

## D1 — ring 闭环不变量放在 session 层（P0）

**决策**：`set_vertex`/`insert_vertex`/`delete_vertex` 在多边形 ring 上下文
维护首=尾闭合，而不是在 native 工具或 canvas_shim 修复。

理由：① native 与 fallback 两条提交路径共享 session 入口，单点修复；
② undo 快照天然正确（before/after 均为合法闭合几何）；③ 权威数据
（working copy）永远闭合，下游 GEOS/QGIS validate 不再被"合法拖动"打爆。
native `nearestVertex` 的严格 `<` tie-break 保留（hover 恰在重复点上时取首点，
与宿主顶点寻址约定一致）。

**边界**：仅维护"构造期已闭合"的 ring（首=尾、≥4 点）；开放 LineString
不动；不自动闭合历史遗留的开放 ring（那是 repair_geometry 的职责）。

## D2 — split/merge 属性策略显性化

- split/explode：replacements 继承原要素全部属性（地质体细分，属性不丢）。
- merge/collect：merged 属性 = 首个选中要素（选择序）；不弹 QGIS 桌面的
  merge-attributes 对话框（薄交互边界，V9 D3 同源），策略在
  `_merge_attributes_policy` 单点实现并测试锁定。
- duplicate：全属性复制 + 新 id。

## D3 — vertex insert/delete 仅 native（不回填 fallback）

V7 §5 反向规则：fallback 不得获得 native 没有的能力——本轮 native 新增
（双击插点 / Delete 删点 / snap marker / 过程反馈）**不**回填 Python
fallback 状态机。headless 测试通过 session API 直接驱动
`insert_vertex`/`delete_vertex`（ring 闭环语义在 session 层，fallback 测试
仍全覆盖）。fallback 的 vertex 工具保持 move-only，禁用原因经
ToolAvailability 诚实呈现（"native digitizer required"）。

## D4 — ring 操作复用 session 既有命令，part 操作走 QGIS 几何语义

- add/delete ring：session 既有 list-op 命令（GeoJSON append/del）+ QGIS
  `validate` 校验；不为此新造 bridge API（QGIS `addRing` 需要编辑缓冲语义，
  与"纯几何结果→命令"链路不匹配，收益为零）。
- add/delete part：bridge `geometry.add_part/delete_part`（`QgsGeometry`
  薄封装）——part 语义（MultiPoint/Line 添加点/环边界规则）由 QGIS 权威定义，
  Python 只拿 GeoJSON 结果。move_part = 限定部件的平移（纯坐标平移无几何
  语义争议，session 层实现）。
- explode/collect 复用 `split_feature`/`merge_features`（语义吻合，不造
  第三种命令形态）。

## D5 — rotate/scale/copy-paste/tracing/CAD 面板：DEFERRED（沿用 V8 D4）

V8 D4 已拒绝 rotate/tracing/CAD（地质语义弱、与 RAW-lock 冲突）。V10 复核
维持：相带边界/物源线的地质编辑工作流没有旋转/缩放需求（比例尺语义属于
制图符号层，不属于要素几何层）。剪贴板粘贴的跨层语义（角色/CRS/字段映射）
需要单独设计轮次。分类记入 05 矩阵，不为"完整"假实现。

## D6 — snapping feedback 用 QgsVertexMarker 自制薄指示器

`QgsSnapIndicator` 是 app 层不可链接。V10 在 edit_tools.cpp 内实现
`PwbSnapIndicator`（组合 `QgsVertexMarker`），仅在工具激活期存活，
不进入任何持久化/选择状态；匹配信息经 `snap_feedback` 回调回传宿主
（宿主已有等价 fallback 信息通道，不新建第二消费内核）。

## D7 — 编辑面扩张不新增第二事务路径

新命令族（part/duplicate/convert）全部走：controller `edit_command` 单入口
（re-gate）→ QGIS 几何执行或 session list-op → `VectorEditSession` 命令 →
EditDelta。不新增直接改 working copy 的入口；`tool_availability.py` 同步
登记新工具 id（canonical evaluator 唯一真源纪律）。

## D8 — capability manifest 同步纪律（沿用 V7）

新增 `set_map_tool` kind / geometry op / feature flag（`native_vertex_edit`
等）必须在 `bindings.cpp` manifest 同步登记并 bump `__version__`，Python
probe 消费后才被 ToolAvailability 承认。旧 bridge 诚实降级（新工具 disabled
with reason），不假实现。

## D9 — Z/M 保持 NOT_REQUIRED（系统 2D）

`VectorFeature._point()` 在构造期把一切坐标降为 [x,y]——Z/M 编辑面会造出
第二几何形态与第二 vertex 寻址方案。当前地质 2D 工作流（等深/相带/物源）
无 Z 需求。记录于 11，若未来需要，须先改权威数据模型，不在工具层补丁。

## D10 — 选择面动作走 session 选择权威

select_all / invert / clear 复用 `VectorLayer.set_selection/select_all/
invert_selection`（会话感知：可选项=working copy），工具面只做动作接线与
可用性（有活动可编辑层 + 有要素），不引入第二选择状态。
