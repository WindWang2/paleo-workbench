# CONV-RUNTIME Findings — Python 面 → C++ 落点逐模块对账

任务：`PWB_BUILD_PREDICTION_RUNTIME=ON` 的 native prediction runtime closure。
“真运行时”= 真实 ONNX Runtime CPU 执行；“stub”= 是否仍依赖测试替身/桩；“wired”= 是否接入 `run_prediction_pipeline` → `PredictionTaskRuntime` 生产路径。
基线 `ff67dcf3`，实现提交 `385add5c` + `c98f66c7`，工作树另含 runtime hardening/oracle/test/docs 收尾提交（合并前随分支统一提交；计数见 pr.md）。

## tiled_onnx.py

- Python 面：`run_tiled_inference` 推理循环/几何、`_make_session`、`TiledOnnxProvider` 注册。
- C++ 落点：CONV-13 `src/tiled_inference.cpp`（`tile_starts`/`authoritative_range`、softmax/argmax、#1187 预算、tile markers、OOM 对半）+ `src/onnx_session.cpp`。
- 真运行时：是（真实 ORT session）；stub：否（`prediction.tiled_stub` 的 CPU 桩只作测试替身）；wired：是。
- 缺失/仍留 Python：zarr classmap/probmap store → headerless raw + descriptor；`TiledOnnxProvider` 注册仍 Python；GPU 路径本地未演练；runtime governor allowance 未接（线程数默认 0）。

## model_package.py

- Python 面：`ModelPackageManifest`/`load_manifest_dict`/`parse_*`/`validate_*`（纯半）、`register_model_package`、运行时装载。
- C++ 落点：CONV-21 `src/model_package.cpp`（纯半）+ `src/model_package_runtime.cpp`（包根 containment、checksum 校验/回填、metadata 解析、与真实 ONNX 端口兼容检查）。
- 真运行时：纯函数 + 真实文件/模型检查；stub：否；wired：是（经 runtime 装载）。
- 缺失/仍留 Python：`register_model_package`（catalog 注册/promote/冲突链）→ catalog 方向。

## input_contract.py

- Python 面：`parse_input_schema`（纯半）、`resolve_model_inputs`、`_enforce_required_curves`、`_asset_type_for_version`。
- C++ 落点：CONV-21 `src/input_contract.cpp`（schema 归一化）+ `src/prediction_input.cpp`（网格/dtype/CRS/geotransform/nodata/quality mask/band mapping 前置校验）。
- 真运行时：是；stub：否；wired：是（`validate_prediction_input` + `run_prediction_pipeline` 内复校）。
- 缺失/仍留 Python：`resolve_model_inputs`、required curves/well-curve 名解析、`_asset_type_for_version`（geoviz/catalog 编排）。

## postprocess.py

- Python 面：`postprocess_prediction_regions`、`resolve_formation_boundaries` 及内部纯函数。
- C++ 落点：CONV-21 `src/postprocess.cpp`（区段合并/顶界切分/display probability/well tops）。
- 真运行时：纯函数；stub：否；wired：否（raster 路径只出 summary + CLASSIFIED_RASTER）。
- 缺失/仍留 Python：向量/井路径的 region 后处理接线属向量输出与编图，未在本片；行为由 `prediction.contracts` 覆盖。

## spatial_result.py

- Python 面：`spatial_type_of`/`extract_polygon_features`/`validate_spatial_result`/`bounded_result_summary`/`is_map_compilable`。
- C++ 落点：CONV-21 `src/spatial_result.cpp`；信封由 `build_prediction_spatial_result` 生成。
- 真运行时：纯函数；stub：否；wired：是（副作用前 `validate_spatial_result`）。
- 缺失/仍留 Python：无。

## providers.py

- Python 面：provider 注册表、`DemoModelProvider`/`LocalAssetProvider`、`ensure_default_models`。
- C++ 落点：无独立落点；native 以 manifest 驱动装载，`PROVIDER_DEMO/LOCAL_ASSET` 常量已在 CONV-21。
- 真运行时：否；stub：否；wired：否。
- 缺失/仍留 Python：注册/解注册与默认模型装配（catalog 耦合 + 演示语义）；native 默认拒绝非 scientific 包（`allow_non_scientific=false`）。

## inference_service.py

- Python 面：`start_inference`/`execute_run`/取消/进度、`_persist_result`、`link_run_to_domain_task`、`materialize_prediction_task`。
- C++ 落点：`src/prediction_service.cpp`（`PredictionTaskRuntime` validate/execute/cancel/progress/snapshot + `PredictionWorkflowNode`）。
- 真运行时：是；stub：否；wired：是（workflow node JSON in/out）。
- 缺失/仍留 Python：catalog 持久化（`_persist_result`、`_validated_volume_stores`、`_run_workspace_roots`）与 domain task 链接 → catalog/workspace。

## adapters.py

- Python 面：`MockPredictionAdapter`、`LocalAssetPredictionAdapter`、`run_heuristic_facies`。
- C++ 落点：无。
- 真运行时：否；stub：否；wired：否。
- 缺失/仍留 Python：演示/启发式 adapter，非生产路径；与 catalog 绑定，整体留 Python。

## viz helpers（geoviz_online.py / mock_facies.py / geoviz_seismic 读器）

- Python 面：在线 GeoViz provider、mock facies provider、zarr volume store。
- C++ 落点：`src/integration_seams.cpp`（`MapLayerDescriptor`/`PredictionOutputVersion`，无 QGIS 类型）；读器为 `RawVolumeReader`/`ArrayVolumeReader`。
- 真运行时：描述符；stub：否；wired：是（workflow node 输出 `output_version`/`map_layers`）。
- 缺失/仍留 Python：在线/mock provider 留 Python；zarr 读器未移植（native 读 raw/in-memory）。

## 注记

- 生产路径无 Python：native 侧不 import、不嵌解释器；oracle 生成器是唯一 Python 参与点（冻结 goldens）。
- zarr 互操作：Python provider 仍写 zarr，native 写 raw + descriptor；仓内除 Python provider 外暂无消费 prediction zarr 的组件，跨用需后续转换器（known limit）。
- 错误类：native 保持 Python 类名（decisions D9），error cases 按类名 + 消息片段断言。
