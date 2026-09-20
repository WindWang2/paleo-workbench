# 03 — Findings（基线 06211541 实测）

## 已实现/合并/接线/验证 四列能力清单（本线相关）

| 能力 | implemented | merged | wired | verified |
|---|---|---|---|---|
| science 服务面（10 算法、envelope、publisher、payload seam） | ✅ CONV-28 | ✅（在 main） | ❌ 无 catalog 消费方 | ✅ oracle 44/44（CONV-28 自测） |
| prediction 运行时（ORT session/model package/tiled/task runtime/workflow node） | ✅ CONV-13/14/19/21 + runtime | ✅ | ⚠️ 仅 ui_controllers 链接，无生产调用 | ✅ prediction.runtime（需 ORT 库） |
| catalog 事务（publish_result_transaction/finish_run/upsert_model*） | ✅ CONV-26/31b | ✅ | ⚠️ 平台 bootstrap 用了一部分；推断链无人用 | ✅ catalog 测试 |
| model registry（register/find_production/promote 门） | ✅ | ✅ | ❌ 无生产调用方（UI hooks 全空） | ✅ |
| 预测页 Qt 壳（guard 链、session token、任务面板） | ✅ UI-09 | ✅ | ❌ hooks 全空 | ✅ 页面自测 |
| Python inference_service 语义（start/execute/cancel/materialize/恢复） | ✅（Python 冻结源） | — | ❌ C++ 未迁移 | Python 侧 |
| 任务恢复 / 工程身份隔离 | ❌ C++ 无 | — | ❌ | — |

## Python 冻结语义（迁移合同，附文件:行）

- `paleo_workbench/prediction/inference_service.py`：
  - `start_inference`（246）：run.parameters 记录 model 身份 + `_input_snapshot_hash`
    （排序去重输入、含 preprocessing_version/checksum/seed；SHA-256 canonical JSON），
    `model_ref`，status=running，generator=inference-service-v1。
  - `execute_run`（332）：非 running run → CatalogError（晚到/重复执行不得触碰终态 run）；
    provider 按 `model.provider` 分发；TaskCancelled → run=cancelled（非 failed，无输出版本）；
    provider 结果 `cancelled:true` → 同上；空间结果校验（spatial_output_type）；
    `PAYLOAD_RESERVED_KEYS` 服务侧独占（provider 不得改写 model/run/seed/snapshot 身份）；
    结果临时文件 → register_result_asset(type=prediction_result, DERIVED, run 关联) →
    run complete + output_version_id；失败→failed+error（不伪造输出）。
  - `materialize_prediction_task`（674）：PredictionTask 承载 result_summary（bounded）、
    model_metadata（workflow/run_id/prediction_version_id/demo_only…）、
    probability_summary、evidence_contribution、review_areas、seed。
  - `resolve_inputs_for_model`（167）→ input_contract.resolve_model_inputs（schema 驱动，
    required_asset_types/required_curves；strict=True 缺→报错）。
  - `_persist_result`（584）：volume store 必须 containment 在工程 artifacts 树内（B1）。
- `paleo_workbench/prediction/providers.py`：
  - `MODEL_ID_DEMO="demo-facies-v1"`、`MODEL_ID_HEURISTIC="facies-heuristic-v1"`、
    `CAPABILITY_FACIES="facies_prediction"`；provider 名：demo / local_asset / geoviz_online /
    tiled_onnx（PROVIDER_TILED_ONNX，`tiled-onnx-seismic@tiled-onnx-v1`）。
  - `ensure_default_models`（642）：demo+heuristic 均 status=demo（find_production_model 永
    不返回），幂等不重写已有行；生产化只能显式 promote。
  - Demo 输出必须带 `demo=true / is_mock=true / final_scientific_prediction=false`。
- `paleo_workbench/prediction/tiled_onnx.py`：TiledOnnxProvider 需 parameters 含
  model_path+classes；模型身份校验（checksum）；取消→TaskCancelled；work_root 缺省为
  `<volume>.inference` 旁目录。

## C++ 可复用核（不重写）

- `pwb::science_service`：`register_science_services`/`IPayloadSource`/`DirectoryEnvelopePublisher`/
  envelope fingerprint（stable_sha256）。
- `pwb::prediction`：`PredictionTaskRuntime`（per-tile 磁盘 resume 标记、取消线性化）、
  `build_prediction_output_version`/`prediction_map_layers`、`validate_prediction_input`
  （CRS/geotransform/dtype/nodata）、`validate_spatial_result`/`bounded_result_summary`。
