# Verification — linked-interpretation-v5

记录每次本地验证的命令、范围、结果。禁止伪完成：target-state.md 的勾选必须能在本文件找到对应证据。

## 环境命令

- 全量/定向测试：`/home/kevin/projects/paleo_project/run_env_li.sh [pytest args]`
- 单 python 进程：`/home/kevin/projects/paleo_project/run_env_li.sh --python <script>`
- wrapper 契约：PYTHONPATH 指向本 worktree 的 geo-viz-engine(+packages) 与
  `well-log-engine/build/dev-python/python`（Shiboken 绑定）；
  `LD_PRELOAD="/usr/lib/libstdc++.so.6 …/libxmlshim.so"`（绑定需系统 GLIBCXX_3.4.35）。
- 子模块绑定构建：`cd well-log-engine && /usr/bin/cmake --preset dev-python && cmake --build --preset dev-python`
  （并发 2；~/.local/bin/cmake 是坏的 shim，必须用 /usr/bin/cmake）

## V1 — L1 typed contract + hub fail-closed（commit 01c9f981）

`run_env_li.sh tests/test_domain_coords_contract.py tests/test_view_coordination_seismic_producer.py tests/test_coordinate_hub_stress.py`
→ 63 passed。
`… tests/test_view_coordination_wiring.py tests/test_geological_context_scenarios.py tests/test_challenger_m6_adversarial_stress.py tests/test_workstation_well_backend.py tests/test_well_log_canvas_panel.py`
→ 78 passed, 1 failed（wiring 断言旧 approximate-MD 语义）→ 改为显式 set_velocity 后 11 passed。
覆盖：单位（m/ft 往返、非有限拒绝）、fail-closed 矩阵（无校准/范围外/非单调构造拒绝/未知井）、
MD↔TWT 往返（容差 1e-6）、map↔seismic 往返（含剪切网格、1e-6）、CRS mismatch 拒绝、
velocity 显式化（未声明 → ValueError；VelocityAssumption authority 标记）、KB/TVDSS 一致性。

## V2 — L2 native 交互（子模块 f40324a + host commit f9ff5155）

- 子模块构建：`cmake --build --preset dev-python` exit 0；`tests/python/` 37 passed
  （含并行贡献者的 test_linked_interaction_bindings.py：crosshair reference-depth 往返、
  clamp、clear、非法输入/未知文档拒绝、主轴选择、viewport、GUI 线程拒绝）。
- 绑定可用性：python3.13 下 `from welllog import WellLogView` +
  set_crosshair/clear_crosshair/crosshair_state/set_depth_selection/set_viewport_depth_range/click_pick_info 全部在。
- host：`run_env_li.sh tests/test_well_log_engine_interaction.py tests/test_well_log_canvas_panel.py tests/test_workstation_well_backend.py tests/test_issue1053_well_log_host_engine.py`
  → 57 passed, 1 skipped；真绑定 `tests/test_welllog_engine_native_integration.py` → 2 passed
  （基线环境该文件因"绑定契约零覆盖"FAIL，现已修复）。
- 修复的问题：echo 护栏需在 setter 调用前布防；护栏语义改为值匹配（浮点往返容差）。

## V3 — L7 校准版本化（commit 4765387*）

`run_env_li.sh tests/test_td_calibration_lifecycle.py tests/test_td_calibration_str_paths.py tests/test_well_tie_host.py`
→ 34 passed。
覆盖：bulk shift、bounded stretch/squeeze（±10% 边界拒绝 + 单调保持 + 区间界）、
重复 MD/非单调 TWT/数组不匹配拒绝、TD 表写读往返（parse_td_table 同解析器）、
TVDSS hub 一致性（垂直+斜井）、指纹稳定性、save→DERIVED+run 质量参数、
verified 双向门控（阈值 0.70 AND 显式 reviewer）、重复保存 demote 旧 primary link、
reopen 携带 version_id/fingerprint/metadata、bind_project 闭环注册、坏 artifact 拒绝。

