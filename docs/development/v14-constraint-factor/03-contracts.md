# V14-CONSTRAINT-FACTOR — 03 契约

## C++ API（新，`pwb::closure_workflow`）

```cpp
// factor_prepare_production.hpp

// 1) 项目切片：PwbDataStore root → ui_workers::PrepareProjectSlice。
//    sample_points 以 vector<map<string,any>>（well/x/y/value[/q/b_i/qc_flag]）
//    装载——与 synthetic_points seam 的既定 any 约定一致（param_truthy 语义）。
PrepareProjectSlice build_prepare_slice(const Json& project_root);

// 2) live 网格缓存（factor_grid_artifacts.py 核心语义）
struct LiveGridEntry {            // 密封载荷
    std::vector<double> grid_x, grid_y;
    std::vector<float> grid_z;    // row-major |y|*|x|, NaN=nodata
    std::string result_fingerprint;
    Json metadata;                // grid_metadata descriptor
};
class LiveFactorGridStore {
  public:
    void store(const std::string& task_id, LiveGridEntry grid);   // 先 clear 再存
    std::optional<LiveGridEntry> peek(const std::string& task_id) const;
    void clear(const std::string& task_id);
    bool clear_if_fingerprint(const std::string& task_id, const std::string& fp);
    bool has(const std::string& task_id) const;
};

// 3) seams 工厂：返回全绑定 FactorPrepareSeams。
struct FactorPrepareKernelConfig {
    int max_workers = 0;                 // 0 → env/硬件推导（clamp 1..4）
    std::string generator_version = "factor-interp-v1";
};
FactorPrepareSeams make_factor_prepare_seams(
    std::shared_ptr<LiveFactorGridStore> grids,
    const FactorPrepareKernelConfig& config = {});

// 4) host commit（GUI 线程）。返回 discarded task ids（Python 契约）。
struct CommitPrepareReport {
    std::vector<std::string> discarded;
    int applied = 0;
    std::vector<std::string> registered_version_ids;  // catalog 登记（空=未接 catalog）
    std::vector<std::string> registration_errors;
};
CommitPrepareReport commit_prepare_batch_result(
    Json& project_root,                       // live 文档 root（唯一写者）
    const ui_workers::FactorPrepareBatchResult& result,
    int expected_generation,
    LiveFactorGridStore& grids,
    workflow_runtime::CatalogRepository* catalog = nullptr,  // null=诚实降级
    const std::string& project_crs = "");

// 5) 等值线 commit 升级：upsert（保 id）+ paleomap_documents 推送。
int commit_contour_drafts_full(Json& project_root, const Json& drafts_array,
                               const std::string& generator_version);
```

## 任务 JSON 契约（本线写者；字段与 Python 完全同名）

`factor_map_tasks[i]`（commit 后）：

| key | 写入者 | 语义 |
|---|---|---|
| `status` | batch | `pending/complete/failed`（词表冻结） |
| `method` | batch | 归一后方法（`mock→IDW`） |
| `parameters.sample_points` | 既有/合成 | **RAW**（非归一化集） |
| `parameters.sample_normalization` | batch | 归一化报告（duplicate_policy 生效时） |
| `parameters.duplicate_policy` | 既有 | mean/first/error/keep |
| `parameters.well_table_id` | 既有 | 井表绑定 |
| `parameters.constraint_pins` | batch | `[{group_id,group_name,content_hash,line_count,version_id?}]` |
| `parameters.grid` | batch | `"n×n"` 字符串 |
| `parameters.interp_backend/power/grid_n` | batch | 引擎记录 |
| `parameters.constraint_diagnostics/n_break_lines/n_direction_lines` | batch | 约束消费诚实性 |
| `parameters.kriging_diagnostics` | batch | kriging |
| `parameters.azimuth_deg/semi_major/semi_minor` | batch | 方向线参数（有 direction 时） |
| `parameters.{schema_version,geometry_fp,values_fp,algorithm_fp,constraints_fp,result_fp,backend}` | batch | Stage-4 指纹（stamp_fingerprints_on_task） |
| `grid_x/grid_y/grid_z/grid_var/grid_boundary`（parameters 内） | batch **剔除** | 网格数组永不入 parameters |
| `input_snapshot_hash` | batch | = result_fp |
| `generator_version` | batch | `factor-interp-v1` |
| `grid_metadata` | batch | descriptor（含 algorithm_parameters.result_fingerprint） |
| `grid_artifact_path/grid_artifact_version_id` | commit | 重插值即置 null；catalog 登记成功时填 version_id |
| `quality_metrics` | batch | `{range,r_squared,grid,n_points,backend,mean[,unit][,duplicate_wells_dropped...]}` |
| `source_json`（仅内存 slice，不落盘） | 切片构建 | 原始任务 JSON，供 commit 整体替换保未知字段 |

