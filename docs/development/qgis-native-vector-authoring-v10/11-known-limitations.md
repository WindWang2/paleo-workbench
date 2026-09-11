# 11 — Known Limitations（V10）

诚实记录；分级 [inherited]=V7–V9 遗留未翻案 / [v10]=本轮新增或显性化。

## 交互边界

1. [v10] **delete_ring / delete_part / move_part 是 API 级支持**（
   `_ring_and_part_commands`，pick_point 驱动，已测）；画布拾取交互（专用
   MapTool 点击选环/部件）DEFERRED——工具面不登记这三个 id，不造假可用性。
2. [v10] **vertex insert/delete 不回填 Python fallback**（D3：fallback 不获
   native 专属能力）。headless 测试经 session API 直接驱动（语义在 session
   层全覆盖）。
3. [v10] **连续 Delete 需重新 hover**：提交后 clearHover 是反陈旧镜像守卫
   （120ms 防抖窗口内镜像几何可能滞后），代价是 Delete/Delete 连击节奏。
4. [v10] **snap_feedback 信号面无宿主消费者**（状态栏 snapping 标签归
   update_state 所有，高频反馈会闪烁）；capture_progress 已接测距标签。
5. [v10] **120ms 镜像防抖窗口内的 hover 陈旧索引**：亚 120ms 的
   insert→hover→Delete 序列可能按旧镜像寻址（会话守卫拒绝越界，错址编辑
   概率极低）。
6. [inherited] move 工具无目标 snap（原始 dx/dy）；multi-vertex selection /
   segment move DEFERRED；rotate/scale/copy-paste/tracing/CAD 面板 DEFERRED
   （V8 D4 维持）。
7. [inherited] capture scratch 层是系统内唯一 `startEditing` 的 QGIS 层
   （digitizer 前置要求，不落盘）。

## 校验边界

8. [v10] **捕获环包含性守卫是宿主近似**（≥1 顶点严格在目标外环内）；
   洞-洞重叠、环自交与完整 OGC 校验归保存期 validate（QGIS GEOS 引擎）。
   doc 04 D4 关于 QgsGeometry::addRing 的论据已更正——按 undo 语义保留
   列表操作是决策而非技术必然。
9. [v10] **minVerticesAfterDelete（C++）与 session 守卫（Python）双语并存**：
   R2 验证失配方向恒为 fail-safe 拒绝（无损坏路径），漂移风险记录在案。
10. [inherited] `canvas_destination_crs` 在 worktree 配方（vendor 缺
    proj.db）返回 ""——digitize CRS 守卫仅在 PROJ 数据可用处生效（V9 09-1）。

## 性能边界

11. [v10] **宿主每次 state_changed 重建 collector ~8-9 次**（各 provider 各
    取一键）：选集事实已单趟+memo（每次构建 O(1) 命中），但结构性多建
    留待 app_shell provider 缓存重构（跨方向）。
12. [v10] **locator 预热是同步索引构建**（确定性优先于首帧延迟）：首次
    snapping 配置推送在超大参考层上可感知停顿；预热仅在配置变更点发生
    （非每编辑），几何变更后由 upsert 失效+重建。
13. [inherited] `_split_inputs`/availability O(layers+selection) 不缓存
    （V9 W10 决策）；undo 栈无界（V7 08-14）；EditDelta 1024 滑窗（by design）。

## 生命周期边界

14. [v10] **无序 teardown 的 snap_feedback 回调**先于 shim 守卫武装（仅
    out-of-band 画布删除路径；无生产消费者，try/except 包裹）。
15. [inherited] QObject 工具累积（Qt parent 持有，切工具不删旧实例）——
    V7 模式。
16. [inherited] `#951` 完整修复（非 qgis_stack 模块）与 CI 侧需独立工单。

## 契约边界

17. [v10] manifest `native_vertex_insert/native_vertex_delete/
    digitize_progress` 为信息性声明（无 Python 消费者；旧桥上 vertex 工具
    仍可用但无双击/删点——结构性降级，无假可用性）。
18. [inherited] 命令面板缺 split/merge/reshape（context-control-plane 08-1）；
    legacy `map_edit_scene.py` 第二编辑面（validator/migration 定位）。
19. [inherited] 100GB seismic 全链路零接触（硬排除）；本方向所有资源用于
    QGIS 2D 矢量 authoring。
