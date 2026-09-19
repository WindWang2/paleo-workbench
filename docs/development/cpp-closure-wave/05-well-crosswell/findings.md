# 05 — findings.md（盘点与发现）

- 盘点轮：2026-09-19，基线 origin/main 06211541，worktree /home/kevin/project/worktrees/cpp-close-05-well-crosswell
- 平台：Linux x86_64，gcc 16.2.1（/usr/sbin/g++），**cmake 本机原缺** → 用户级安装 ~/tools/cmake-4.1.2-linux-x86_64/bin/cmake 4.1.2；ninja 存在但 shell alias 注入 -j40（脚本内 cmake --build --parallel 显式传参不受影响；直接调 ninja 必须显式 -j≤4 覆盖，alias 展开后最后一个 -j 生效）；Qt6 在 /usr；内存可用 ≈40 GiB；nproc 40（上限仍按波次合同 j4/j2）。

## 环境事实
- 子模块：well-log-engine @ f845e7ab、geo-viz-engine @ 08851951 已在本 worktree 初始化；third_party/gdal、third_party/proj 未初始化（平台全量构建才需要）。
- QGIS SDK：/home/kevin/pwb-sdks/root/usr/{include,lib,bin,share} 在本机**存在**（A 线机器上曾缺）。
- 本机无 Python venv、无 pip；python3 3.14.6（stdlib 可用于 oracle 生成；不引入运行时依赖）。
- /goal、/goal-loop：平台无此命令（可用技能清单核实），按任务文件用文件持久化循环替代，已记录于 task_plan.md。

## 已实现/已合并（不重复做，直接复用）
- LAS 解析：WLE `LasSourceAdapter::parse`；生产 load_fn `libs/ui_workers/src/wle_load.cpp`（make_wle_load_fn，LAS-only，XML → nullopt 诚实降级）。
- ingest LAS 预览：`libs/ingest/src/preview/las_preview.cpp` + `las_wle_bridge.cpp` + registry VIZ-A 分支。
- DTW：`libs/well_science/src/dtw.cpp`（numpy parity）+ `libs/ui_workers/src/dtw_propagation.cpp`（banded SC，JobCenter job kind "compute.dtw_propagation"）。
- 标定/合成/自动tie：`libs/visualization/src/well_tie/`（Qt-free，oracle 测试在）；`cross_well/seismic_tie.cpp` checkshot CSV。
- 绘制：`libs/visualization/src/well_log/`（WLE 宿主 widget、track layout、viz_a_patterns、robust_scale）+ `cross_well/`（section canvas、tops/picks 模型含 undo/redo、formation preview、auto planner）。
- 报告：`cross_well/qt/report_export.cpp`（A4/A3/A2 PDF/SVG/PNG）+ `well_tie/qt/report_export.cpp`。
- App 层：`apps/paleo_workbench_platform/`：viz_a_install（菜单→JobCenter→WellLogHostWidget::load_document）、viz_b_cross_well_dock（两 tab：连井剖面/井震标定；JobCenter DTW；sidecar 持久化 cross_well_workspace.json：picks/tops/links/top_meta/view/well_source，300ms coalesce，restore bump session_generation_ + 自动重载 well_source；openProject 先 handle_project_closed；close flush）、well_log_track_panel、viz_e_install（ExternalPresenter 注册表）、job_center。
- 会话：ProjectDocument .paleo.json（schema v2，三阶段保存）；viz-b sidecar 是 B 专属文件（注释：schema 已为未来 cross_well_workspace 顶层节点成型）。
- 测试资产：viz_a.*（6）、viz_b.*（6，含 dock_smoke 真实 dock+JobCenter）、well_science.dtw、ui_workers.oracle/lifecycle、ingest.parsers、platform.*。

## 缺口 → 本线任务映射（证据）
1. **XML worker 真加载**：wle_load.cpp:107-111 非 LAS → nullopt → viz_resolve.cpp:127 "无法解析 LAS 井数据"。C++ XML 表格预览已存在（`libs/ingest/src/preview/well_log_xml_preview.cpp`，385 行，WITSML curveInfo/logData + SpreadsheetML worksheet + record/point 三 pass），但**加载**（构造 welllog::WellLogDocument 进 worker/dock 链）缺失。Python 参考：`paleo_workbench/resources/well_log_xml.py`（is_well_log_xml 识别：WITSML tags / SpreadsheetML 工作表名 测井曲线|welllog|well log|log curves）。
2. **B 真实 LAS 数据通路**：viz_b_cross_well_dock.hpp:69-70 注释明示 "LAS arrives through the same seam once line A's parser merges"——dock 目前只吃 JSON 井库 + CSV tops/checkshot。需把 wle_load 的 WLE document 曲线转成 dock 的井列数据。
3. **A 共享井身份**：全链身份=井名字符串（WellColumnData::name、WellLogDocumentInput.well_name）。ui_wellseis 已有 well_identity_asset_id/well_identity_map seam（JointHostController::well_identity_map，platform 的 UnavailableJointHost 返回空）。需最小共享身份概念打通 A（LAS 井）↔B（连井列）。
4. **ui_workers_lifecycle_test.cpp 是空壳**：`int main(){return 0;}`（CMake 注释承诺取消/迟到覆盖）。验收要求"取消和迟到结果""真实 dock 测试覆盖对象销毁而非仅编译"。
5. **04 消费 presenter**：ui_pages_data preview_dispatch 有 "well_log" mode 表项；现成 presenter 模式 = `libs/ui_pages_preview/qt/seismic_preview_presenter`（moc-free、session generation、经 viz_e ExternalPresenter 注册）。well/time-depth presenter 不存在——本线交付物（对 04 的唯一接口）。
6. **连井会话恢复/结果来源显示**：sidecar 已存 well_source 且自动重载；需核对"结果来源显示"（UI 上可见数据/结果出处）与跨工程切换行为（B 已修 openProject flush；补测试）。
7. **pattern 近似与导出行为**：viz_a.patterns 测试在（42 图案探针）；复验并记录，发现分歧才改。
8. 深度单位/缺曲线/反向深度：WLE LAS 已覆盖（A 线 fixture）；XML 加载路径需同覆盖（本线新测试）。

## 接口归属（合同）
- 05 → 04：well/time-depth presenter（本线新建；走 viz_e ExternalPresenter 注册 seam + ui_pages_data dispatch）。
- 井震 3D：06（app_shell UnavailableJointHost 不可动其语义）；报告模板短写：13 分工，避免双修。

## 决策记录
- XML 加载构造 WLE document（WellLogDocumentBuilder + SamplingAxis + Curve），与 LAS 路径同一载荷类型 WleDocumentPayload，消费者无差别——真加载而非旁路数据结构。
- 识别语义严格对齐 Python is_well_log_xml（WITSML 三件套 log/curveinfo/logdata 或 witsml 根 + 两件套，或具名工作表），不放宽；非井 XML 保持诚实消息。
- oracle：XML 解析对冻结 Python（stdlib ElementTree 转录 well_log_xml.py 识别语义）生成 fixture，含负面自检（非井 XML 必须不识别）。
