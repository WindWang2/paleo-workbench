# 相图编辑迁移 QGIS 原生拓扑编辑——规格与路线图

> 地图 [拓扑编辑地图 #1278](https://github.com/WindWang2/paleo-workbench/issues/1278) 的终点交付物。
> 本文档是七张决议票的**组装视图**；每节末尾链接决议票为唯一真源，冲突时以票为准。
> 实施会话按 §8 里程碑逐个领取，一个里程碑一个会话。

## §1 背景与底座

- 现状事实（编辑权威、原生工具、吸附/校验/撤销架构、vendored QGIS 4.2 能力审计）：
  [docs/research/topological-editing-baseline.md](../research/topological-editing-baseline.md)
- 机制考证（拓扑编辑缓冲区行为、桌面 undo 真相、避免重叠生效点、splitFeatures 语义、
  QgsTracer、qgis_app 结论）：
  [research/qgis-topo-editing 分支](https://github.com/WindWang2/paleo-workbench/tree/research/qgis-topo-editing)
  `docs/research/qgis-native-topological-editing.md`
- 检查框架考证（analysis 检查器体系、插件可移植性、缝隙语义）：
  [research/qgs-geometry-check 分支](https://github.com/WindWang2/paleo-workbench/tree/research/qgs-geometry-check)
  `docs/research/qgs-geometry-check-framework.md`
- 路线基调（访谈锁定）：**编辑权迁移 QGIS**（镜像层升级真可编辑，Python 会话改同步方）；
  相图草稿先行；终点 = 本规格 + 路线图（实施不在地图内）。

## §2 编辑权威迁移契约

**门禁三段式**

1. 进入编辑前：Python 单点 `_role_allows_editing` 唯一权威——拒绝则不开 `startEditing()`
   （RAW/成熟度/组锁 + §6 CRS 一致性在源头挡住）。
2. 编辑中：无防御，原生缓冲区自由操作。
3. 提交前：`beforeCommitChanges` 拦截——重算角色+成熟度+组锁+§5 拓扑零未忽略错误；
   拒绝则阻止提交保持会话。

**回写通道**：提交后消费 `committedFeaturesAdded/Removed/GeometryChanges/AttributeChanges`
增量信号 → 化为 EditCommand 同族命令写入 `user_vector_layers`（工程唯一真源与保存链不变）。
编辑期间 Python 不动。

**易失会话**：未提交编辑不落盘；崩溃/退出即丢；`rollBack()` 后复位到会话开启时快照基线。无 sidecar。

**拓扑服务退休**：阶段内一次替换（M5），无双轨——原生顶点上线即停
`propagate_shared_vertex`；`CompoundUndoGroup` 被手势管理器替代；`TopologyService`
保留有效性校验过渡至 §5 检查器上线后整体退役。

**审计**：宿主手势管理器即审计源（手势 id、受影响层序列、宏文本、edit_source 工具标签）；
提交时结合 committed\* 增量生成 EditDelta 等价物。不从 QUndoStack 宏文本反解。

**不变式**

- 两级撤销：层内 = `QgsVectorLayer::undoStack()` 宏，**每层每手势恰一条**；
  手势级 = 手势管理器维护受影响层有序表——整手势撤销 = 逆序逐层 `undo()`，
  重做 = 正序逐层 `redo()`；失败半程 `destroyEditCommand` 清理。手势边界 = 鼠标释放/命令确认。
- 跨层拓扑仅同 CRS 层生效（硬前提，执行点见 §6）。
- 共享节点 = map CRS 下 **1e-8 精确重合**（≠吸附容差）；拓扑点插入容差 = 层 `geometryPrecision`。
- `setTopologicalEditing`/`setAvoidIntersectionsMode` 是工具行为开关（随会话配置推送），
  **不是**校验保证——质量只来自 §5 检查器+门禁。

源：[决议 #1281](https://github.com/WindWang2/paleo-workbench/issues/1281)

## §3 存储与镜像同步通道

- **会话层集合按需生长**：进入编辑 = {活动层}；手势波及邻层（顶点「全部层」档、
  拓扑点散布目标）→ 门禁即时复查 → 通过自动加入集合，拒绝则该层不参与并提示。
- **停发窗口 = 会话集合整体**：集合内层数据增量重发短路；集合外照常发布
  （no-op 样式漂移自愈在集合外层继续生效）。编辑期数据台账冻结；样式验证继续跑。
- **保存 = 整集合全或无**：门禁+拓扑零错误全集合判定 → 全过逐层 `commitChanges`
  → 逐层回写真源；任一失败剩余层 `rollBack`。逐层独立保存不可用。
- **编辑中变更互斥**：样式允许（渲染器替换不碰缓冲区）；字段 schema 变更拒绝
  （提示先保存/回滚）。集合外不受限。
- **提交后对齐**：镜像即编辑发生地，commit 后无需重发——台账直接对齐新基线
  （data_revision 跳新值、fields_sig/style_sig 重算，状态 =「镜像=真源」）；
  fid 反查表按 provider 现值重建。
- `user_vector_layers` 唯一真源不变；QGIS 工程信封只存呈现态。

源：[决议 #1283](https://github.com/WindWang2/paleo-workbench/issues/1283)

## §4 拓扑交互工具规格

**顶点工具 v2**（对标 `QgsVertexTool`，参考坐标 `qgsvertextool.cpp:1898-1919, 2091-2096,
2320-2567, 2685-2724, 2727-2769`）

- 档位：默认「当前层」（层内拓扑覆盖相图主场景）；可切「全部层」（跨层+邻层散布）。
- 框选多节点；**公共节点高亮**：拖拽开始 → `locatorForLayer(layer)->verticesInRect(mapPt, 1e-8)`
  联合发现同位置节点集，视觉区分「只动本要素」与「拓扑同步」。
- 提交 → 每层一宏 + 同 CRS 线/面层拓扑点散布（bbox 预查，空层 destroy 不留痕）。
- 删除 → 同位置节点联合删除（含最小节点数防护）。
- 撤销宏文本沿用桌面词汇（"Moved vertex" 等）。

**无缝分割**：选中面 → 「分割要素」→ 画布数字化切线（复用 `PwbDigitizeTool` 线模式，
吸附/追踪可用）→ 确认 → `splitFeatures(curve, topologyTestPoints, true, topologicalEditing=true)`
+ 邻层拓扑点循环。**邻层只插点不分割**（原生语义，显式非目标：邻层同切）。
属性继承：两块继承源要素（桌面 split policy 最大块继承 fid）；后续动作用相分类对话框改赋。

**无缝合并**：确认对话框预填「面积最大要素」属性（下拉可换），相分类字段冲突高亮可改；
确认 → `mergeFeatures(union, 归并属性)`，一宏可撤。不盲合。

**避免重叠**：吸附工具栏开关，默认**开**，裁切范围默认 = 当前编辑层（高级可扩层）。
数字化免费（GUI 基类已调 `avoidIntersectionsV2`，桥接只推配置）；
顶点/移动工具需桥接复刻 `QgsAvoidIntersectionsOperation` 语义
（多部件保留最大块 + 交点散布拓扑点）。

**追踪**：吸附工具栏开关，默认**关**；注册 `QgsMapCanvasTracer` 全体捕获工具（含分割切线）
免费获得；端点容差 = 常规吸附容差（无 `setSnapTolerance` API）；`maxFeatureCount`/
extent 按可见范围；缩放/编辑后图全量重建。两开关随编辑会话持久化。

源：[决议 #1282](https://github.com/WindWang2/paleo-workbench/issues/1282)

## §5 拓扑检查器

选型（研究锁定）：**analysis 检查器体系 + 桥接暴露 run/fix API + 自制面板**，插件零移植。

| 规则 | 引擎 | 修复 | 适用 |
|---|---|---|---|
| 面重叠 | `QgsGeometryOverlapCheck` | 裁掉/合并（可修） | 面状可编辑角色 |
| 面缝隙 | `QgsGeometryGapCheck` | 填补/白名单（可修） | 面状可编辑角色 |
| 几何有效性 | `validateGeometry`(GEOS) | makeValid（可修） | 全部可编辑层 |
| 工区余量（自制） | `工区面.difference(union(相带))` | **建议性导航** | 相图草稿角色默认启用 |
| 线悬挂点 | `QgsGeometryDangleCheck` | 无修复 | 二阶段线层再开 |

- 工区范围 = 工区边界图层（兜底：工程范围）。工区余量抓「相带间直通边界的未分配区域」
  ——原生缝隙只抓被面包围的洞，抓不到它；「铺满工区」是相图核心质量要求。
- 刷新：面板「检查」手动全量 + **保存前自动**（面板与门禁共用一份结果）；
  徽章 = 上次结果+时间；不做每笔编辑实时重算；修复后局部复查
  （复用 `QgsGeometryChecker::fixError` 修复→复查→级联失效闭环）。
- 面板 UX：错误列表（规则过滤）、地图高亮、点击缩放、被忽略错误灰显可恢复。
- 门禁：零**未忽略**错误放行（`beforeCommitChanges` 同点，合并现有 `save_edits` 拓扑门禁）。
  豁免①缝隙白名单层（原生 allowedGaps，随工程持久化）；豁免②标记忽略
  （feature id+规则+原因，随工程持久化，不改几何只不阻断）。
- 修复：单条右键出 check 声明的方法列表（含预览描述）；批量「全部修复」同方法顺序应用；
  每次修复一宏可撤。工区余量修复 = 建议性导航（不自动改几何）。

源：[决议 #1284](https://github.com/WindWang2/paleo-workbench/issues/1284)

## §6 CRS 契约

- 进前域校验（声明有效坐标域 vs 数据实际坐标范围）；失配 → 阻止进入编辑 +
  一次性引导对话框（一键改声明为本地/清除、查看受影响层、取消），修复即入编辑。
  打开工程时同一检测兜底旧工程。
- CRS 校验并入三段式「进前段」（会话集合全部层+画布同 CRS）；**编辑会话期间 CRS 冻结**；
  提交前不重复查；旧 `crs_chain.evaluate_commit_guard` 退休。
- 新工程不预设地理 CRS；首次导入数据按坐标范围推断（超经纬度域→保持本地；
  可识别投影→建议声明，用户确认锁定）；锁定后可手改（非编辑会话中）。

源：[决议 #1285](https://github.com/WindWang2/paleo-workbench/issues/1285)

## §7 验收场景（Given-When-Then）

**门禁与会话**

1. RAW 保护：Given RAW 层为活动层 When 开始编辑 Then 进前拒绝（原因含「复制为草稿」指引），
   无 `startEditing` 发生。
2. CRS 失配引导：Given 工程声明 EPSG:4326 且数据本地坐标 When 开始编辑 Then 阻止 + 引导框；
   一键修复后进入编辑且画布单位为本地。
3. 保存全或无：Given 会话集合 2 层且层 B 有未忽略拓扑错误 When 保存 Then 全集合保持会话、
   无任何层提交；修复后保存两层同提交。
4. 崩溃易失：Given 编辑未保存 When 进程被杀 Then 重开工程只含已提交状态。

**拓扑编辑**

5. 层内拓扑：Given 当前层档、相邻两面共享节点 When 拖动公共节点 Then 两面同步移动，
   一次 Ctrl+Z 整体回退，无缝隙产生。
6. 跨层拓扑：Given 全部层档 When 拖动跨层共享节点（3 层）Then 邻层经门禁复查自动入会话集合、
   三层同步；一次 Ctrl+Z 三层回退（逆序逐层）。
7. 邻层拒绝：Given 波及 RAW 邻层 When 手势提交 Then 该层不参与 + 状态条提示，其余层正常。
8. 避免重叠：Given 开关开 When 数字化与已有面重叠的新面 Then 提交时自动裁掉重叠部分，
   拓扑点散布到被交面。

**几何命令**

9. 分割：Given 选中面 When 画切线确认 Then 面分两块均继承源属性；追踪开时切线沿边吸附；
   邻层同位置被插拓扑点但不分割；一 Ctrl+Z 全撤。
10. 合并：Given 选相邻两面 When 合并 Then 对话框预填最大面积要素属性、冲突高亮；
    改值确认后 union 几何 + 归并属性落层，一 Ctrl+Z 全撤。
11. 追踪：Given 追踪开 When 沿现有边画新面（起终点点在边上）Then 新面与旧面公共边
    顶点完全重合（无微缝）。

**检查器**

12. 工区余量：Given 相带未铺满工区 When 检查 Then 未分配区域被抓为错误并高亮，
    点击缩放定位；「修复」给建议导航不自动改几何。
13. 门禁豁免：Given 一处标记忽略的重叠 When 保存 Then 放行；面板中该错误灰显可恢复；
    恢复后再次阻断。
14. 批量修复：Given 多处重叠 When 全部修复 Then 逐个裁切完成面板清空；
    一次 Ctrl+Z 全部修复整体回退。

**同步通道**

15. 停发窗口：Given A 层在编辑会话 When B 层（集合外）样式被外部改变 Then B 层重发/自愈
    照常，A 层数据不重发。
16. 提交对齐：Given 保存成功 When 检查镜像与真源 Then 内容一致、台账状态=镜像=真源、
    fid 反查表重建正确、审计日志含手势溯源。

## §8 里程碑路线图

| 里程碑 | 内容 | 实现件来源 | 退出标准 |
|---|---|---|---|
| **M0 地基** | CRS 契约件（域校验+引导框+推断锁定）+ 会话集合管理器 + 停发短路 + 台账对齐 | §6、§3 | 场景 2、15 通过；现有镜像回归全绿 |
| **M1 原生编辑 MVP** | 镜像层 startEditing + 三段门禁 + 手势管理器（层宏+逆序撤销）+ 顶点 v2 当前层档 + committed\* 回写 + 快照基线回滚 | §2、§4 顶点、§3 | 场景 1、3、4、5 通过；M0 回归绿 |
| **M2 跨层与配置型能力** | 全部层档 + 拓扑点散布 + 避免重叠（开关+数字化免费+顶点/移动复刻）+ 追踪（Tracer 注册+开关） | §4 | 场景 6、7、8、11 通过；M1 回归绿 |
| **M3 几何命令** | 无缝分割（画布切线）+ 无缝合并（对话框）+ 属性继承 | §4 | 场景 9、10 通过；M2 回归绿 |
| **M4 检查器** | 四规则 + 面板 dock + 保存门禁合并 + 双豁免 + 修复交互 | §5 | 场景 12、13、14、16 通过；M3 回归绿 |
| **M5 退休与评估** | Python 拓扑服务下线（propagate_shared_vertex / CompoundUndoGroup / TopologyService）+ 二阶段推广评估 | §2 | 全部 16 场景绿；无双轨残留 |

**二阶段（线约束层/综合相/注记 + 悬挂点规则）启动三重门**：① M0–M5 验收全绿；
② 一个真实相图工程完整编辑周期（建稿→拓扑编辑→检查→保存→导出）无 P1 缺陷；
③ 用户确认体验达标。

**实施注意**：每里程碑一个实施会话；桥接改动遵循现有构建配方
（`PALEO_WITH_QGIS_RENDERER=1 PALEO_QGIS_CMAKE_PREFIX=<vendor_output>`）；
每里程碑附回归锚点——尤其 M0/M1 不得破坏近期修复的 no-op 样式漂移自愈与
显示顺序（自上而下）语义。
