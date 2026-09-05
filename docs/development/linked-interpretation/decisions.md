# Decisions — linked-interpretation-v5

按时间序记录架构决策（ADR-lite）。每条：背景 → 决策 → 理由 → 影响。

## D1（2026-09-06）分层策略：typed 契约层包住 CoordinateTransformHub，不重写 hub

背景：L1 要求显式单位/深度域/CRS/校准版本 + fail-closed 结果。CoordinateTransformHub 已被 ViewCoordinationController、若干测试和井震 3D 页消费。
决策：新增 `viz/domain_coords.py` 作为 typed 契约层（值对象 + 换算结果 + diagnostics），内部委托 hub 的几何/插值内核；hub 的常速 z↔TWT 路径标记为 approximate-only，科学路径一律经 typed 层。旧 tuple API 保留为兼容层。
理由：避免第二套坐标权威（禁止事项），迁移可增量进行，调用方可逐个切换。

## D2（2026-09-06）L2 双轨：host 侧先用"无参信号 + hover_info 轮询"，子模块补外部 crosshair/区间选择绑定

背景：绑定已有 hover_info()（含 display_depth）与无参信号 crosshairChanged/hoverChanged；C++ session 已有 SetCrosshairCommand 与 set_selection(深度区间)，未暴露。
决策：
1. workbench 侧立即用现有绑定实现 cursor 深度联动（信号→轮询），解除 engine=False 硬编码；
2. well-log-engine feature branch 暴露 `set_crosshair(document_id, depth)` / `crosshair_state()` / `set_depth_selection(document_id, top, bottom)`（typesystem add-function + numpy_bridge 胶水，沿用现有 inject-code 模式）；
3. 子模块单独 branch/commit/PR，主仓库只 bump gitlink。
理由：host 侧改动不依赖子模块构建即可落地测试；外部 link-cursor 是双向联动的必要通道，C++ 通道已在（SetCrosshairCommand 有测试），风险低。

## D3（2026-09-06）绑定环境：LD_PRELOAD 系统 libstdc++；不重建 vendored QGIS

背景：Shiboken .so 链接系统 GCC 的 GLIBCXX_3.4.35；/opt/miniconda3 的 libstdc++ 较旧。主 worktree 的 well-log-engine build 陈旧（缺 pinned commit 的四个绑定入口）。
决策：本 worktree 用 preset `dev-python` 重建一次绑定（并发 2），wrapper 恒定 `LD_PRELOAD="/usr/lib/libstdc++.so.6 libxmlshim.so"`。vendored QGIS 完全不动（本 Goal 不改其 ABI）。

## D4（2026-09-06）L7 校准落盘格式复用 TD-table 生态

背景：bind_project 只认 role=time_depth 资产且用 parse_td_table 解析（SMI 列序 TIME TVDSS TVD MD）。
决策：tie 保存的校准写成同格式 `.dat`（+# 注释井名行），catalog DERIVED 注册 + entity_asset_link(role=time_depth, entity=well) 写回。重开工程即可被现有路径注册——不造第二套标定权威。
约束：verified 状态存 catalog run parameters（quality 字段），只有 QC 阈值 + 显式人工确认才置 verified。

## D5（2026-09-06）fault 解释与 map fault 的关系

背景：project 已有 FaultInterpretationRef（project/models.py:222）与 map 侧 fault DomainEntity；禁止建立冲突权威。
决策：seismic fault pick 的 FaultInterpretationDraft 以 `domain_fault_id`（map fault 的稳定 id，可空）关联 map fault；没有关联时是独立 seismic 解释对象。版本化走 interpretation_lifecycle 同构管线（artifact=.fault_interp.npz/json + catalog DERIVED + project ref）。map fault 仍是编图域权威，seismic fault 是解释域对象，二者通过 id 引用。

## D6（2026-09-06）L5 arbitrary line 走 windowed 采样

背景：chunked.read_arbitrary_line（bilinear 4 道插值）无 UI 消费者；现有 arb line 基于 preview 体。
决策：2D 解释工作区的 arbitrary line 用 SeismicVolumeSource/chunked 的窗口采样路径按需生成剖面（ROI-friendly），preview 途径仅作 3D 页现状保留。

## D7（2026-09-06）L8 工作站接线以 ViewCoordinationController 为唯一总线

背景：LinkedInterpretationWorkspace 现在只发状态文本。
决策：dock 面板作为普通 view 接到 controller（sink 注册 + source 发布），不在 workspace 内新造总线；per-pane link 开关在面板层过滤（不再发布/不再消费），不绕过 controller。

## D8（2026-09-06 02:05）并行会话协调（同一 worktree 双实例）

背景：检测到同一 worktree 存在两个活跃 agent 会话（同一 Goal 的重复派发）：submodule 出现非本会话 commit（5324b27、f40324a——后者吸收了本会话 staged 文件），main repo 出现非本会话未提交修改（view_coordination.py / coordinate_hub.py / test_view_coordination_seismic_producer.py）。
决策：
1. **不终止、不回滚对方工作**——两个实例产出并入同一 branch，PR 以最终分支内容为准。
2. **文件级避让**：动手改任何文件前 fresh Read；提交前 `git status` + `git log` 核查，只 `git add` 自己明确产出的文件。
3. **包级认领**：本会话当前认领 L3（workflow/curve_interpretation.py + data_page 曲线操作 UI）与 L5（seismic 显示控制）；L1（coordinate_hub/view_coordination）由并行会话正在实施，本会话后续只做 review/验证，不并行重写。
4. 任何会话发现目标文件已被对方修改时，先读对方实现再决定增量补充，不做整文件覆盖。
影响：commit 历史会混合两个实例的贡献；target-state.md 勾选时以分支最终状态为准。
