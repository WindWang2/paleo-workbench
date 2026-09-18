# CONV-23 decisions — workflow/contracts 移植决策

- **D1 新叶库 `libs/workflow_contracts`**：不放进 `libs/workflow`（该库经 science_suite 入构建、链 Pwb::Science，非纯叶）。新库 Qt-free、仅链 `Pwb::Domain`(Json)。`PWB_BUILD_CONV_23` 默认 OFF，隐含 `PWB_BUILD_DATA`。
- **D2 pydantic→struct**：`models.py` 的 BaseModel 仅用到 defaults + `Field(default_factory=list)`；C++ 用带默认初始化的 struct + `model_dump()`/`from_json`。Enum 全部 `str`-valued，C++ 用 `std::string` 常量 + 校验函数（构造面宽容、序列化直出字符串）；`X.value` 语义即字符串本身。
- **D3 声明数据生成式 `.inc`**：`modules.py` 1491 行声明不手工转录——生成器把 `build_all_contracts()` 的 `model_dump(mode="json")` 序列化为 `src/modules_data.inc`（紧凑 JSON 文本嵌入），C++ `build_all_contracts()` 解析为 struct。同 `lower_map.inc` 先例：**数据冻结、行为原生**。差异可在 diff 中审计。
- **D4 project duck-typing**：readiness 的 `getattr(project, "resources", None) or []` 语义 → `ProjectView` 成员为 `Json`（缺省=null→empty）；叶子记录保持 Json，`attr(obj,key,default)` helper 保 None/missing/`or ""` 语义（`getattr(x,"s","") or ""` = 缺省或 None 或空→"")。
- **D5 探针 seam**：`ProductionModelProbe` 接口（`virtual std::optional<bool> find_production_model(std::string_view cap)`；nullopt=Python 返回 None 语义即"无生产模型"，异常→`catalog_read_error`，probe 本身 null→`svc is None` 分支）。这是 D 记档的显式 seam，非生产 test double。
- **D6 FS 分支**：`_resource_payload_present` 绝对路径分支用 `std::filesystem::exists`/`is_directory`；`root != "."` 且 `is_dir(root)` 才拼接判定。生成器冻结相对路径无 root 的 `return True` 主路径 + 一个 $FX 真目录案。
- **D7 报告字节级**：`"\n".join(lines)` 无尾换行；`_cell` 先 `or ""` 再 replace `|`→`\|`、`\n`→空格、strip；`or "—"` 的 None/空串合并；`enumerate(op,1)` 序号；SECTION_ORDER 按表过滤空类。`write_reports` 返回两路径，C++ 提供 `write_reports(dir)` 返回 `{consult_path, gap_path}` 对（ofstream UTF-8 直写）。
- **D8 `import` 循环惰性**：readiness 函数体内的 `from ...providers import CAPABILITY_FACIES` 与 `from ...catalog import get_catalog_service` 均为惰性——C++ 以 `static constexpr char kCapFacies[]` 直写常量 `"facies"`（值冻结于 oracle）；`get_catalog_service` 全局回退在 C++ 侧即 probe=null 语义。
- **D9 `dict.get`/集合语义**：`_resource_counts` 的 `counts.get(t,0)+1` → `std::map`/`unordered_map`（顺序无关，迭代只读求和）；`sorted({...})` 去重排序 → `std::set`；`{...} in set` 成员判定按值。
- **D10 oracle 协议**：`indent=1 ensure_ascii=False`；raises 类名+逐字消息双断言；`run_case` 按 fn 分派；dump/parse 归一化两侧整数类差（int-vs-float 仍真实差异）；生成器自断言案例数；重跑逐字节一致。
- **D11 非目标**：`resolve_correlation_target_horizon` 惰性调用（无可观察行为）、`__init__.py` 再导出层、`get_default_registry` 进程级单例的跨线程懒初始化竞态（C++ 用函数级 static，线程安全且语义等价）、pytest 迁移、UI/服务层接线（后续切片）。