## catalog run 契约（register_factor_map_run 的 C++ 移植）

每个成功 commit 的任务（reused 不重复登记）：

```text
operation            = "factor_map"
input_version_ids    = []（井/约束以 pins+hash 表达；无上游版本时如 Python）
parameters           = {factor_type, target_horizon, method, grid_n, power,
                        constraint_pins, n_points, backend, generator_version}
generator_version    = "factor-interp-v1"
domain_task_id       = task.id
input_snapshot_hash  = result_fp
status               = "running" → 登记 INTERMEDIATE 版本 → "complete"
asset                = register_result_asset(name=f"{horizon} {factor_type} 网格",
                      type="factor_map_grid", format="json",
                      payload=FactorGridEnvelope JSON, stage="INTERMEDIATE")
                     → task.grid_artifact_version_id = version_id
失败                  = update_run_status(run, "failed", {error})
```

payload 用 `mapping::factor_grid_io` 的 envelope JSON（to_legacy_dict/to_descriptor 既有 codec）——JSON 字符串传输是 workflow seam 既定约定（map_product 同型）。

## 等值线 upsert/map-apply 契约（Python commit_contour_drafts 移植）

1. 同 `linked_factor_task_id` 的既有 draft → **保 id** 替换；无 link 时按 (horizon, factor_type, generator_version) 匹配；否则 append。
2. `apply_contour_draft_to_map`：复用 `draft.linked_map_document_id`，否则新建 `PaleoMapDocument(name=f"{horizon|'图件'} 等值线")`；剥离该文档既有 `role=="contour"` line features 后追加（`{id, kind:"line", name:"L=<level>", role:"contour", coordinates, properties:{role, constraint_role:"contour", level, closed, contour_draft_id, factor_type, target_horizon}}`）；draft.status→"editing"。
3. 返回创建/更新 draft 数。

## 指纹复验契约（commit stale-input 守卫）

- 复验**必须**用 scheduled overrides（`result.method/result.grid_n/result.power`），**不得**用任务存储参数；
- 复验**不走 memo**（从 live 输入重推导）；
- `current.result == item.scheduled_result_fingerprint` 不成立 → 丢弃该 task 补丁 + `clear_live_factor_grid_if_fingerprint(tid, grid_result_fingerprint(item.grid))`（无 grid 则不清）。

## 输入契约（Stage1→Stage2）

- 井表 → sample_points：`value_key_for_factor_type` 语义（砂地比→R_s、地层厚度→H_t、砂岩厚度→H_s、其他→z；qc_flag≠ok 默认排除）在 C++ 侧按同表实现（本线落 `well_table_bridge` 辅助）。
- 约束：`constraint_layers_for_project`（空 horizon 或匹配）→ break（active、≥2 点，IDW/constrained 有效）/direction（azimuth=首段方位角 atan2(dx,dy)，多线圆周平均）/boundary（闭合、≥4 点）。
- CRS：组内声明不一致 → fail-closed；项目 CRS 参与 result 指纹。
