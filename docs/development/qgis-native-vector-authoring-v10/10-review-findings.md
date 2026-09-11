# 10 — Review Findings（V10）

5 轮对抗审查（每轮独立 subagent + 主 agent 复核修复）。
分级：P0（阻断）/ P1（必须修）/ P2（修复或记录）。

## Review 1 — QGIS 架构

- **P1** `_nearest_part` MultiPoint TypeError（与 R2 重复发现）→ 已修
  （composite_editing.py，裸坐标按点距离处理）。
- **P1** delete_ring/delete_part/move_part 是无生产调用方的 dead surface，
  与自家 doc 03 §A6 冲突 → 决策：确认为 **API 级支持 + 画布拾取交互 DEFERRED**
  （文档更新，不造假工具面；`_ring_and_part_commands` 保留为已测 API）。
- **P2** nearestSegmentOnFeature 手写段扫描 = 第二内核气味 → 已重构到
  `QgsGeometry::closestSegmentWithContext`（核心公开算子，曲线安全）。
- **P2** minVerticesAfterDelete 双语守卫漂移风险 → 记录（R2 验证失配方向
  恒为 fail-safe 拒绝，无损坏路径）。
- **P2** add_ring 列表操作的 D4 论据有误（QgsGeometry::addRing 是公开纯几何
  算子）→ doc 04 已更正；按 undo 语义保留列表操作 + 捕获期包含性守卫
  （宿主近似），完整 OGC 校验归保存期 validate（11 记录）。
- **P2** add_part/delete_part 绕过 facade → 记录（manifest 门禁在位；
  facade 归一留待后续）。
- **P2** doc 04 D6 "PwbSnapIndicator" 从未实现（QgsSnapIndicator 本就是
  GUI 公开类）→ doc 03/04 已更正。
- **P2** locator 预热同步构建 → 保留（确定性优先），频次审计为有限点
  （R4 验证非每编辑触发）。
- **P2** 3 个 manifest flag 无消费者 → 记录（信息性声明 + 未来门禁锚点）。
- **P2** duplicate_selected 不刷新拓扑计数 → 已修。
- **P2** ring/part applier 吞拒绝原因 → shim 层补 commit_rejected 回执。
- OK：全部新变更路径经 VectorEditSession 命令；QGIS API 全公开层；
  manifest 与暴露面一致；镜像层只读纪律保持。

## Review 2 — 编辑正确性（含 3000 试随机 fuzz + 执行验证）

- **P1** `_nearest_part` MultiPoint TypeError → 已修。
- **P1** `duplicate_feature` 显式 id 冲突 → apply 覆盖 + undo 删原要素 →
  已修（存在性拒绝 + 测试）。
- **P2** `_nearest_part` 嵌套多边形洞盲（错位部件）→ 已修（洞感知包含判定）。
- **P2** `_nearest_interior_ring` 未闭合环缺 wrap-around 边 → 已修。
- **P2** `_plain_geometry` falsy 穿透（空列表→对象→TypeError）→ 已修
  （显式属性判定）。
- **P2** explode 不过滤空部件 → 已修（类型+非空过滤）。
- OK（fuzz 验证）：ring 闭环维护 3000 试零开环/零退化/undo 精确恢复；
  `allow_append` 边界正确；locator 边命中 +1 语义全几何类型正确（闭环段
  是真实存储对）；move_part 浮点平移闭环位精确；digitize 节流 NaN 初始化
  正确；explode/collect 命令语义端到端正确。

## Review 3 — 生命周期

- **P2** 无序 teardown 路径 hideSnapIndicator 回调先于 shim 守卫 → 记录
  （无生产消费者，try/except 包裹；坟场注释同类）。
- **P2** add_ring/add_part 缺陈旧目标重绑守卫（reshape 有 ADV-3）→ 已修
  （同款守卫）。
- **P2** digitizer 捕获点跨 deactivate/reactivate 存活（幻影提交进新会话，
  V8 既有类，V10 重绑扩大触发面）→ 已修（`PwbDigitizeTool::deactivate`
  调 `clean()`——与 QGIS 桌面"切工具弃捕获"一致）。
- **P2** 120ms 镜像防抖窗口内 hover 陈旧索引（insert→hover→Delete 亚 120ms
  序列可错址）→ 记录（会话边界守卫兜底，错址概率极低）。
- OK：新 C++ 成员析构序安全（deactivate-before-qDeleteAll 纪律与 rubber_
  一致）；alive_token 正确覆盖新回调；shim 弱引用守卫覆盖新分支；
  Ring/PartCaptureTool 引用环与 reshape 同类（GC 可回收）；
  start_editing 重绑无重入危害。

## Review 4 — 性能

- **P0** 镜像层无空间索引 → pickFeature 每 move 全表扫描（100k 层
  10-30ms/move）→ 已修（upsert 后 createSpatialIndex；delta 路径增量维护）。
- **P1** 双 snapToMap/move → 已修（match 复用）。
- **P1** 预热同步构建 + **定位器索引永不失效**（provider 级编辑不发
  dataChanged → 捕捉长期命中过期几何）→ 失效问题已修（几何变更 upsert
  后销毁+重建已预热定位器）；同步构建保留（确定性）。
- **P1** 选集事实 O(selection)×~9 次收集器重建 → 已修（单趟合并 + memo；
  ~9 次结构问题记录于 11）。
- **P1** digitize 进度 O(captured) payload + 死解析 → 已修（30ms 节流 +
  无消费者跳过 json.loads）。
- **P1（流程）** 承诺的 call-count 测试缺失 → 已补
  （tests/test_v10_edit_paths_callcount.py）。
- **P2** explode 逐要素 undo 粒度 → 已修（单宏）。

## Review 5 — UX 对抗

- **P1** add_ring 无包含性校验（洞可画在多边形外）→ 已修（捕获期至少一
  顶点严格在外环内；完整校验归保存期，11 记录）。
- **P2** 零位移点击产生同值 vertex_moved（undo 噪音）→ 已修（拖动阈值
  抑制，QGIS click-vs-drag 语义）。
- **P2** 拖动中 snap 指示器冻结原位 → 已修（拖动开始隐藏）。
- **P2** 被拒 Delete 是无声死键 → 已修（vertex_delete_rejected 回执）。
- **P2** 连续 Delete 需重新 hover → 记录（反陈旧镜像守卫，有意）。
- **P2** snap_feedback/capture_progress 死接线 → capture_progress 已接
  状态栏测距标签（工具互斥复用）；snap_feedback 保持信号面（11 记录）。
- **P2** 混合选集 explode 消息夸大 → 已修（跳过计数）。
- OK：快速切工具/Esc 连击/双击边界（顶点上、空白、拖动中、MultiPoint）/
  Delete 与 delete_selected 快捷键无冲突/捕获中切层保存回滚/undo 后选集
  由 session 剪枝（审稿人称"幽灵选集"不成立——session.undo 有
  intersection_update）。

## 结论

P0 清零；P1 全部修复或以诚实 DEFERRED 记录；P2 修复 14 项、记录 9 项
（见 11-known-limitations）。修复后回归：fallback 腿 405 passed / 2 skipped，
QGIS 腿 99 passed。
