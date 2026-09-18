# CONV-RUNTIME Decisions — native prediction runtime closure

编号 D1–D13；每条：选项、决定、理由/边界。

- **D1 无 Python 运行时依赖 / ORT 动态加载**
  决定：ONNX Runtime 作为**可选运行时依赖**，进程启动时动态加载（Windows `LoadLibraryW` / POSIX `dlopen`），编译期仅需 vendored C API 头。发现顺序（first-wins，进程内只加载一次）：显式 `OnnxSessionOptions::library_path` → `PALEO_ONNXRUNTIME_LIBRARY` → CMake 烘焙 `PWB_ONNXRUNTIME_LIBRARY` → 平台默认库名。
  理由：缺 ORT 是正常状态而非 configure error；失败必须显式（`TiledInferenceError` 带全部候选路径），绝不静默降级到桩。

- **D2 vendored 头 + ABI 策略**
  决定：`libs/prediction/third_party/onnxruntime/onnxruntime_c_api.h` 逐字复制上游 v1.17.0（`ORT_API_VERSION 17`，MIT；`libs/prediction/third_party/onnxruntime/README.md` 记 tag + sha256），不 `find_package(onnxruntime)`。
  理由：ORT 承诺 `OrtApi` 字段序 ABI 稳定（新函数仅追加），`GetApi(17)` 对任意 `>= 1.17` 可用；本地已对照 `onnxruntime.dll` 1.29.0 验证。升级 = 复制新 tag 头 + 更新 README tag/sha256；禁止手改头文件。

- **D3 复用 CONV-13/21，不复制内核**
  决定：tile 几何、center-crop fusion、softmax/argmax、预算、resume markers、OOM 对半全部复用 CONV-13 `tiled_inference.cpp`；纯契约复用 CONV-21 `postprocess`/`spatial_result`/`input_contract`/`model_package`。
  理由：单一 fusion 内核，行为已在 CONV-13/21 冻结；本片只补运行时（读器、session、预处理、输出、服务）。

- **D4 CPU-first，GPU 诚实报告**
  决定：`prefer_gpu` 为 best-effort；仅当 CUDA provider 真正建出 session 时 `device_mode="cuda"`，否则 `"cpu"` 且 provenance 记 `gpu_requested=true`。
  理由：与 Python `_make_session` 的 provider 列表 + CPU 重试语义一致；不给假 GPU。CUDA 路径本地未演练（known limit）。

- **D5 原始输出格式 + descriptor**
  决定：输出为 headerless little-endian raw（classmap uint8 / probmap float16 bits / valid_mask uint8）+ 原子写 descriptor JSON（shape/classes/paths/dtype/byte_order/layout/CRS/geotransform/sha256/bytes）。
  理由：Python 用 zarr；仓内除 Python provider 外无消费者，raw + descriptor 让 C++ 侧零依赖，QGIS/GDAL 消费方可据 shape/geotransform/dtype 建 VRT。默认 2 GiB 输出预算（`kDefaultOutputBudgetBytes`），并与 `max_voxels` 取交。

- **D6 resume = fingerprint + mask 持久化**
  决定：fingerprint 覆盖 model/source/quality-mask sha256、shape、classes、tile/overlap、normalization、nodata（batch 故意排除）；仅当 fingerprint 精确匹配**且**持久化概率图存在时 seed（含 valid mask，保证 nodata 计数只发生一次）；不匹配则清 markers 重算。
  理由：宁可全量重算，也不把旧预测置于新 provenance 之下；取消运行写 partial 描述符 + fingerprint，第二次 `execute()` 续跑。

- **D7 包根路径 containment**
  决定：`load_model_package` 默认 `enforce_within_root`，经 `pwb::interchange::ensure_within_root` 拒绝 artifact 越出 manifest 目录（`ModelPackageError`）。
  理由：Python 装载器只 resolve 不 contain；native 侧封住路径逃逸向量。关闭时记 `package_root_check_disabled` warning。`385add5c` 将 containment 修为按路径分量（text-prefix 在 Windows 只认 `/`，曾拒绝一切嵌套路径）。

- **D8 空间信封先校验、后副作用**
  决定：成功路径先 `build_prediction_spatial_result` 再 `validate_spatial_result`，通过后才写 artifacts 与 fingerprint。
  理由：缺 CRS 等 CLASSIFIED_RASTER 契约违规不得留下任何产物/续跑状态；失败保持上一份一致状态。

- **D9 错误层级镜像 Python**
  决定：`ValueError` 为基类；`ModelPackageError`、`UnicodeDecodeError`（manifest 非 UTF-8 原样泄漏）、`InputContractError` 均为其子类；`AttributeError`/`TypeError` 独立；`TiledInferenceError` 保持 `runtime_error`。
  理由：oracle `"raises"` 字段按类名 1:1 对账；Python `except ValueError` 语义在 C++ 可平移。

- **D10 整数范围检查**
  决定：JSON → int 全部显式 32 位窄化检查（`classes`/`batch`/`tile`/`shape`/`max_voxels`/`output_budget_bytes`）；unsigned 分支先于 signed，避免 `get<long long>()` 回绕；metadata `int(value)` 同义。
  理由：回绕会静默改语义（如 `2^32 → 0 → "unset"`），必须 fail-closed 报 out of range。

- **D11 oracle 用生产 Python 函数**
  决定：生成器直接调用 `paleo_workbench.prediction.tiled_onnx.run_tiled_inference` + 真 onnxruntime CPU session（numpy 2.5.2 / ORT 1.29.0 / onnx 1.22.0）冻结 goldens；C++ 重放用独立 binary16 解码器（刻意不用库内 helper）与 1 fp16 ulp 容差。
  理由：oracle 必须是被替换实现本身，不是重写；独立解码防止被测代码掩盖 bug。

- **D12 不等待线上 CI**
  决定：验收证据全部本地（configure/build/ctest/oracle）；不改 workflow 文件，不以远端 check 为完成条件。共享资源门禁不可用时直接调用 `cmake --build --parallel 2`，同一时间仅一个重型构建（见 pr.md 资源控制）。

- **D13 map layer 描述符无 nodata 哨兵**
  决定：移除曾发明的 `style_hints["nodata_value"] = 255`（class map 为纯 argmax、无 255 哨兵；validity mask 是独立 artifact）。
