# Prediction 运行时闭环 — Scope Ledger

分支：`feat/cpp-prediction-ai-runtime-closure`（独立 worktree：`<worktree>`）
基线：本地 main `ff67dcf3`（`origin/main` 已 fetch 到同一提交，无落后/领先）；提交：`385add5c`（MSVC/路径可移植修复）、`c98f66c7`（运行时闭环）
任务族：M9 prediction 的**运行时闭环**——把 CONV-13/14/19/21 已冻结的 tiled 几何与预测契约接上真实 ONNX Runtime、模型包/输入运行时、任务服务与集成缝。

## 1. 本分支负责

| # | 面 | 交付 |
|---|---|---|
| A | ONNX Runtime session | `onnx_session.{hpp,cpp}`：动态加载（无链接依赖）、四段发现顺序、tensor/type/shape 校验、dtype 输入转换、诚实 GPU 报告 |
| B | 模型包运行时 | `model_package_runtime.{hpp,cpp}`：manifest 装载、包根 containment、checksum 校验/回填、prediction metadata、与真实 ONNX 端口的兼容性检查 |
| C | 输入契约运行时 | `prediction_input.{hpp,cpp}`：网格描述符、band mapping、nodata/quality mask/dtype/CRS/geotransform 前置校验 |
| D | tiled 流水线 | `prediction_pipeline.{hpp,cpp}`：raw 读器栈、nodata/归一化预处理、CONV-13 fusion 复用、有界输出、确定性 summary、resume、CLASSIFIED_RASTER 信封与 provenance |
| E | 任务服务与集成缝 | `prediction_service.{hpp,cpp}`、`integration_seams.{hpp,cpp}`：validate/execute/cancel/progress/snapshot、workflow node、output version、map layer 描述符、任务 sink |
| F | 头文件与构建 | 6 个公共头（`onnx_session`、`model_package_runtime`、`prediction_input`、`prediction_pipeline`、`prediction_service`、`integration_seams`，位于 `include/pwb/prediction/`）；运行时源码 7 个，其中 `src/runtime_io.{hpp,cpp}` 为 `libs/prediction/src/` 下的私有 helper（不安装、非公共头）；vendored ORT C API 头 v1.17.0；CMake `PWB_BUILD_PREDICTION_RUNTIME`；ctest `prediction.runtime` |
| G | oracle 与测试 | `tools/oracle/generate_prediction_runtime_fixtures.py` + fixtures；`runtime_test.cpp` 重放真实 Python 生产 `run_tiled_inference` 的 goldens |

验收流程：装载模型包 → 校验输入 → 真实 ONNX tiled 推理 → center-crop fusion → summary → CLASSIFIED_RASTER 空间信封 + provenance → `PredictionTaskRuntime` / `PredictionWorkflowNode` 可调用；生产路径无 Python。

## 2. 本分支明确不负责

Workflow 调度器与依赖图（CONV-22..25 / `libs/workflow_graph`）；Catalog 持久化与注册链；QGIS UI/图层树/地图发布；well/geomodel 科学；打包与构建工具链；Python provider/旧生产路径（保留为 oracle）。

## 3. 与其他并行方向的边界

| 方向 | 边界 |
|---|---|
| Workflow | 本分支只提供 `PredictionWorkflowNode`（JSON in/out）+ `IPredictionTaskSink`；引擎的 CancelToken/progress 经 `std::function` 桥接，本库不依赖引擎 |
| Catalog/Workspace | `PredictionOutputVersion`/`MapLayerDescriptor` 仅为描述符；落库/版本事务由 catalog 方向实现 |
| QGIS/平台 | map layer 描述符不含 QGIS 类型；消费者用 shape/geotransform/dtype/byte_order 自行构建 VRT |
| 打包（`cpp-build-packaging-hardening`） | 预设、资源门禁、安装/打包均为对方所有；本分支只新增一个 CMake option |
| 科学/建模 | 不引入 well/geomodel 实体；`postprocess` 纯核已由 CONV-21 移植，本分支不接线向量路径 |

## 4. 写入范围（文件）

`libs/prediction/include/pwb/prediction/{onnx_session,model_package_runtime,prediction_input,prediction_pipeline,prediction_service,integration_seams}.hpp`、`errors.hpp` 扩展；`libs/prediction/src/{onnx_session,model_package_runtime,prediction_input,prediction_pipeline,prediction_service,integration_seams,runtime_io}.cpp` + `src/runtime_io.hpp`、`src/tiled_inference.cpp` 收尾（UTF-8 路径）；`libs/prediction/third_party/onnxruntime/*`；`libs/prediction/prediction_tests/{runtime_test.cpp,fixtures/prediction_runtime*,CMakeLists.txt}`；`tools/oracle/generate_prediction_runtime_fixtures.py`；根/库/测试三处 CMake 的 `BEGIN/END PREDICTION-RUNTIME` 块；`docs/development/cpp-prediction-runtime/*`。

## 5. 共享文件最小补丁

- 根 `CMakeLists.txt`：仅新增 `PREDICTION-RUNTIME` option 块（DATA/CONV-13/14/19/21 隐含开关，前置声明保证生效）。
- `libs/prediction/CMakeLists.txt`：新增运行时源列表块 + ORT include + 可选 `PWB_ONNXRUNTIME_LIBRARY` 编译定义。
- `libs/prediction/prediction_tests/CMakeLists.txt`：新增 `prediction.runtime` 测试块。
- 可移植性（`385add5c`，构建所需的最小跨模块修复）：`libs/ingest/src/xml_scanner.cpp`（显式 `BuildNode` 特殊成员，绕过 MSVC 19.38 trait 缺陷）、`libs/ingest/src/project_path.cpp`（`generic_string()` 比较）、`libs/interchange/src/path_safety.cpp`（按路径分量 containment，Windows 分隔符）、prediction 测试分隔符归一化（`contracts_test.cpp`/`tiled_stub_test.cpp`）。
