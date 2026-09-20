# 07 — 高级地震显示、导出与持久化 — task_plan

- line: 07 (cpp-close wave)
- branch: `codex/cpp-close-07-seismic-display-20260920`
- worktree: `/home/kevin/project/worktrees/cpp-close-07-seismic-display`
- base: origin/main `06211541ae1ccce22b0d5ba9258ce722170ca98b`（2026-09-20 fetch 后确认，与 GitHub API 锚点一致）
- 执行器: glm5.3-flash（ZCode 会话。**平台无 /goal、/goal-loop 技能**——可用技能仅 browser-use/document-skills/skill-creator/zcode-guide，故采用本四文件持久化循环，如实记录，不伪造命令成功）
- 预算: 请求 360,000,000 tokens 上限（平台未提供配额查询接口；按需推进、完成即停，不宣称额度已生效）

## 目标（本线验收）

同一体下模式/极性/增益/clip/色表/切片和 picks 状态重开一致；导出数组值、轴和单位正确、
PNG 含真实显示；无效体、全 NaN、常量面、取消和跨体恢复拒绝错配。

## 范围（独占）

- `libs/seismic_viewer` 产品显示/导出层（属性/RGB 融合显示核、npy/csv/png 导出、视图态 schema 与持久化）
- `libs/ui_wellseis/qt/viz_d_seismic_binding`（真绑定适配，按需扩展）
- `apps/paleo_workbench_platform/closure_seismic_*`（新建；ui_wellseis 真面板绑定装配）
- `docs/development/cpp-closure-wave/07-seismic-display`（本 ledger）
- 不拥有：seismic_io 算法重写、joint 3D（06）、通用 preview registry（04/viz_e）、
  MainWindow/AppShell 全局结构（12，仅具名块租约）

## 盘点结论（2026-09-20，origin/main=06211541，开放 PR 为空）

已存在（直接复用）：
- SeismicSliceWidget：VD/wiggle、极性、percentile clip、增益、层位拾取 JSON、colorbar、
  set_volume(identity,revision)、SliceController 异步切片（tests/cpp/seismic_viewer 5 套件）
- display_core：nanpercentile clip（numpy linear parity，oracle fixture 已验）+ normalize_to_index
- viz_d_seismic_binding：make_real_seismic_view_factory + RealSeismicViewBinding（纯转发，未接线）
- libs/ui_pages_preview/qt/seismic_preview_presenter（D→E 缝，SliceController 异步真实现，smoke test 存在，
  无人调用；04 线协调文件声明由其 closure_preview_install 注册 kind="seismic"）
- libs/seismic_attributes：10 个真核（E 线 envelope/inst_phase/inst_freq/rms；S 线 sweetness/…），
  经 science::IAlgorithm，oracle fixture 已提交

缺口（=本线工作）：
1. 2D 属性/RGB 融合显示：C++ 侧无任何属性/RGB 显示路径（Python: fuse_rgb attributes.py:223、
   seismic_view.py:2169 _apply_current_attr；workbench 面板把 RGB融合 列为未实现 seismic_attribute_panel.py:32）
2. slice 导出 npy/csv/png：C++ 无（Python seismic_view.py:1880 _export_slice：npy=np.save 原始、
   csv=np.savetxt %.6f 无表头、png=widget.grab() 真实显示抓图）
3. seismic 视图态持久化：C++ 仅 picks JSON（Python: seismic_view.py:372 get_project_state →
   slice_positions/colormap/render_mode）
4. ui_wellseis 真面板绑定：make_real_seismic_view_factory 无人调用；SeismicPredictionPage 的
   SeismicViewHooks（含 show_resource）从未被设置（页面不调 view_panel_->set_hooks）→ 面板永远空占位
5. 04 可注册的真实 seismic presenter：presenter 已真实现，需验证可注册路径（注册动作归 04）

LOD/GPU/Zarr 不迁裁决复查（r6a-audit.md:15-17）：LOD 只是性能优化（有界 CPU tile 路径
SliceController+tiled_volume 即生产路径，用户能力无损）；GPU 路径 C++ 无后端（诚实降级，能力无损）；
Zarr 被 PWBVOL1 架构性替代（能力无损）。结论：维持不迁，证据见 findings.md。

## 实施顺序

R1 Qt-free 核：attribute_fusion_core（fuse_rgb parity，复用 percentile_clip_range）、
   slice_export（npy v1.0 写器 + csv %.6f 无表头）、view_state（schema v1 + to/from json + 拒绝错配）
R2 widget 集成：set_attribute_plane/set_rgb_fusion/clear_attribute（切片变更诚实失效）、
   export_slice(npy/csv/png grab 真实显示)、save/load_view_state（跨体拒绝）；
   viz_d_seismic_install 增加导出/视图态菜单
R3 产品接线：closure_seismic_install（app 层）——SeismicPredictionPage.view_panel 真绑定
   （show_resource→seismic_service open→RealSeismicViewBinding→set_view+volume_shape+光标门）、
   属性面板→E 线核对当前面计算、RGB 融合→三通道融合；app_shell 具名块租约接线；
   验证 presenter 可注册路径（不替 04 注册）
R4 验证：oracle（冻结 Python 源语义 + 已提交 fixture + 篡改自检）、
   seismic_viewer 新测试、viz_d 回归、closure 装配测试；独立审查→修复→复验；PR

## 并行协作

- 14 线资源租约：scripts/cpp-migration/invoke-resource-gate.sh（.git common-dir flock，j2 默认、峰值 j4）
- 04 线：注册 kind="seismic" 归其 closure_preview_install；我保证 make_seismic_preview_presenter 真实可注册
- 12 线：app_shell.cpp 只取 seismic_page_ 构造处具名块租约（BEGIN/END CLOSURE-SEISMIC）
- 06 线：已声明 libs/ui_wellseis geological_modeling_3d_page.cpp；我不动 joint 相关文件
- 跨主机协调：.git/codex-coordination/cpp-close-wave/07-line.json（本机文件锁不构成跨主机互斥，如实记录）
