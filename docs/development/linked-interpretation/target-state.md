# Target State — 井–震–图一体化联动解释工作站

逐项可勾选验收清单。Goal 结束前不得留下伪完成项：勾选 = 有测试/验证证据（见 verification.md）。

## L1 坐标/域契约 V2

- [x] `viz/domain_coords.py`：typed 值对象（DepthCoord[domain+unit]、MapPoint[crs]、SeismicPosition、CalibrationIdentity）+ 显式单位/深度域/CRS/校准版本。
- [x] 所有跨域换算返回带 validity + diagnostic 的结果；不可转换 fail-closed（None/invalid + 原因），绝不静默换算。
- [x] z↔TWT 的常速路径被隔离：仅显式 `velocity_assumption` 上下文可用（readout/approximate），科学转换必须走 TimeDepthCalibration。
- [x] `well_to_seismic` 常速旁路移除或改为显式 approximate 语义（调用方全部迁移）。
- [x] 兼容迁移层保留旧 tuple API，但新代码走 typed 层；隐式哨兵逐步消除。
- [x] 数值 roundtrip 测试：map→seismic→map、MD→TWT→MD（合法域内容差通过）。
- [x] 对抗测试：missing calibration / out-of-range / 非单调校准 / 非法 CRS / ft↔m 井。

## L2 WellLogEngine 原生交互

- [x] workbench：engine 后端连接 `crosshairChanged/hoverChanged` → 轮询 `hover_info()` → 发 `depth_cursor_moved`（含深度域/单位）。
- [x] workbench：`depth_cursor_supported()` 不再硬编码 False；engine 后端联动真实可用。
- [x] 子模块（well-log-engine feature branch）：暴露 `set_crosshair(document_id, depth)` / `crosshair_state()`（外部 link cursor 通道）+ `set_depth_selection(document_id, top, bottom)`（区间选择）Python 绑定。
- [x] workbench：seismic→well 方向的 link cursor set/clear 使用新绑定；widget 销毁/切换安全（无悬挂回调）。
- [x] 拾取回调：curveClicked → curve 拾取事件可用（至少 workbench 侧能读 click pick 结果）。
- [x] 程序化跳转深度/重置视口可用（reset_viewport 已有；如需 set_depth_viewport 则子模块暴露）。
- [x] 绑定测试：GIL 安全、destroyed widget 后调用不崩溃、回调释放安全。
- [x] Paleo host 不再因 native API 缺失永久硬切 Legacy（apply_default_well_backend 文案更新）。

## L3 测井处理工具箱

- [x] 新 kernel：resample、smoothing(moving avg)、median_filter、normalization(z/minmax)、clip_outliers、unit_conversion(m↔ft 等显式因子)、missing_interval_diagnostics、derived_curve calculator（受控表达式，AST 白名单，无 eval）。
- [x] 全部走 `RAW/DERIVED input → DataRun → 新 DERIVED version`；RAW 永不覆盖。
- [x] 元数据保留：original sample count、resample/decimation 参数、unit provenance（catalog parameters + LAS 头）。
- [x] kernel 纯函数单测（数值正确性）+ catalog 闭环测试（version/run/lineage）。

## L4 多井连井对比

- [x] 既有 StratigraphyCorrelationPage 能力核对：well order、shared depth range、datum mode（md/tvdss/horizon flatten）、formation tops 显示、DTW 推荐、correlation bands。
- [x] correlation link 增删改（add/remove/edit）真实可操作且写回 draft。（commit b01fb4ad + correlation_link_editor + tests/test_correlation_link_editing.py）
- [x] draft copy-on-edit + undo/redo（若 draft 支持；不支持则最小实现编辑事务）。（CorrelationInterpretationDraft copy-on-edit；页面 undo/redo 接 picks_model）
- [x] save immutable version + reopen（已有 correlation_lifecycle，验证联动页接入）。
- [x] 大井数 LOD：可见深度窗口采样，不全分辨率绘制（引擎 decimation 已有，验证接线）。

## L5 中小地震体 2D 解释

- [x] 显示控制补齐：polarity（normal/SEG normal reverse）、独立 gain（×倍率，含单位语义与 reset）、wiggle gain、opacity（2D 剖面叠加）、全部有 reset。
- [x] profile 方向切换：inline / crossline / arbitrary line（windowed 读取，接 chunked.read_arbitrary_line 或等价 ROI 采样，不整读体积）。
- [x] time slice 浏览在 profile 工作区可用（方向切换或独立入口）。→ set_profile_orientation('time') + workspace 方向选择器（tests/test_seismic_profile_orientation.py）
- [x] depth slice：仅当该 IL/XL 有可用校准（或显式 velocity assumption 标记）时提供，fail-closed 并给出原因。
- [x] horizon overlay / well trace overlay（剖面上井轨迹+GR 着色，若已有则验证）在 2D 剖面可用。
- [x] cursor/readout 保持单位明确（TWT ms / IL / XL / 振幅）。
- [x] 不引入 100GB 全量路径；ROI/window 语义保留（测试引用 read_voxel_window）。

