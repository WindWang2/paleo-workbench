# 3D Geological Modeling V5 — Verification Log

本地验证记录（持续追加）。环境：`run_env_g3d.sh`（conda py3.13，offscreen，
PYTHONPATH 指向本 worktree 子模块）。并发约束：native 构建 ≤2，Qt 测试小批。

## 基线（实现前）

- 2026-09-06 targeted 3D 套件：80 passed / 3 skipped / 1 failed
  （`test_geological_modeling_3d_page_clip_and_tie_without_show` maximumWidth
  flake —— origin/main 同样失败，记入 E5 待修）。

## 阶段验证（实现中逐项追加）

- 子模块 scene objects（feat/scene-object-overlays）：
  `tests/test_scene_objects.py` + `tests/test_scene_render_to_world.py`
  18 passed；geoviz_seismic 全量 1752 passed / 6 skipped（无回归）。
- 主仓 geomodel V2 模块：domain 23 + builders 19 + qc 18 + exporters 16 +
  measure/section 14 + scene_adapter 18 = 108 headless 用例全绿。
- 页面集成：joint_layout / stratal_entry / joint_page / 3d_page /
  joint_persistence / well_pick / layer_visibility / cross_page_sync /
  view_coordination / context_scenarios 89 passed；
  V5 集成（含 30 轮 project 切换 teardown）16 passed；
  规模基准（100/500/1000 井、50 面、decimation、内存上限）7 passed；
  provenance 流 6 passed。
- 页面导出入口接 V2（体积对象→FLAC3D/Abaqus、面片→OBJ/STL/VTP），遗留
  GridSpec 路径保留且诚实标注 LEGACY。
- 既有 flake 修复：`test_geological_modeling_3d_page_clip_and_tie_without_show`
  的 maximumWidth<=320 断言与页面契约矛盾（:793 注释明确 cap=QWIDGETSIZE_MAX），
  改为 minimumWidth>=220 + maximumWidth>=QWIDGETSIZE_MAX 的确定性断言；
  `test_geological_modeling_3d_page_ui_elements` 改断言 V5 workspace
  （gl_widget 已按 ADR-01 移除）。

## 最终验证

### 全量回归与环境 forensics

- **origin/main 基线**（本机 conda py3.13/offscreen，同 deselect）：
  75 failed / 5236 passed / 214 skipped / 2 errors，**无段错误**，
  14:38 完成。失败集合为预存环境失败（mapping/native-render 区域：
  test_native_*、test_unified_map_*、test_scalar_raster_mirror、
  test_composite_qgis_canvas、test_project_paths、test_tiled_onnx 等），
  与本分支失败集文件级 diff 为空（无本分支引入的回归；
  test_app_shell 导航与 geoviz facade 两处初始回归已修复，见 commit a637464c）。
- **全量段错误 forensics（预存环境 flake）**：本分支与 origin/main 的
  3106-test 前缀会话均以 SIGSEGV 退出（coredumpctl 证据：PID 416777 为
  origin/main 运行）；gdb 栈：`gc_collect_main → subtract_refs` 于 Qt
  信号分发期间的 Python GC —— CPython GC 穿越半析构 Qt wrapper 的已知
  崩溃窗口，与测试顺序/时序相关（origin/main 全量 5631 通过、同前缀即崩）。
  处置：非本分支引入；本分支做了引用环加固（weakref viewport provider +
  shutdown 前清场景，commit 141ae024）缩小窗口，并在此记录证据供后续追查。
- **环境契约补充**：worktree 的 run_env wrapper 必须包含
  `$ROOT/well-log-engine`（native `seismic_3d_core` .so 的发现路径），
  否则 marching-cubes/native-status 系列出现假失败（.so 为子模块
  checkout 内未跟踪构建产物，从主 checkout 复制）。
- 三轮 review（correctness / architecture / adversarial-performance）
  的修复分别见 commit 68dc7378、b0d04993 及子模块 4a068822。

### V5 验收对照（target-state.md）

- A1–A6：domain/scene 解耦（scene_adapter + 引擎命名对象 API）、
  隐藏视口移除、无私有 reach-in（_stratal_surfaces/_loaded/_clip_planes
  均改公开路径）——已实现并有测试。
- B1–B6：井轨迹（measured + 诚实 simplified_vertical + 井名标签 +
  选中高亮）、层位（NaN 空洞保留、decimation 上限、属性/置信度字段）、
  断层（3D mesh 与 2.5D curtain 显式表示）、地层体（闭合 shell + QC +
  柱状六面体）、facies 着色——已实现。
- C1–C6：剖切（bounds 推导、box/invert/reset、逐对象 clip planes、
  重新可见时补投递）、剖面交线（section.py + 测试）、拾取闭环
  （mesh + line 拾取、树同步、well_selected 广播带 source tagging）、
  Inspector（identity/CRS/unit/QC/provenance/stats）、测量（6 种，
  domain 单位）、相机（fit/preset 持久化）——已实现。
- D1–D5：QC 四级阶梯 + blocker 导出门禁；FLAC3D/Abaqus 真实体导出 +
  OBJ/STL/VTP + 五个 parser 回读验证 + provenance sidecar；
  Catalog 经 register_modeling_run/register_export_output。
- E1–E5：token 缓存零重建（blake2b 内容地址 + scene identity）、
  规模基准（100/500/1000 井、50 面、内存上限、decimation）、
  30 轮 project 切换 teardown、GL-less 降级、maximumWidth flake 修复。
- F1–F6：新增 9 个主仓测试文件 + 2 个子模块测试文件，全部本地通过
  （计 ~190 个新用例）；全量回归以 origin/main 基线比对判定零回归。
