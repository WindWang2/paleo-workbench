# CONV-23 findings — workflow/contracts 集群勘察

## 切片选定

M7 延续：`paleo_workbench/workflow/contracts/` 是 workflow 剩余代码中依赖最轻的完整子包（全部导入仅指向自身），~2.6k 行，契约声明密集。与 conv-06/07/08/18 已移植的 DAG/factor_host 核互补：那些是执行核，这是**词汇表**——后续 freshness/factor_fusion/map_product 等服务层切片都以这些契约为输入。

## 文件盘点（paleo_workbench/workflow/contracts/）

| 文件 | 行 | 性质 | 迁移判定 |
|---|---|---|---|
| `models.py` | 244 | pydantic BaseModel×10 + str Enum×11 + `completeness()` | **入**——pydantic 用量最简（defaults + `Field(default_factory=list)`，无 validator/model_config），C++ 用带默认成员初始化的 struct + `model_dump()`/`from_json` 等价物 |
| `modules.py` | 1491 | `build_all_contracts()` 返回 14 个模块契约（`_ev`/`_q` helper + 每模块私有 builder） | **入，但声明数据走生成式 `.inc`**——同 `lower_map.inc`/`word_char_ranges.inc` 先例：生成器把 14 个 `model_dump(mode="json")` 冻结为 C++ 可解析数据，避免 1491 行手工转录的错字面；`build_all_contracts()` 在 C++ 侧解析 .inc → 真 struct |
| `registry.py` | 83 | dict 注册表 + 构造期 `validate_registry` + 导航 + `p0_ids` + 默认单例 | **入**——重复 id `ValueError`、upstream/downstream 过滤存在性、insertion-ordered `list_contracts` |
| `validation.py` | 78 | 注册表一致性检查（边镜像、datarun op 白名单、专家问题完备性） | **入**——纯谓词，issue 文案逐字 |
| `readiness.py` | 463 | 元数据就绪评估（绝不加载 artifact 体） | **入**——project 为 duck-type；C++ 用 `ProjectView`（成员为 Json）+ `getattr`-等价 helper 保 None/missing 语义 |
| `report.py` | 228 | 确定性 Markdown 报告（consultation + gap） | **入**——`_cell` 转义、`or '—'`、`enumerate` 序号、SECTION_ORDER 过滤；`write_reports` 仅 mkdir+write_text 薄壳，C++ 用 ofstream 等价实现 |
| `__init__.py` | 72 | 再导出 | 不需要（C++ 头文件即接口） |

## readiness.py 的三个 seam（如实记档）

1. **`_resource_payload_present` 的 `Path.exists()`/`is_dir()`**：仅 absolute path 且 root 为真目录时触达 FS。生成器全部用相对路径 + 无 project_root → 走 "return True" 分支；C++ 用 `std::filesystem` 等价实现绝对路径分支（函数级可测，冻结用 $FX 真目录一案）。
2. **`facies_prediction` 的生产模型探针**：`svc.find_production_model(CAPABILITY_FACIES)`——svc 为 None→`no_production_model`("目录未连接")；返回 None→`no_production_model`("科学预测不可用")；抛异常→`catalog_read_error`。C++ 定义 `ProductionModelProbe` 接口注入（D 记档的显式 seam）；oracle 用桩对象冻结三条路径。
3. **`resolve_correlation_target_horizon` 惰性导入**：只在 `factor_interpolation` 且全任务无 target_horizon 时调用，结果仅 `pass`——**无可观察行为**，不移植（D 记档为非目标）。

## 既有可复用面

- `Pwb::Domain` 的 `Json`(ordered_json)+ `json_semantically_equal`/`json_semantic_diff`——模型 `model_dump` 对账与 readiness project 输入。
- ingest `py_compat` 的 `getattr` 语义不靠它——readiness 的 getattr-with-default 逻辑薄，直接在 `ProjectView` helper 内实现。
- CMake/测试惯例：`PWB_BUILD_CONV_23` 默认 OFF + 隐含 DATA（Pwb::Domain）；oracle `indent=1 ensure_ascii=False` + `$FX` + raises 类名/消息双断言 + dump/parse 归一化比较。

## 对账面（fn 分派）

- `contract_dump`：14 个 `model_dump` 逐案（验证 from_json→to_json 往返与字段默认）。
- `completeness`：14 案的 `completeness()` dict。
- `registry_*`：list 顺序 / get_contract hit+miss / by_category / upstream+downstream（含 unknown id→[]）/ all_expert_questions / p0_ids / validation_issues / duplicate-id `ValueError`。
- `custom_registry`：桩契约集合（断镜像边、未声明 op、缺 expert_question_id、空 question、无 path evidence）→ `validate_registry` issue 文案。
- `readiness`：~20 个 project 场景 × 契约（缺输入/ambiguous/连井 2 口+深度域混用/factor_interpolation 三分支/paleomap 三分支/facies_prediction demo+mock+探针三态/quality_control/export/geomodel/未知契约）。
- `report_consultation`/`report_gap`：全文本字节对账（含 project 就绪段开/关两态）。