- `pwb::catalog`：`CatalogRepository`（publish_result_transaction / finish_run_transaction /
  commit_version_transaction / upsert_model*）、`model_registry.hpp`（register_model(_version)/
  find_production_model/promote_model，字节级 Python 文本）。
- `pwb::workflow::TaskRuntime`（publish-before-terminal）。

## 本机环境

- cmake/ctest 不在 PATH：`export PATH=/home/kevin/pwb-sdks/root/usr/bin:$PATH`；
  `LD_LIBRARY_PATH=/home/kevin/pwb-sdks/root/usr/lib`。
- **无系统 ONNX Runtime**：已下载官方 v1.17.1（与 vendored C API 头 1.17.0 兼容）至
  `/home/kevin/pwb-sdks/ort/onnxruntime-linux-x64-1.17.1/lib/libonnxruntime.so`；
  测试经 ctest ENVIRONMENT `PALEO_ONNXRUNTIME_LIBRARY` 注入（同 prediction.runtime）。
- 机器：40 核 / 62GiB（可用 ~39GiB）；门禁默认 j2。
- Qt6/QGIS SDK vendored（PLATFORM 门需要）；本线核测试 Qt-free + offscreen Qt smoke。

## 关键设计决定

1. 不动 `libs/science_service`/`libs/prediction`/`libs/ui_wellseis` 源码：全部新增在
   `libs/closure_science`（消费方适配层），避免与 13/14 线冲突。
2. app 注入 = `main_window.cpp wire_app_shell()` 内 `BEGIN/END CLOSURE-SCIENCE` 命名块 +
   root/apps CMake 命名块（12 装配；租约登记于 03-line.json）。app_shell.cpp/AppContext 不改。
3. provider 注册表显式 fail-closed：未知 provider / 未注册模型 / 缺 ORT 库 → 明确错误文本，
   绝不静默 fallback。demo provider 为 C++ 冻结确定性实现（demo_only=true 诚实标注；不声称
   与 Python MT19937 序列位等价，C++ 测试冻结自身值）。
4. 任务恢复：`PredictionTaskJournal`（工程 artifacts 下 JSON，原子写）+ 工程身份 token
   （project 文件绝对路径 sha256）；rebind 到不同工程后，晚到完成按 token 拒绝。
   run 级防重复执行由 Python parity 的"非 running run 拒绝 execute"承担。
5. seismic 输入描述符来自 catalog version metadata（shape/dtype/crs/geotransform/unit 显式
   声明）；缺元数据 = 明确失败（不做猜测式默认）。

## 独立审查轮（reviewer C）修复记录

- P0 worker/GUI 并发：binding 级 `document_mutex_` 串行化所有 document 访问；run 期间 GUI hooks 走 try_lock + 缓存值回退（demo/production version id 首次成功后缓存）。
- P0 线程析构：shutdown() 恒 join（cancel 后 join 由 provider 的 tile-seam 取消响应性兜底）。
- P1 token 校验移至 GUI 线程（queued 回调内读宿主工程状态，worker 不再触碰 GUI 状态）。
- P1 start_run 在创建 run 前预检 is_running，杜绝滞留 running 的 run。
- P1 canonical dump 对齐 `json.dumps(sort_keys=True, ensure_ascii=False)`（键经 nlohmann dump 转义、默认分隔符）。
- P1 `resolve_resource_version_id` 增加 parsed_summary.catalog_asset_id 梯级 + weakly_canonical（symlink 感知，Python resolve(strict=False) parity）。
- P1 input_schema 语义对齐：H5-b 拒绝仅在"无任何可识别键"时；混合 schema 忽略未知键；fixture 包 manifest 显式声明 required_asset_types=["seismic"]（生产包形态）。
- P1 core_test 移除 ORT 软跳过（缺 ORT = 诚实的环境失败）；恒真断言改为具体契约断言（无 expected_crs 的包按原样传递空 CRS，无静默 EPSG 注入）。
- P1 qt_hooks：页面守卫为模态框（QMessageBox parity），测试以 auto_close_modals 处理 + set_project 提供真实工程切片；此前 ctest 300s 超时即首版测试在孤立页 modal 上阻塞（且直跑"通过"为管道退出码假象——已纠正，验证必须看输出）。
- P2 落地：persist save 失败清理孤儿结果文件；publisher getter 加锁/头注释对齐；materialize output_version_id 参数回退 + cancelled truthy 判定。
