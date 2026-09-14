# 04 — 本期已知边界与限制

## 算法/语义边界

1. **仅二维平面坐标系**：索引、脏区拓扑、LOD 全部在 2D（Qgis::GeometryType
   平面类）上运算；Z/M 值随几何搬运但不参与谓词。三维网格/非流形几何不在
   本期范围。
2. **gap 规则不增量**：间隙是覆盖全局属性，子池复检会产生边界假阳性——
   gap 仅做"指纹未变 → 缓存直返"快路径，覆盖变化时全量重算（00-D2）。
   is_valid/overlap/dangle 完全增量且与全量逐字段等价（测试钉死）。
3. **顶点编号平移**：索引以 feature 为失效粒度（插点/删点导致 nr 平移，
   逐顶点手术更新不安全）；feature 粒度重插的正确性-成本权衡已记入 00-D1。
4. **LOD 是绘制态化简**：Visvalingam 结果只进渲染管线（`_PreparedLayer`
   下游），**永不写回要素几何**——编辑拾取/拓扑始终在原始几何上进行，
   化简不改变任何持久语义。
5. **图集"批处理"是栅格批处理**：回退渲染器是 QPainter 栅格路径，
   "Instanced Quad"在本语境 = 同 pattern 多边形合并路径单次填充；
   不存在 GPU instancing（QGIS 原生画布的 GPU 路径不经本层）。
6. **零拷贝总线是 SPSC 单写者**：C++ 生产 / Python 消费；多 Python 线程
   消费需宿主自行串行化（QGIS 世界 GUI 单写者的既有约束）。

## 环境/平台边界

7. **Windows 单机实测**：全部 SLA 数字来自本机（01 文件环境节）。预算按
   本机校准；跨机器跑 `tests/perf/` 时预算可能需按 CPU 档位缩放（既有
   `test_mirror_publish_scale.py` 先例：本机已有预算级既有失败）。
8. **既有手势崩溃（非本分支引入）**：主仓 vendor 构建今日 14:09 重建后，
   命中共享节点的 press 与 ≥20k 顶点的 press 存在访问冲突
   （`test_qgis_topo_m1_native_editing.py::test_scenario5` 亦崩，主 .pyd
   同崩）——域属并行 prompt-1（拓扑编辑器）。本分支的手势级计时因此
   限 ≤10k 规模，≥20k SLA 证据走 `vertex_pick_bench` 微基准绑定
   （无 Qt 事件投递面）。该崩溃修复后应恢复手势级全规模计时。
9. **geo-viz-engine 子模块**：Ticket 3 的 C++ 侧（`vector_lod.cpp`）位于
   子模块内；子模块指针是否随 PR 推进取决于上游仓库推送权限——若不可
   推送，则以 Python 参照实现 + 本地构建的 C++ 扩展交付测试，子模块
   指针不动（避免悬空 commit）。
10. **vendor 复用**：本 worktree 桥链接主仓 vendor 构建（14:09 版）；
    vendor 的 spatialindex 静态库补丁等源差异由主仓未提交状态承载，
    本分支不 vendored QGIS 源。

## 明确不做（红线）

11. **不做任何全量栅格/地震体驻留内存方案**（00-D6 物理论证）。
12. **不改对外 API 语义**：所有加速在内部替换（JSON 回调、镜像协议、
    渲染快照接口签名不变）；新能力（bench 绑定、事件总线）全部 opt-in。
13. **不动并行方向文件集**：`catalog/`、`geological_pipeline/`、
    `qgis_mirror.py` 主链（V12-A/B/C 域）不碰；与 prompt-1 共享的
    `edit_tools.cpp`/`bindings.cpp` 冲突面已在 PR 描述声明。
