# CONV-RUNTIME — native prediction runtime closure（ONNX session / 模型包与输入运行时 / 任务服务）

## 目标与用户流程（本切片验收）

M9 prediction 的运行时闭环：把 CONV-13/14/19/21 已冻结的 tiled 几何与预测契约接上**真实 ONNX Runtime**，形成无 Python 依赖的生产任务路径：

装载模型包（manifest/containment/checksum）→ 校验输入网格（shape/dtype/nodata/CRS/geotransform/quality mask/band mapping）→ 真实 ONNX tiled 推理（动态加载 ORT，CPU 主路径）→ center-crop fusion → 确定性 summary → CLASSIFIED_RASTER 空间信封 + provenance（模型/运行库/输入摘要）→ `PredictionTaskRuntime` / `PredictionWorkflowNode` 可调用（validate/execute/cancel/progress/结果描述符）。

## 新增/修改的 C++ 模块

- `onnx_session.{hpp,cpp}`：动态加载 ORT C API、模型/tensor/type/shape 校验、float16/float64 输入转换、CUDA best-effort + CPU 回退、诚实 `device_mode`。
- `model_package_runtime.{hpp,cpp}`：manifest 装载、包根 containment、checksum 校验/回填、`metadata.prediction_runtime` 解析、与真实 ONNX 端口兼容检查。
- `prediction_input.{hpp,cpp}`：网格描述符与 band mapping 前置校验（不抛的 `validate_*` + 抛 `InputContractError` 的 `require_*`）。
- `prediction_pipeline.{hpp,cpp}`：raw float32/16/64 + in-memory 读器、nodata/quality mask/归一化预处理、CONV-13 fusion 复用、有界输出、summary、resume fingerprint/mask、空间信封与 provenance。
- `prediction_service.{hpp,cpp}`、`integration_seams.{hpp,cpp}`：任务运行时与 workflow/catalog/map 描述符缝。
- `runtime_io.{hpp,cpp}`、`tiled_inference.cpp` 收尾（UTF-8 路径）；6 个新公共头；vendored ORT C API 头 v1.17.0（tag + sha256 见 `libs/prediction/third_party/onnxruntime/README.md`）。
- 构建：根 CMake `PWB_BUILD_PREDICTION_RUNTIME`（隐含 `PWB_BUILD_DATA` + CONV-13/14/19/21），ctest `prediction.runtime`；`PWB_ONNXRUNTIME_LIBRARY` 为可选烘焙 hint。

## 被替换的 Python 模块

`tiled_onnx.py`（推理循环/session/fusion/resume）、`model_package.py` 的运行时半、`input_contract.py` 的输入校验半、`spatial_result.py`、`postprocess.py` 纯核均已在 C++ 落地（`postprocess` 暂未接 native raster 输出）；`inference_service.py` 的任务编排半由 `PredictionTaskRuntime` 取代。

## 暂留 Python 及原因

- `providers.py` 注册表、`inference_service.py` 的 catalog 持久化（`_persist_result` 等）、`adapters.py`、`geoviz_online.py`、`mock_facies.py`、Qt worker：属 catalog/workspace/QGIS 编排层，超出本分支范围；native 以 manifest + 描述符缝对接。
- Python provider/旧生产路径整体保留为 oracle，不与 native 抢占生产入口。

## 本地构建（已验证配置）

Windows MSVC 14.38.33130 + Ninja，Release：

```bash
cmake -S . -B build/prediction -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DPWB_BUILD_PLATFORM=OFF -DPWB_BUILD_DATA=ON \
  -DPWB_BUILD_PREDICTION_RUNTIME=ON -DBUILD_TESTING=ON \
  "-DPWB_ONNXRUNTIME_LIBRARY=C:/Users/wangj.KEVIN/projects/paleo-workbench/.venv/Lib/site-packages/onnxruntime/capi/onnxruntime.dll"
cmake --build build/prediction --parallel 2
ctest --test-dir build/prediction -R "prediction\." --output-on-failure
```

注：上述 `.venv` 属于主 checkout（`C:/Users/wangj.KEVIN/projects/paleo-workbench`），不在本 worktree 内。

## 本地测试结果（last run，未等待线上 CI）

- `prediction.tiled_stub`：275 checks，0 failures（CONV-13 回归，最终源码重跑）。
- `prediction.contracts`：78 checks，0 failures（CONV-21 回归，最终源码重跑）。
- `prediction.runtime`：737 checks，0 failures（最终本地运行，含全部 fixture/测试增补）。

## Oracle 覆盖

`tools/oracle/generate_prediction_runtime_fixtures.py` 用真 onnxruntime（1.29.0）跑**生产** Python `run_tiled_inference`，冻结 tiny ONNX 模型 + 10×12×9 合成体（tile 6×8×5，overlap 2，3 类）的 goldens；当前 fixture 为 10 个成功 run + 17 个 error case（共 27，`meta.cases=27`）。成功例重放 classmap 字节、fp16 概率位（1 fp16 ulp，独立解码器）、summary、spatial 校验与 provenance；错误例断言 C++ 错误类 + 消息片段；C++-only 覆盖 cancel/resume（含 nodata mask seed）、确定性重跑、resume fingerprint 拒绝、dtype 输入转换（f16/f64 输入模型）、workflow sink/node 与 output version/map layers。

## 资源控制

共享资源门禁 `scripts/cpp-migration/Invoke-ResourceGate.ps1` 本地不可用（空闲内存低于其 8 GiB 下限，退出码 75），构建直接调用 `cmake --build --parallel 2`，同一时间仅一个重型构建；未并行链接多个大目标。

## 已知限制（如实记档）

- GPU 为 best-effort + CPU 回退；CUDA 路径本地未演练。
- 输出为 headerless raw + descriptor，与 Python zarr store 不同构；仓内除 Python provider 外暂无 prediction zarr 消费者，跨用需转换器。
- 默认 2 GiB 输出预算；超出需显式提高 `output_budget_bytes`。
- Resume 需要 fingerprint 精确匹配且概率图已持久化（`keep_probmap`）。
- 输出路径遵循仓内 native-string 约定：UTF-8 经 `path_from_utf8` 打开，但 `generic_string` 往返在 Windows 仍可能回落到 ACP。
- Python provider/旧路径保持不动，仍是 oracle。

## 依赖其他并行方向

Workflow（消费 `PredictionWorkflowNode`/`IPredictionTaskSink`）；Catalog/Workspace（持久化 `PredictionOutputVersion`）；QGIS/地图（消费 `MapLayerDescriptor` 构建 VRT）；打包方向（预设/门禁/安装，本分支不碰）。

Local verification only; no online CI wait required for this task.
