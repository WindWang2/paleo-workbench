# 06 — 联合 3D 真实宿主、异步切片与会话恢复 — task_plan

- line: 06 (cpp-close wave)
- branch: `codex/cpp-close-06-joint3d-20260919`
- PR: https://github.com/WindWang2/paleo-workbench/pull/1417
- HEAD: 92868b3b（a719375a 主体 + 92868b3b 审查修复）
- worktree: `/home/kevin/project/worktrees/cpp-close-06-joint3d`
- base: origin/main `06211541ae1ccce22b0d5ba9258ce722170ca98b`（开工时 origin/main 即此 SHA，fetch 后确认）
- 执行器: glm5.3-flash（ZCode 会话，无 /goal /goal-loop 平台技能——采用本四文件持久化循环，如实记录）
- 预算: 请求 360,000,000 tokens 上限（平台未提供配额查询接口，按需推进、完成即停）

## 目标（本线验收）

真实井+体数据 → 场景 → 剖面/拾取 → 保存重开；快速切片/销毁窗口/取消/工程切换不阻塞或越界；
软件 GL 与硬件 GL 分开记录至少真实渲染证据；缺 GPU/缺数据明确降级。

## 范围（独占）

- `libs/geo3d_viz` joint host/scene controller/volume adapter 扩展
- `apps/paleo_workbench_platform` 的 viz_c_joint_host/viz_c_joint_volume/viz_c_time_map + closure_joint3d_*
- `libs/ui_wellseis` 联合 3D 页面适配（geological_modeling_3d_page）
- 不拥有：地震 2D 显示核（07）、MainWindow 全局重构（12，仅具名块租约）

## 盘点结论（2026-09-19, origin/main=06211541）

已存在（C 线交付，直接复用）：joint 核 11 组件、VizCJointHost（真实 host，open_volume 已走 JobCenter）、
Geo3DDock 组合根、viz_c_joint_example、oracle 测试。开放 PR 为空，无重复实现风险。

缺口（=本线工作）：
1. **产品 shell 仍装配 UnavailableJointHost**（app_shell.cpp:49,180）——真实 host 从未注入页面。
2. **pwb_job_center 属性错位（C 线潜伏缺陷）**：main_window.cpp:460 设在 MainWindow，
   geo3d_dock.cpp:240 在 dock 上读 → 产品里 joint_host() 恒为 nullptr。
3. **GUI 冷 tile 读取**：VizCTimeSliceMap::refresh() 在 GUI 线程 scene_->slice_time(active)；
   assemble_joint_objects() 的 fence 帘幕/活动切片 mesh 构建同样在 GUI 线程读体。
   C 线注释明言"moving them to jobs is future work with prepared-slice injection
   (VizCTimeSliceMap::set_prepared_slice is the seam)"——即本线任务。
4. **单 fence 渲染**：assemble_joint_objects 只对 active fence 提取（extract_active_fence）；
   核已有 fences() 列表管理但 3D 只画一个。需 per-fence 提取 + 管理 UI。
5. **状态持久化无工程身份**：save_state 用全局 QSettings key `viz_c/joint_state`，
   换工程会串状态。需工程身份键 + 切换不越界。
6. **readiness_inputs 潜伏竞争**：main_window.cpp:3011 GUI 直接读 store document()
   （#1380 audit 记录的 rebind_layer 边界），需锁定投影读。
7. **坐标/单位说明缺失**：页面无 inline/xline 号↔索引、TWT ms/Depth m、世界坐标说明。

## 实施顺序

R1 产品接线：property 错位修复 + shell 注入真实 host（UnavailableJointHost 退役为无
   GEO3D_VIZ 时的诚实降级）+ 工程身份状态键。
R2 异步切片：时间平面 prepared-slice 走 JobCenter（generation/cancel/销毁守卫）+
   3D 帘幕/切片 mesh worker 化（staged apply on GUI）。
R3 多 fence：scene 增 extract_fence(fence_id)（复用 C 线提取核）、host 组装全部可见
   fence、页面 fence 列表（激活/删除/可见性）。
R4 会话恢复闭环：保存重开 roundtrip 测试（QTemporaryDir+QSettings 隔离）、
   readiness_inputs 锁定投影读、坐标/单位说明卡。
R5 验证：受影响测试 ×2、示例双 GL 路径证据、降级路径；独立审查；PR。

## 资源约束

- invoke-resource-gate.sh 全程持锁；j2 默认；CTest 并行 ≤2；OMP/BLAS=1。
- 构建 dir: <worktree>/build；QGIS/WLE/ONNX SDK 只读。
