# UI-10 `qt-seq-factor-viz` — 移植台账

权威分片(taskbook UI-10):16 个 `pages/*.py`,层序/单因素/组合可视化面。
工作树 `/home/kevin/project/worktrees/cpp-qt-seq-factor-viz`,基线 `55881f9d`。
新库 `libs/ui_seqviz/`:`Pwb::UiSeqviz`(Qt-free 页面状态核)+ Qt Widgets 壳。

## 结构

- `pwb_ui_seqviz`(STATIC):composition/correlation/curve_ops/factor/lithology/
  sequence/viz_page/state_language/page_tokens/geoviz_provider 状态核
- Qt 壳位于 `src/qt/`,含 sequence_boundary_table、sequence_framework_page、
  sequence_scheme_summary、sequence_target_panel、stratigraphy_correlation_page、
  factor_preview_grid、factor_task_panel、create_factor_map_dialog、
  composite_visualization_panel、composition_panel、visualization_page、
  visualization_summary_panel 等 widget
- 测试:`ui_seqviz.core_state` + `ui_seqviz.qt_widgets_smoke`(offscreen),
  fixtures 目录已备

## 跨库扩展(登记)

- `libs/ui_data_core/preview_provider.{hpp,cpp}`:新增 `SummaryFn`/
  `VisualizationFn` 可选 hook(`set_summary_hook`/`set_visualization_hook`)。
  原因:Python `LocalVisualizationProvider` 子类化 `PreviewProvider` 覆写
  `preview_summary`/`preview_visualization`;C++ 侧用注入 hook 复刻覆写语义,
  默认路径不变(向后兼容)。**属于 UI-03 库的外科扩展**,integration 阶段可
  评估是否收敛为虚函数。

## 构建/验证

- feature-gate:`PWB_BUILD_PLATFORM AND PWB_BUILD_DATA` 暗含
  CONV_02/27C/29/11 内核闭包(根 CMakeLists `UI-10-IMPLY` 块);
  挂载门为 `if(TARGET Pwb::UiWorkers AND Pwb::UiDataCore AND
  Pwb::MappingDocument AND Pwb::WellScience AND Pwb::JobRuntime AND Pwb::Domain)`。
- `linux-ninja` 全量构建通过;`ctest -R ui_seqviz` 2/2 通过
  (core_state + qt_widgets_smoke,offscreen)。

## 修复轮(协调流程补全,agent 于编译修复前终止)

- `viz_page_state.cpp`:两处 `to_slice(resource)` → `resource_slice(resource)`
  (单资源适配器实际名;to_slices 为 vector 版)。

## 接缝/延期

- geoviz 引擎经 `geoviz_provider` seam 注入;页面保持状态/判词/文案。
- 服务侧(factor/sequence/composition 任务执行)经 `libs/ui_workers` +
  domain seam 复用,不重复移植。
