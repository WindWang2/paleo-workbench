# Goal Loop Ledger — Native Science Service Closure（CONV-28）

分支：`feat/cpp-science-well-geomodel-closure`（base: `origin/main` @ `ff67dcf3`）
Worktree：`/home/kevin/project/worktrees/cpp-science-well-geomodel-closure`
切片编号 **CONV-28**（CONV-27 已被并行 QGIS UI closure 分支占用 ——
其根 CMakeLists 已声明 `PWB_BUILD_CONV_27`，本分支据此改用 28）。

## Scope Ledger（本分支负责 / 不负责 / 边界）

### 负责

在既有 Qt-free 纯 kernel 之上构建 **native science service layer**
（`libs/science_service`），把分散的 pure kernel 组合为可被 C++ Workflow /
Application 直接调用的稳定应用接口：

- typed request/result + `std::stop_token` 取消（阶段边界检查）
- resource-aware（输入规模前置守卫，超限 fail-closed 诊断，envelope 尺寸独立上限）
- provenance-friendly（复用 `pwb::science::ProvenanceRecord` 词汇 + service 级 provenance）
- deterministic fingerprint（`factor_host::stable_sha256`，仅覆盖 payload，
  与时间戳隔离）
- 结果 envelope：type / units / CRS / extent / quality / provenance / fingerprint

服务面（10 个注册算法，全部为既有 kernel 的薄组合，不复制算法）：

| 服务 | 组合的既有 kernel |
|---|---|
| `mapping.factor_interpolate` | extract + sample_normalization + interpolator(IDW/kriging) 或 constrained_idw（值域/半径/分辨率按 Python host 语义从样本推导）+ factor_grid_io + crs_policy/crs_contract |
| `mapping.factor_layer_products` | layer_products（contour + facies GeoJSON），共享 legacy 解码器 |
| `mapping.facies_surface` | representative_facies + class_grid + polygonize + extent/clip helpers |
| `well.curve_operation` | curve_ops（冻结 11 op 表中 9 个派发；depth_unit_normalize/derive_curve 显式拒绝）|
| `well.log_match` | dtw（Sakoe-Chiba + minmax 降采样，超 kMaxCostCells 先降采样）|
| `factor.fuse` | factor_fusion（weighted/rule_based + sensitivity 数据面）|
| `geomodel.build` | builders（volume shell / hex mesh）+ volume + mesh_qc |
| `geomodel.section` | section（平面切剖面）|
| `geomodel.fault_displacement` | fault_displacement（点锚定 throw）|
| `geomodel.export` | qc_contract（export gate）+ export_contract（bytes+sidecar，QC blocker 拒绝）|

基础设施：

- `IPayloadSource` seam：catalog-like 输入 DTO → payload（table/well_log/grid），
  宿主注入（in-memory / fail-closed unavailable）；线程契约：submit 前
  populate 或外部同步
- `DirectoryEnvelopePublisher`：本地持久化/mock publisher（请求 id 与
  记录名双重路径段消毒，temp+rename 原子写，rename 失败清理）
- `IAlgorithm` 适配器 ×10：进 `AlgorithmRegistry` + `pwb::workflow::TaskRuntime`
  （`node_request` = workflow 分支注册 node adapter 的唯一入口）
- 对 `libs/algorithms` SDK 的**最小 additive** 扩展：
  `ProducedRecord` + `AlgorithmResultV1` 尾部成员 **`records`**
  （非 volume 结构化产物；既有消费者只读 outputs，无聚合初始化破坏）

### 明确不负责（其他并行方向）

- ONNX / prediction runtime → `feat/cpp-prediction-ai-runtime-closure`
- GUI / QGIS UI → `feat/cpp-qgis-ui-workbench-closure`（占用 CONV-27）
- Catalog persistence / workspace → `feat/cpp-data-workspace-catalog-closure`
- Workflow scheduler / runtime 服务层 → `feat/cpp-workflow-runtime-closure`（CONV-26）
- 本分支只交付**可被 workflow 注册 node adapter 的 service 面**；
  Python 生产链 rewire 由 Workflow/UI 分支在 service 面稳定后进行
  （`factor_interpolation.py` 编排、`geological_mapping_service.py`、
  harness actions 的调用方迁移不在本分支）
- 不重写任何已冻结 kernel；不统一 mapping(含边)/geomodel(严格) 两个
  point-in-ring 语义（各自冻结）

### 复用图（禁止重复算法）

- `pwb::science`（libs/algorithms）：IAlgorithm / AlgorithmRegistry /
  Result / IResultPublisherV1 —— 服务层的 SDK 基座
- `pwb::workflow::TaskRuntime`：执行编排（publish-before-terminal / 取消线性化）
- mapping_kernel 14 头、well_science 6 头、factor_host 5 头、
  factor_fusion 4 头、geomodel 11 头 —— 纯函数薄包装
- legacy grid dict 解码单一实现（`legacy_dict_to_fusion_grid` /
  `legacy_dict_to_mapping_grid` 共享一套校验）；嵌套列表编码复用
  CONV-18 `encode_legacy_grid_lists`；不再有平行实现

## 验收（Oracle）与实测

1. ✅ 端到端：catalog-like input DTO（InMemoryPayloadSource）→
   AlgorithmRegistry → TaskRuntime → DirectoryEnvelopePublisher 落盘 →
   envelope 字段/fingerprint/文件齐全 + failure.json / cancelled 路径
   （`science_service.e2e`）
2. ✅ 服务级 frozen oracle：19 案例（真实 Python 生产叶：sample_normalization
   + IDWInterpolator/_pure_numpy_kriging + generate_contour_layer +
   curve_operations + viz.geomodel.builders；cpp-contract 案例显式标记），
   C++ replay 全过 + 比较器 negative self-check（损坏期望必须被抓）
