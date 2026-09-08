# 01 — Target State（V7 验收目标）

体验参照：QGIS + Petrel/Kingdom + VS Code（专业桌面工作站，非 Web dashboard）。
UI 的职责：正确呈现系统能做什么、解释为什么不能做、把地质上下文映射为
工具/面板/Inspector/状态。禁止无后端按钮、永显按钮、无因禁用、多套命令状态、
重写 QGIS 原生 dialog、继续扩张 inline style 债务。

## T1 上下文驱动的命令面（goal §3）

单一 ToolContext 消费：project、preset、stage、active layer、LayerRole、
kind（point/line/polygon/其它）、maturity（RAW/DERIVED/OUTPUT）、editability、
editing、dirty、selection、QGIS capability（三态）、snapping/topology、task 态、
WRITE 授权、degraded/unavailable、freshness、QC。

menu / toolbar / palette / 右键菜单 / inspector 动作 / 阶段面板动作 / 快捷键
全部消费同一 applicability 体系（CommandRegistry + tool evaluator 派生）。

## T2 工具可用性矩阵（goal §4）

完整矩阵实现并有测试覆盖：

- **Phase 1 初始相图校正**：突出 identify/select/layer properties/start editing/
  add polygon/move/vertex/split/merge/save/rollback/QC；add_line 默认不提供
  （除非活动图层角色为线角色）；约束类工具与因子执行动作不出现。
- **Phase 2 约束与单因素**：活动图层=物源线/展布线/断层/岸线 → Add Line 为主捕获
  工具，Add Polygon 不抢主位；活动图层=interpolation boundary/mask → Add Polygon
  可用，线捕获按角色禁用；活动图层=factor raster（FACTOR_GRID/CLASSIFICATION/
  UNCERTAINTY/QC 等 RAW 角色）→ 矢量编辑工具禁用（原因：RAW/模型结果），
  呈现 color ramp/contour/statistics/properties/opacity/QC/export 入口。
- **Phase 3 综合编图**：突出 evidence selection、integrated interpretation target、
  polygon/boundary editing、QA、symbology、legend、layout、export、publish readiness。

## T3 禁用原因 UX（goal §5）

所有不可用工具能解释原因（RAW 保护、阶段不允许、几何类型不匹配、无活动矢量层、
需先开始编辑、拓扑错误、QGIS 后端不可用、需 WRITE 授权、结果已冻结、选择不满足
合并条件…），并在 tooltip / status bar / palette 禁用原因 / Inspector 提示
四个表面**一致**展示（同一字符串源）。

## T4 工具条/菜单信息架构（goal §6）

专业分组：Navigation / Selection / Inspection / Editing Session / Capture /
Geometry Editing / Snapping·Topology / Layer / Symbology / Factor / QA /
Layout·Export。支持按 stage 隐藏整组、按 active layer 切换组、compact mode、
overflow、高 DPI、icon-only+tooltip、键盘可发现性。不"单纯加按钮"。

## T5 图层树 V7（goal §7）

在现有树上完善（不自建第二棵业务树）。可视化：visibility、active layer、
editing target、RAW lock、stage lock、dirty、stale、error/QC count、reviewed、
frozen、published、missing、degraded（SVG/token/text 语义，禁止 emoji）。
组级状态消费真实聚合（stale count、error count、running/pending factor、
published/frozen 摘要）：组级装饰 + 图层级装饰 + hover 摘要 + 定位问题图层 +
手动排序状态正确显示 + 阶段切换不破坏展开/滚动/选择。

## T6 Inspector V7（goal §8）

类型化 Inspector 分节：Layer（name/role/type/geometry/CRS/source/version/
maturity/editability/freshness/style/visibility/opacity）、Feature（id/几何摘要/
属性/schema 校验/地质元数据）、Factor raster（factor/unit/method/parameters/
range/uncertainty/QC/source versions）、MapProduct（inputs/factor versions/
interpretation versions/run/stale/publish readiness）、Well/seismic/interpretation
（消费现有 typed 域，不伪造数据）。

## T7 视觉收敛（goal §9）

清理 legacy inline QSS、固定尺寸、内联字号、硬编码色、旧 chrome、stale emoji、
重复徽章、不一致 padding/分隔线/空态。token 单一真源；objectName 驱动；
light/dark/high-contrast × compact/comfortable 真实生效（构造期 light-snapshot
清零或 bind）；QGIS 原生 dialog 内部不强行换肤；画布与 QGIS 原生 widget 只统一
宿主 chrome。ratchet 建立（font-size、定宽、状态词表导入、emoji 禁令）且只减不增。

## T8 专业桌面布局（goal §10）

中央 QGIS 画布 + 左 Explorer + 右 Inspector + 底 task/agent/log/console +
well/seismic/mapping stage docks。处理：Hub force-float 遗留、死页面/死 preset/
死 placeholder、dock 重开路径、几何持久化、多显示器、拔显示器恢复、首跑布局、
窄屏 1366×768、2K/4K、DPR>1、tabified docks、dock float/restore。

## T9 QGIS UX 配套（goal §11）

不重写 renderer/symbol dialog。提供正确入口：Layer Properties / Renderer
Properties / Symbol Selector / Style Manager / Snapping / Topology / CRS /
Attribute Table；入口显示/可用来自 capability/context（缺桥=禁用+原因，不隐藏
 能力假象）。

## T10 Task/Agent UX（goal §12）

queued/running/degraded/success/failed/cancelled + cancelling + unavailable +
rejected + dirty output + stale output 如实呈现；retry/resume 仅当后端有；
取消中/槽位占用/新请求策略明确反馈（不伪造立即取消）。

## T11 可访问性 / DPI / 键盘（goal §13）

icon-only accessibleName、focus chain、keyboard-only 主工作流、中央快捷键
注册表（无重复）、文本输入 focus guard 统一、DPR 100–200%、对比度、
high-contrast、核心工作流 screen reader 标签。

## T12 视觉 QA V7（goal §14）

尺寸 1366×768/1600×900/1920×1080/2560×1440；主题 light/dark/HC；密度
compact/comfortable；状态：no project、project open、phase1 RAW、phase1 editing、
phase2 constraint line、phase2 factor raster、phase3 integrated、palette 禁用
原因、树 stale/error、write grant、task running、task cancelling、backend
degraded、QGIS unavailable fallback、inspector layer/factor、layout/export。
除 pixel diff 外必须有 semantic assertions。

## T13 性能（goal §17）

1000 layers、10k wells、100k catalog entries、高频 selection、tool context
refresh、task updates、主题/密度切换、树更新：差分更新、无全清重建、无逐行
QWidget、无全量物化、无事件循环阻塞。benchmark 有显式规模与内存上限。

## 结束条件（goal §19）

目标清单逐项有证据；本地相关测试全绿；三轮独立 review；P0/P1 全修+回归；
无新增架构双轨；文档与代码一致；PR 到 main；无 100GB seismic。
