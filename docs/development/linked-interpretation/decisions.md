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
决策：seismic fault pick 的 FaultSectionPick/FaultTrace 以 `map_fault_id`（map fault DomainEntity 的稳定 id，可空）关联 map fault；没有关联时是独立 seismic 解释对象。版本化走 interpretation_lifecycle 同构管线（artifact=.fault_interp.npz/json + catalog DERIVED + project ref）。map fault 仍是编图域权威，seismic fault 是解释域对象，二者通过 id 引用。

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

## D8（2026-09-06）三轮 review 结论与已接受风险

修复项见 commit "fix(review)" 与 engine commit（R1-B1）。以下为评估后**接受现状**的项（含理由）：

- R1-m3 well_section_overlay 用取整后 IL/XL 过滤距离（±0.5 bin 误差）：hub 无小数测线访问器；正确修法需在 hub 暴露浮点几何访问器并重算（影响面跨 collaborator 文件），留待后续。当前 max_line_offset=1.0 的语义按 bin 位数级近似解释。
- R1-m6 resample 的 interp_nan_aware 跨缺失区间线性内插：重采样的标准语义；模块承诺"不把缺失变 0"仍成立（NaN 保持 NaN，仅有限样点间插值）。若需保留缺失区间，应在 derive/诊断流程使用 missing_interval_diagnostics 后再决定。
- R1-m7 merge_session_links 可能保留指向已删 top 的手工链接：L4 collaborator 在制；reopen 后 link 编辑器以现有 tops 校验显示。记录待其后续处理。
- R1-m10 unit_conversion 信任用户输入源单位：L3 对话框在制；操作 provenance 已记录参数，可审计回滚。建议后续在对话框预填曲线头单位。
- R2-m3 旧 correlation 工件 link-id 规范化导致首次 resave 指纹漂移：一次性迁移噪音（科学内容不变），接受。
- R3-m5 绑定"存在但损坏"时构造崩溃（H13 既有决策）：宁可崩也不静默降级；dock 路径同样传播。保持。
- R3-m6 任意选井自动弹出 well dock：case A 设计意图；"用户关闭后不再弹出"的闩锁记为后续 UX 迭代。
- R2-M4 子模块 commit 推送顺序：交付时先推子模块分支再推主仓库（本次执行）。

## D9（2026-09-06）并行协作模式

本 Goal 执行中存在同 worktree 的并行贡献者（井–震方向：L3 曲线工具箱、L5 引擎显示控制/任意线/井迹投影、L4 link 编辑）。分工边界自然形成：本 agent 负责 L1/L2/L6/L7/L8/L10/L11 与 review 修复；重复实现（fault_interpretation.py 草稿）在发现既有 fault_lifecycle.py 后立即删除。所有合并提交均通过测试门。