## V4 — L8 双向联动（commit 后 85 passed）

`run_env_li.sh tests/test_linked_workspace_coordination.py tests/test_view_coordination_wiring.py tests/test_view_coordination_seismic_producer.py tests/test_workstation_well_backend.py tests/test_geological_context_scenarios.py`
→ 85 passed。
覆盖：case A（任意视图选井 → dock sink，sink 异常不破坏路由）、case B（校准 MD 驱动 link cursor；
approximate 不驱动；authority-less 清除一次；clear_project 重置）、case C（dock 面板以自身井名发布；
无名面板不发布）、apply_link_cursor 井匹配门控矩阵、AppShell sink 注册 + 组合 locate（运行时查 dock 面板）。

## V5 — L6 fault picks（commit 后 56 passed）

`run_env_li.sh tests/test_fault_section_picks.py tests/test_fault_interpretation_ui.py tests/test_stratigraphic_interpretation.py tests/test_lifecycle_registration_gaps.py`
→ 56 passed。
覆盖：picks artifact 往返（confidence None≠0）、指纹覆盖 picks/map link/confidence、
非法 section kind 拒绝、save 带 provenance（pick/seismic/map-linked 计数、domains、crs）、
reopen 恢复 picks+关联、display-only no-op、pick 变更分支新版本（父链）、map-only trace 不回归。

## V6 — L10 UX（commit 后 31+6 passed）

`run_env_li.sh tests/test_linked_workspace_ux.py tests/test_workstation_well_backend.py tests/test_linked_workspace_coordination.py tests/test_view_coordination_wiring.py`
→ 37 passed。
覆盖：换算状态显示校准 authority / 无校准显式"不可用"（不静默空白）、状态订阅只读（不发布）、
link off 阻断 seismic locate / link cursor / 深度广播三条路径、preset「解释工作区」存在（dock_manager.py:99）。

## V7 — L11 对抗矩阵（commit 后 24 passed）

`run_env_li.sh tests/test_linked_interpretation_adversarial.py tests/test_linked_workspace_coordination.py`
→ 24 passed。
本文件矩阵项与既有覆盖映射：
- missing well head / invalid CRS / ft·m 井 / missing calibration / non-monotonic / out-of-range TWT / no nearby well
  → 本文件 + test_domain_coords_contract.py
- project switch → 本文件 test_project_switch_clears…（+ controller 级已有 clear_project 测试）
- view destroyed → test_well_log_engine_interaction.py::test_set_link_cursor_survives_destroyed_view
- backend unavailable → test_workstation_well_backend.py（legacy 诚实回退系列）
- repeated open/close → 本文件；rapid cursor → 本文件（+ panel 级 gate 测试 in L2/L8）
- corrupted artifact → 本文件（fault JSON / TD 表）+ test_interpretation_lifecycle.py（horizon 写失败不腐蚀工程）
- save/reopen → L6/L7 各自闭环测试 + test_interpretation_lifecycle.py
- cancellation → 既有 seismic 侧（test_seismic_volume_source latest-wins/single-flight；SliceReadWorker 取消）
- small seismic window → 本文件（纯几何零体积访问）+ 既有 test_seismic_volume_source ROI 语义
- roundtrip map↔seismic、MD↔TWT → test_domain_coords_contract.py
发现并修复：dock 深度路径无控制器侧门控（可能被原始 emitter 洪泛）→ 已加 120ms 防御门。

## V8 — 回归汇总（阶段性）

每次 commit 前跑相关套件；截至 L11 提交，本 Goal 新增/修改测试合计：
test_domain_coords_contract / test_well_log_engine_interaction / test_td_calibration_lifecycle /
test_linked_workspace_coordination / test_linked_workspace_ux / test_fault_section_picks /
test_linked_interpretation_adversarial + 迁移的 producer/wiring/canvas/workstation 测试。

## V9 — 三轮 review（见下方追加记录）