## L6 Horizon/Fault/Pick 闭环

- [x] horizon：既有闭环（draft/undo/fingerprint/no-op/immutable/catalog/reopen）回归通过。
- [x] confidence 字段：pick 携带 confidence（至少 schema+存储支持，UI 可编辑则加分）。
- [x] seismic fault pick：新 FaultInterpretationDraft（polyline per IL/XL section）+ lifecycle 版本化；与 map fault（DomainEntity）通过稳定 id 关联而非第二权威。
- [x] fault artifact + catalog DERIVED + ProjectDocument FaultInterpretationRef 接入 + reopen 校验。

## L7 Well–Seismic Tie

- [x] 工作流：log(sonic/density) → reflectivity → Ricker/Ormsby synthetic → 与井旁道互相关 → bulk shift（显式 ms）→ 审查 → 保存。
- [x] controlled stretch/squeeze：有约束实现（分段线性、bounded 比例），或明确声明未实现并在文档记录（不得无约束）。→ 已实现：StretchSqueezeRecord ±10% 边界 + 严格递增锚点 + 单调性验证（tests/test_td_calibration_lifecycle.py）
- [x] correlation score + quality metadata 进版本。
- [x] 保存：TimeDepthCalibration artifact（td-table 格式兼容 parse_td_table）→ catalog DERIVED 版本 + run → entity_asset_link(role=time_depth) 写回 project → 重开工程后 bind_project 自动注册校准（闭环测试）。
- [x] 不自动宣称 tie verified：verified 状态只由显式 QC 通过（相关性阈值 + 人工确认）产生。

## L8 Map↔Well↔Seismic 双向联动

- [x] 案例 A：map 点井 → active well → well dock 聚焦 + seismic 定位（IL/XL，有校准才带 TWT）→ inspector 显示转换状态。
- [x] 案例 B：seismic 点 pick → map marker（spatial_cursor）+ nearest well 高亮 + well 视图显示等效 depth（有校准才显示，标 approximate/None）。
- [x] 案例 C：well cursor → seismic cursor + map marker，engine 后端同样可用（L2 解锁）。
- [x] LinkedInterpretationWorkspace 两个 dock 接入 ViewCoordinationController（现在只有状态文本）。
- [x] debounce/coalesce 全链路（well cursor 至少 100ms 级门控；seismic 已有 30ms gate）。
- [x] echo loop 防护回归测试（source tagging 差分路由）。

## L9 解释版本/溯源统一

- [x] FormationTop/Correlation、TimeDepthCalibration、HorizonInterpretation、FaultInterpretation 均有：DataRun + input versions + method/parameters + output version + quality + timestamp。
- [x] reopen 后 SelectionContext 不指向失效版本（clear_project 已清，验证 project switch 测试）。

## L10 联动工作站 UX

- [x] Link on/off 全局与 per-pane 真实生效（现在 set_linked 只改 badge 文本）。
- [x] current domain badge（MD/TVDSS/TWT）+ conversion unavailable 原因显示 + sync status。
- [x] 布局 preset「解释工作区」（Map 中央 + well/seismic dock 打开）。
- [x] panel lazy load 保持；native backend 状态诚实显示（engine/legacy + 原因）。
- [x] 样式消费 Design System tokens，不新建平行主题。

## L11 对抗性科学验证

- [x] 测试矩阵全项：missing well head、invalid CRS、ft 井、m 井、missing calibration、non-monotonic calibration、out-of-range TWT、no nearby well、project switch、view destroyed、backend unavailable、repeated open/close、rapid cursor move、corrupted interpretation artifact、save/reopen、cancellation、small seismic window。
- [x] roundtrip：map→seismic→map、MD→TWT→MD 容差断言。

## 交付

- [ ] well-log-engine 子模块 feature branch + PR（如 L2 需要子模块改动）；主仓库 gitlink 更新。
- [ ] 三轮 review（Correctness/Architecture/UX-Perf-Adversarial）完成且问题修复。
- [ ] 主仓库 PR 到 main（不等待 CI）。
- [x] 不运行 100GB benchmark。