3. ✅ 取消：pre-stopped token 在阶段边界 → TaskCancelled（suite）
4. ✅ 资源守卫：grid_n/records/curve/cells/geomodel 顶点 + envelope 尺寸
   独立上限（suite + fusion 截断诊断）
5. ✅ 本地 configure/build/ctest：**44/44 全树绿**（含全部既有 kernel oracle
   + 3 个新测试）
6. ✅ 三轮 review（A/B/C）完成并修复（见迭代记录 R4）
7. ⏳ PR 创建

### 验证配方（本机实测）

```bash
cd /home/kevin/project/worktrees/cpp-science-well-geomodel-closure
# SDK 工具链（本机 cmake/ctest 不在 PATH，SDK 自带；librhash 需 LD_LIBRARY_PATH）
export LD_LIBRARY_PATH=/home/kevin/pwb-sdks/root/usr/lib
export PATH=/home/kevin/pwb-sdks/root/usr/bin:$PATH
# 门禁：独占共享槽 + >=8GiB + build 限 <worktree>/build；-DPWB_BUILD_PLATFORM=OFF
#（本切片 Qt-free；PLATFORM 默认 ON 会要求 vendored QGIS）
./scripts/cpp-migration/invoke-resource-gate.sh Configure -s . -b build/conv-28 \
    -a "-DPWB_BUILD_CONV_28=ON;-DPWB_BUILD_PLATFORM=OFF;-DCMAKE_BUILD_TYPE=Release"
CMAKE_BUILD_PARALLEL_LEVEL=2 ./scripts/cpp-migration/invoke-resource-gate.sh \
    Build -s . -b build/conv-28 -c Release
cd build/conv-28 && ctest -j2        # 44/44
# oracle 再生成（仅生成时用 Python；numpy+scipy venv）
/home/kevin/oracle-venvs/fusion/bin/python tools/oracle/generate_science_service_fixtures.py
```

注意：`-DPWB_BUILD_CONV_28=ON` 单独打开会因 `PWB_BUILD_PLATFORM` 默认 ON
撞 QGIS SDK fail-closed 检查 —— 需要 `;-DPWB_BUILD_PLATFORM=OFF`（与
sibling CONV 切片相同的独立配置语义）。

### 关键发现（冻结进 oracle/测试的语义结论）

1. **kNN 等距并列**：`max_neighbors + search_radius` 组合下，对称采样几何
   会产生等距并列第 k 邻居；scipy cKDTree 与 C++ 暴力法打破并列的规则不同。
   kernel 冻结契约明确只覆盖"唯一距离邻域集"（interpolator.hpp），oracle
   案例改用非对称几何（生成器注释记录）。
2. **单点插值**：Python/C++ kernel 一致拒绝（<2 有效点，冻结 ValueError 文本）
   —— 服务层透传为 `factor.interpolate` 诊断（oracle 冻结）。
3. **constrained IDW host 契约**：kernel Config 默认 value [0,1]/search
   10000/decluster 6500 会静默截断真实因素场 —— Python host 集成
   （constrained_idw_adapter）必须从井数据推导；服务层已内建推导
   （显式覆盖优先），`keep` policy 因引擎 first-wins 拒绝（冻结中文消息）。
4. **geomodel export QC 门**：MISSING_CRS（crs "unknown"）是 blocker ——
   export 请求必须显式携带 crs。
5. **section 节点上平面**：平面恰好压在节点列时分链行为未指定 —— oracle
   只冻结几何契约（一般 in-cell 平面的单链 + 端点 + 共面性）。

## 迭代记录

| 轮 | 改动 | 验证 | 判定 | 下一步 |
|---|---|---|---|---|
| 1 | 只读盘点（2 个并行只读 agent）：C++ kernel API 清单 + Python glue 面；建 worktree/scope ledger | 复用图成立：全部数值 kernel 已就位，缺口=服务组合层 | 通过 | 服务层 API 细化 + 编码 |
| 2 | CONV-28 全量源码落地（10 服务 typed API + envelope + payload source + publisher + 10 适配器 + SDK additive records + oracle 生成器 19 案例 + 3 测试）| 单文件语法检查全绿（构建被并行 worktree 占用门禁槽）| 通过（源码级） | 门禁下 configure/build/ctest |
| 3 | 编译/链接修复 + oracle 对账修复（单点=拒绝、kNN 并列、NaN<->null、top/bottom thickness、volume: 前缀、CRS 传播、smooth/unit_conversion 表名等） | **44/44 全树 ctest 绿**；E2E demo envelope 实检（全字段 + 指纹 + 产品层）| 通过 | 三轮 review |
| 4 | 三轮 review（A 正确性/B 架构/C 产品闭环）修复：constrained 值域推导（P0）、sha256 字节摘要、publisher 路径消毒、build_identity 丢失、Windows 守卫、fusion envelope 上限、pack_result 无异常契约、共享解码器、fault adapter（第 10 服务）、测试补真 | 44/44 保持全绿（含新 constrained/capture/registry 用例）| 通过 | ledger 收口 + push + PR |

## 已知限制（如实）

- `well.curve_operation` 派发 9/11 注册操作（depth_unit_normalize /
  derive_curve 未接线 —— 后者需要 curve_expr 上下文组装，后续小切片）
- constrained IDW 的 `barrier_buffer_distance_for_crs`（地理度 CRS 的 ~300m
  度换算）未内建 —— host 需显式传 barrier 参数（Python adapter 同源逻辑）
- Publisher 无 fsync（进程崩溃安全，掉电不保证 —— mock publisher 语义）
- Windows 分支已做守卫但本机只验证了 Linux 构建
- Python 生产链 rewire 未做（本分支交付 service 面；Workflow/UI 分支消费）
