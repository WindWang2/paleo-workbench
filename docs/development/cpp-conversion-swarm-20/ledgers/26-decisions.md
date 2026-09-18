# 26 — decisions：well-log native host / UI / engine integration

## D1 范围

Python/PySide6 测井 host 面向 C++20/Qt6 的迁移首闭环：`welllog_engine_adapter.py`（821 行,核心语义全量）+ `well_log_track_layout.py`（172 行,全量）+ `well_log_canvas_panel.py` 的交互语义（深度游标联动/选区/导出）+ `well_log_load.py` 的取消与单位信封。多井剖面（`welllog_multi_well_adapter.py`,558 行）与 LAS LRU 缓存细节不在本切片（已在 engine 侧有 retained document/多井布局，可后续接 `SetWellLayoutCommand`）。

## D2 落点：扩充既有 `Pwb::VisualizationWellLog`,不另起架构

- 新增 Qt-free 平面层：`well_log_track_layout.hpp`（layout 模型 + 模板 JSON）、`well_log_document_plan.hpp`（DTO→EngineLoadPlan + parity snapshot）、`well_log_events.hpp`（游标/解释事件契约）。均不依赖 Qt/welllog,可独立测试。
- `WellLogHostWidget` 在原 moc-free 设计上扩展：`load_document`/`load_from_source`（工作区 DTO、懒加载、协作取消）、`apply_track_layout`（presentation 级重排,文档/视口/选区不动）、深度游标（SetCrosshair 双向）、解释事件（选区→document intervals/markers 命中）、`export_png/svg/pdf`（framebuffer + 引擎 SvgExporter/PdfSceneExporter）。
- Platform 接线：`well_log_track_panel`（Q_OBJECT,dock 化）+ main_window 解释事件→状态栏。被否备选：往 widget 上加自定义 signal（会破坏 moc-free 约束）——统一 std::function 回调,与既有 SelectionEventV1 模式一致。

## D3 复用内核,禁止复制

- 深度单位词表直接链 `Pwb::WellScience`（CONV-11 的 `classify_depth_unit`,V6 §2-3 oracle-frozen）——science_suite viewer 块按需 `add_subdirectory(libs/well_science)` 补挂（fail-closed 前提下目标缺失则自建）。
- JSON 用 `Pwb::Domain` 的 nlohmann 惯例（`ordered_json`,键序确定）。domain 同样按需补挂。
- UUIDv5 所需 SHA-1 为本地实现（仓库只有 SHA-256）,RFC 3174 向量 + Python hashlib 对账覆盖。

## D4 与 Python oracle 的对账契约

- fixture 由**真实 production adapter**生成（`tests/cpp/science/fixtures/welllog/generate_oracle.py`,numpy-only venv 可跑；`paleo_workbench` 包 `__init__` 会拉 PySide6,故用 importlib 文件级加载 + 最小 import 跳板,`well_science.py` 本体为纯 stdlib,无任何被测对象被 stub）。
- C++ 侧 `parity_snapshot_json` 与 Python `parity_snapshot` 字段/键序/取值一一对应；submit 面（tracks/top/bottom/诊断序）同帧对账。
- 精度规则：interval/marker id 内嵌 `repr(float)`——实现 `python_repr_double`（to_chars 最短 + 补 `.0`；NaN/Inf 在 id 生成前已被 invalid 诊断拦截,不进入该路径）。
- 12 案例含 negative self-check（异命名空间 id 必须不等）,证明比较器可失败。

## D5 语义保持要点（易错清单）

- gap-honest：NaN 值留轴上（engine LOD 断段）,非有限深度丢弃;null_indices 仅诊断。
- 未知深度单位：渲染标签 "m" + `declared=false` + 诊断,永不静默。
- RT/RXO 对数轴：1e-10 下限;无正有限样本回退线性 + `log_scale_fallback` 诊断（engine 拒绝 log+min<=0）。
- 布局 reconcile：曲线键 = `curve:{index}:{mnemonic}`（index-based,重名安全,与井名无关）→ schema 一致保留,不一致重置默认（前 6 可见,GR 保证）。
- 轨道序：interval 轨（lithology/facies,24mm）在前,曲线轨 40mm 在后；marker（tops）层挂每条曲线轨。
- 降序深度轴：显式声明 `AxisDirection::decreasing`（engine 校验方向与坐标一致,默认 increasing 会被 SetDocumentCommand 拒绝——测试抓出）。

## D6 资源/流程

- 全程 -j3（单 worktree 单 build）,science-only 配置先验证（`PWB_BUILD_SCIENCE=ON + PWB_SCIENCE_BUILD_VIEWER/TESTS`）,不反复全量编译。
- 线上 CI 不需要：验收 = 本地 configure + targeted build + ctest（3 个 viewer 测试含 offscreen GL）。
