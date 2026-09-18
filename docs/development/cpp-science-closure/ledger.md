# Goal Loop Ledger — Native Science Service Closure（CONV-28）

分支：`feat/cpp-science-well-geomodel-closure`（base: `origin/main` @ `ff67dcf3`）
Worktree：`/home/kevin/project/worktrees/cpp-science-well-geomodel-closure`

## Scope Ledger（本分支负责 / 不负责 / 边界）

### 负责

在既有 Qt-free 纯 kernel 之上构建 **native science service layer**
（`libs/science_service`），把分散的 pure kernel 组合为可被 C++ Workflow /
Application 直接调用的稳定应用接口：

- typed request/result + `std::stop_token` 取消（阶段边界检查）
- resource-aware（输入规模前置守卫，超限 fail-closed 诊断）
- provenance-friendly（复用 `pwb::science::ProvenanceRecord` 词汇）
- deterministic fingerprint（`factor_host::canonical_json` + sha256）
- 结果 envelope：type / units / CRS / extent / quality / provenance / fingerprint

服务面（全部为既有 kernel 的薄组合，不复制算法）：

| 服务 | 组合的既有 kernel |
|---|---|
| `mapping.factor_interpolate` | mapping_kernel: extract + sample_normalization + interpolator(IDW/kriging) + constrained_idw + factor_grid_io + crs_policy |
| `mapping.factor_layer_products` | mapping_kernel: layer_products（contour + facies GeoJSON） |
| `mapping.facies_surface` | mapping_kernel: representative_facies + class_grid + polygonize |
| `well.curve_operation` | well_science: curve_ops（11 op 注册表）+ depth_unit + null_policy |
| `well.log_match` | well_science: dtw（Sakoe-Chiba + minmax 降采样） |
| `factor.fuse` | factor_fusion: fuse_weighted/fuse_rule_based + sensitivity |
| `geomodel.build` | geomodel: builders（volume shell / hex mesh / triangulate） |
| `geomodel.qc_export` | geomodel: qc_contract（export gate）+ export_contract（bytes+sidecar） |
| `geomodel.section` | geomodel: section（平面切剖面） |
| `geomodel.fault_displacement` | geomodel: fault_displacement |

基础设施：

- `IPayloadSource` seam：catalog-like 输入 DTO → payload（table/well_log/grid），
  由宿主注入（in-memory / 未来 catalog adapter）
- `DirectoryEnvelopePublisher`：本地持久化/mock publisher（envelope JSON +
  payload 文件，原子写）
- `IAlgorithm` 适配器：服务进 `AlgorithmRegistry` + `TaskRuntime`
  （workflow adapter 可调用路径）
- 对 `libs/algorithms` SDK 的**最小 additive** 扩展：
  `AlgorithmResultV1` 增加尾部成员 `artifacts`（非 volume 结构化产物），
  不改变既有字段语义

### 明确不负责（其他 6 个并行方向）

- ONNX / prediction runtime → `feat/cpp-prediction-ai-runtime-closure`
- GUI / QGIS UI → `feat/cpp-qgis-ui-workbench-closure`
- Catalog persistence / workspace → `feat/cpp-data-workspace-catalog-closure`
- Workflow scheduler / runtime 服务层（freshness/recompute）→
  `feat/cpp-workflow-runtime-closure`（CONV-26）
- 本分支只交付**可被 workflow 注册 node adapter 的 service 面**，
  不改 Python 生产链接线（Python glue 替换的实际 rewire 由 Workflow/UI
  分支在 service 面稳定后进行）
- 不重写任何已冻结 kernel；不统一 mapping(含边)/geomodel(严格) 两个
  point-in-ring 语义（各自冻结）

### 复用图（禁止重复算法）

- `pwb::science`（libs/algorithms）：IAlgorithm / AlgorithmRegistry /
  Result / IResultPublisherV1 / ProvenanceRecord —— 服务层的 SDK 基座
- `pwb::workflow::TaskRuntime`（libs/workflow）：执行编排
  （publish-before-terminal / 取消线性化）
- mapping_kernel 14 头、well_science 6 头、factor_host 5 头、
  factor_fusion 4 头、geomodel 11 头 —— 全部为纯函数薄包装对象

## 验收（Oracle）

1. 端到端：catalog-like input DTO → science service（经 TaskRuntime）→
   result envelope → DirectoryEnvelopePublisher 落盘 → envelope 字段/
   fingerprint/文件齐全（`science_service.e2e`）
2. 服务级 frozen oracle（Python 真实生产叶生成 → C++ replay）通过，
   含 negative self-check（比较器能抓错）
3. 取消：已停止的 stop_token 在阶段边界产生 TaskCancelled
4. 资源守卫：超限输入 → error 诊断，不 OOM
5. 本地 configure/build/ctest 绿（资源门禁 `-j2`）
6. 三轮 review（A 正确性 / B 架构 / C 产品闭环）完成并修复
7. PR 创建（Local verification only; no online CI wait required）

## 迭代记录

| 轮 | 改动 | 验证 | 判定 | 下一步 |
|---|---|---|---|---|
| 1 | 只读盘点（2 个并行只读 agent）：C++ kernel API 清单 + Python glue 面；建 worktree/scope ledger | 复用图成立：全部数值 kernel 已就位，缺口=服务组合层 | 通过 | 服务层 API 细化 + 编码 |
