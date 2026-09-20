# 08 — progress（逐轮记录：候选 SHA / 命令 / 退出码 / 发现 / 下一步）

## R1（2026-09-20）盘点与基线

- 候选基线：origin/main `06211541ae1ccce22b0d5ba9258ce722170ca98b`（fetch 后确认；
  开放 PR #1412 = mapping_document 桥编辑域，登记为依赖）。
- 分支/工作区：`codex/cpp-close-08-mapping-authoring-20260920` @
  `/home/kevin/project/worktrees/cpp-close-08-mapping-authoring`。
- 资源门：`invoke-resource-gate.sh Configure/Build`，j2；工具链
  `/home/kevin/pwb-sdks/root/usr/bin/{cmake,ninja}`（cmake 需
  LD_LIBRARY_PATH=.../usr/lib 引 librhash）；QGIS vendor 产物只读复用主工作区。
- 命令/退出码：
  - gate Configure（Release，PLATFORM/DATA/SCIENCE/MAPPING_KERNEL/CONV_01/CONV_16 ON）
    → exit 0，Generating done。
  - gate Build -j2（全量基线）→ exit 0，1163/1163 全绿（含我方 CMake 改动后的增量混编）。
- 发现：见 findings.md（三杜撰符号、面板 getter 缺口、场景从未实例化、
  project schema 已有 paleomap_documents/contour_drafts/factor_map_tasks 段等）。

## R2–R5（实现轮 1，待构建验证）

代码落地面（全部为本线文件或命名块/租约）：

1. `libs/ui_seqviz`：composition_panel.cpp 对齐真实 core API 重写
   （history_state/property_geometry_state/schema_editor_descs；Python 语义的
   值转换助手 schema_bool/float/text_value 新增入 core；duplicate_element/
   set_locked/bring_to_front/send_to_back；geometry 字段 x/y/w/h；series 表
   标签/数值两列直接提交；document_io 原子保存/恢复载入）；CMake 入 target
   （+Qt6::Svg）；新增 ui_seqviz.composition_panel 测试。
2. `libs/ui_pages_data`：preparation_page.cpp 交付（splitter 组装、代数守卫、
   target 守卫、切工程作废、QC/制备/等值线全生命周期、诚实占位标签）；
   CMake 头+TU 同时入 target；新增 ui_pages_data.preparation_page 测试；
   hub_page 增加 adopt_submodule（与 04 的 replace_submodule 不同名，登记调和）。
3. `apps/paleo_workbench_platform/closure_mapping_document.{hpp,cpp}`：
   MapDocumentBank（多图件 bank、绑定/保存(document_io apply + view_state)/
   放弃(重绑 saved copy)/切换守卫(保存/放弃/取消；无守卫面且脏=拒绝)/
   persist 缝）。
4. `apps/paleo_workbench_platform/closure_mapping_install.{hpp,cpp}`：
   - MappingPage 四占位 adopt + WorkerHost 离线程编组；
   - composer 注册面子集（registry.py 忠实数据：分类/几何/默认属性/属性
     schema/CHART_SERIES_SCHEMAS）；预览/导出引擎未接线 = 面板诚实失败面；
   - PreparationPage 真装配：TaskPanelShim/WellTableShim(自带 QC 行)/
     PreviewGridShim + BoundaryPanel；制备走诚实失败结果（网格计算内核未
     移植=跨线依赖，登记）；等值线走真核（ui_workers compile + viz_charts
     marching squares），draft→Json 写回工程 contour_drafts。
5. `libs/ui_map`：mapping_page adopt_* 四方法 + map_dock_manager adopt_panel_widget
   （BEGIN/END CLOSURE-MAPPING 租约块）。
6. `apps/paleo_workbench_platform/app_shell.{hpp,cpp}`：adopt_preparation_page
   （租约）；`main_window.cpp`：CLOSURE-MAPPING 命名块（include + install 调用）。
7. 根 `CMakeLists.txt`：CLOSURE-MAPPING 门块（target_sources/链接/定义
   PWB_WITH_CLOSURE_MAPPING，门= AppShell 组合全部 target）。
8. `tests/cpp/platform/test_closure_mapping.cpp` + 注册：bank 深测（编辑/撤销/
   保存/放弃/守卫拒绝/重绑一致性）+ MainWindow 级安装验证（占位被真件替换、
   save_documents 诚实失败）。

## 待办 / 下一步

- 构建轮 1 进行中（gate Build -j2）→ 修编译错误至绿。
- ctest：ui_seqviz.composition_panel、ui_pages_data.preparation_page、
  ui_pages_mapedit.*、mapping_document.*、platform.closure_mapping、
  platform.app_shell（受影响集）；关键测试跑两遍。
- 独立审查子代理（第 3 个、最后一个直接子代理预算）。
- 提交/推送/PR（draft 或 ready 视 #1412 依赖说明）。

## 已知限制（诚实登记，另见 acceptance.md）

- 网格批量计算内核未移植（ui_workers batch_fn 缝无原生绑定）→ 制备运行显式
  失败文案，不伪造产物；等值线内核已真绑定，但输入网格依赖制备完成态。
- composition 预览 SVG 字符串渲染器与导出执行器（CompositionLayoutService）
  未接线 → 面板诚实失败；模板库未移植 → 面板以空白 A4 文档起步。
- 12 的全局 save 路由：install 暴露 `save_documents(window, error)`，
  等 12 接线（UI-17 登记 save_project_requested 为 deferred 宿主动作）。
