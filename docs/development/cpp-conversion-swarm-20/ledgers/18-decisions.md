# 18 — Decisions(非显然选择逐条记录)

D1. **路径差异**:prompt 假设仓库在 `/home/kevin/projects/paleo_project/main`、
worktree 在 `…/paleo_project/worktrees`、goal-loop skill 在 `/home/kevin/.grok/`。
本机实际:仓库主工作区 `/home/kevin/project/paleo-workbench`,worktree 惯例
`/home/kevin/project/worktrees/`(conv-11…16 同),goal-loop skill 文件不存在
——按已落地的 karpathy-guidelines(`agent/skills/`)与仓内
`docs/development/cpp-conversion-main-plan.md` 执行,GOAL Loop 的流程约束
(账本、完成条件、配额)按 prompt 原文照做。

D2. **`src/factor_grid_io.cpp` 落位**:`libs/mapping_kernel/src/factor_grid_io.cpp`
(与既有核同目录;§6 写 `src/…` 相对上一行的 libs/mapping_kernel 解析)。

D3. **NPZ 容器不在本切片**:§4 目标 = 序列化/from_legacy/encode_legacy_*(全部
JSON),§7 步骤只写 JSON NaN→null,§8 oracle 是 ctest 对账。grid_artifact.py 的
NPZ zip/.npy 容器、write/read_grid_artifact、artifact_file_identity 属后续切片。
但 `__descriptor__` = `to_descriptor()`(+artifact_version/boundary_ring)是
JSON 契约,C++ `to_descriptor` 与其语义等价;`boundary_ring`/`artifact_version`
两个键是 write_grid_artifact 追加的,**不进** C++ to_descriptor 输出。

D4. **C++ 读路径统一到 from_legacy_task_parameters**:验收「Python 写 JSON →
C++ 读回 grid_z+statistics 一致」的 JSON 载体是含 grid 数组的 legacy dict
(to_legacy_dict 输出 / 老工程内联 parameters)。Python 测试自己也是用
from_engine_dict 读 to_legacy_dict 输出;from_legacy 与 from_engine_dict 对该
形状同构(backend 键回退、None/NaN 双编码、grid_label/power 两参 get),且
from_legacy 是 prompt 点名的读路径。不为 C++ 另做 from_engine_dict
(Karpathy:最小面)。

D5. **from_constrained_idw_dict / contours 写入不移植**:constrained-IDW 适配器
与 #928 isolines 是另一切片;from_legacy 恒不产生 contours,故 C++ 信封暂不含
contours 字段(descriptor 的 contours 键恒缺,与 Python from_legacy 输出一致)。

D6. **内存层 property/方法不移植**:`copied`、`input_points`、`input_version_ids`、
`run_id` 别名、`dx/dy/cell_size`、`mask`、factor_grid_artifacts.py 的整个
LRU/指纹/工程桥、grid_artifact.py 的文件身份 —— 无 JSON 字节输出。

D7. **NaN/Infinity 字面量容忍**:Python `json.dumps` 默认 allow_nan=True 会写出
`NaN`/`Infinity` 字面量(老工程内联参数的真实形态),nlohmann 按 RFC 拒收。
信封语义里格子级 None/NaN/inf 全部归一为 nodata,`_json_safe` 又把非 finite
全变 null,故解析前把这三个字面量替换为 null 是**本 codec 内无损**的。
`factor_grid_io` 提供 `parse_json_python_tolerant(text)`(~30 行字符串感知扫描),
oracle 的 parameters 以 `json.dumps` 原始字节内嵌字符串字段,C++ 用它解析——
oracle 保持真实 Python 产物,不手写。

D8. **错误分支文案是契约**:C++ 异常 message 与 Python `str(exc)` 对齐:
- KeyError → `"'grid_x'"` 形式;
- ValueError 文案逐字(含 tuple repr 的 shape,如
  `grid_z shape (2, 2) does not match expected (2, 3)`);
- C++ 抛 `std::invalid_argument`(ValueError)/`std::out_of_range`(KeyError)。
oracle 案例存 `error`(str(exc) 全文),C++ catch 后比对全文。

D9. **statistics 复用**:`pwb::mapping::grid_statistics` 已绿
(mapping_kernel.grid_stats),不重写;新增的只是 `to_dict` 的 JSON 化 +
from_descriptor 的信任读取等价物不需要(读路径重算后对账,比 Python 信任写方
更严,允许)。

D10. **to_descriptor 键序**:按 Python 字面量序插入 ordered_json;update 语义
(已有键原位覆盖、新键按序追加)用 ordered_json `operator[]` 天然吻合。
对账用 `json_semantic_diff`(键序无关)为主,**另对 2 个代表案例做
`dump()` 字节级对比**(信息性,不作为门禁;§4 允许语义级)。

D11. **数字身份**:valid_count/total_count/n_points 等写 int;grid/extent/stats
写 double(float32 widen 语义 = `static_cast<double>(float_value)`,与 Python
`float(np.float32)` 位模式一致)。`crs_is_known`/`has_*` 写 bool。

D12. **Python oracle 解释器**:`/home/kevin/project/oracle-venvs/conv11/bin/python`
(numpy 2.5.3;系统 python3 无 numpy)。生成器按 `__file__` 定位 REPO_ROOT 并
前置 sys.path,**运行 cwd 必须不在主工作区**(否则 cwd `''` 遮蔽 worktree 副本)
——用 worktree 根为 cwd。

D13. **CMake**:根 CMakeLists 追加 `BEGIN CONV-18` 块(option + 无 add_subdirectory,
仅当 PWB_BUILD_MAPPING_KERNEL 未开时置位它——codec 物理在 mapping_kernel 内,
避免重复 add_subdirectory);`libs/mapping_kernel/CMakeLists.txt` 追加块用
`target_sources(pwb_mapping_kernel PRIVATE src/factor_grid_io.cpp)`(不重写
add_library 原列表);测试目标在 `mapping_kernel_tests/CMakeLists.txt` 追加块,
`PWB_BUILD_CONV_18` 门控。

D14. **subagent 配额用法**:1 explore(本文件撰写前的源码复核,若需要)、
2 spec 对抗审核、3 Karpathy/质量审核。父代理自己写全部实现。

D15. **验收口径**:「C++ 读回 Python 写的 JSON」= 解析 fixture 中 Python 冻结的
parameters/legacy-dict JSON → grid_z 逐格(float32 位级)+ statistics 逐字段与
Python 一致;「反向」= C++ 对同信封执行 to_legacy_dict/to_descriptor,与 Python
冻结输出语义相等,且 C++ 内部 round-trip(读自己写的)与 Python round-trip
(pytest 的 lossless 语义)一致。两侧共享 oracle,即双向对账。

---

## Round 4 增补(对抗性 spec 审核后的修正与新增偏差)

D16. **NaN/Infinity 传输升级(替换 D7 的 null 替换方案)**:tolerant 解析不再把
NaN/Infinity→null,而是经字符串哨兵(`@@pwb_json_nan/inf/ninf@@`)还原为真实
非 finite double。理由:NaN 在 Python 真值域是 truthy——`backend=NaN` →
algorithm_id "nan"、`azimuth_deg=NaN` 过 `is not None` 门控(键恒写,descriptor
里经 `_json_safe` 变 null);null 替换在这些位置不无损。哨兵文本碰撞概率工程上
为零,还原后不残留字符串。

D17. **非列表轴 = Python TypeError 分支**:grid_x/y/z 为 null/bool/number 时
Python 在 `list(values)` 抛 TypeError(`'NoneType' object is not iterable` 等),
C++ 以 `std::runtime_error` 镜像同文案;fixture 记录 `error_type`,测试断言
异常类映射(KeyError→out_of_range、ValueError→invalid_argument、
TypeError→runtime_error)。string/dict 轴在 Python 会走到逐字符数值化再失败
(numpy 版本相关文案),病态族,C++ 报 1-D 违规文案,不冻结。

D18. **3-D+ 嵌套 grid_z 忠实 reshape**:numpy 允许 (1,2,2) 等 N-D 输入
reshape 成 (h,w)(元素数匹配即成功,行主序);C++ 递归 flatten 同语义;
计数不符时报错文案带全部维度(如 `grid_z shape (1, 3, 2) does not match
expected (2, 2)`)。ragged(不均匀)嵌套的 numpy inhomogeneous 文案版本相关,
病态族,C++ 报 "inhomogeneous shape"(不冻结,偏差记录)。

D19. **bool 数值化**:numpy 把 True/False 数值化为 1.0/0.0(轴、格点、边界
点一致);C++ `numeric_or_nan` 镜像;fixture `bool_inputs_numericize` 冻结。

D20. **元数据原样透传**:crs/unit/generator_version/run_ref/created_at/
source_refs 在信封中存 Json 原值(Python 是裸 dict 访问,非字符串元素原样
保留,如 `source_refs: ["asset-1", 2, true]`、`run_ref: 9`);descriptor 的
`crs_is_known` = `crs is not None`(任何非 null 值都算 known)。替代原
opt_string 方案(它静默把非字符串降为 null,是数据丢失)。

D21. **metadata.algorithm_parameters 为字符串** 时镜像 Python `dict("abc")`
的 ValueError(`dictionary update sequence element #0 has length 1; 2 is
required`,有 fixture);其他非对象类型(list-of-pairs 在 Python 反而成功等)
病态族,落空 params,记录不冻结。

D22. **sample_points 可 len 类型**:list/dict/str 都贡献 `len()`(Python
`len(x or [])`);number/bool 在 Python 抛 TypeError(不可 len),C++ 落回
params.n_points,偏差记录。

D23. **D10 抽查机制落地**:对 idw_none_cells 与 descriptor_metadata_full 两
案例断言 (a) 声明键序全等(递归布局向量)、(b) `json_semantically_equal`
精确等值(先 `Json::parse(dump())` 归一数字身份——构造的 signed int 与解析的
unsigned int 在 domain 比较器的 type() 检查下不同,parse 往返后同为 unsigned,
这正是该比较器"parsed vs parsed"的预期用法)。

D24. **求和次序(信息性)**:M7 kernel 顺序累加 vs numpy pairwise 在
"大值小方差"网格理论上可触 1e-9 相对容差界;属已冻结的 grid_stats 取舍,
本任务不改数值核。

---

## Round 6 增补(Karpathy 审核后的注释/加固,无逻辑变更)

D25. 病态偏差集中记录(代码内同位注释已标):metadata.algorithm_parameters
非对象非字符串真值落空 params(Python 为 TypeError/pair-list 成功);
sample_points 真值标量(Python len() TypeError)落回 params;数字字符串格元
(numpy 会解析)归 NaN;grid_boundary 真值非数组视为缺席(Python 迭代后死于
float() 转换);boundary 非 pair 行折叠进 finite 文案(Python 是 unpack
ValueError);≥3 维轴的错误 shape 只报前两维(grid_z 路径报全维)。

D26. PWB_BUILD_CONV_18 单独开启时会在 Pwb::Domain 检查处 configure 失败
(与根 CMakeLists "缺模块是 configure error" 协议一致),option 注释已注明
需同设 PWB_BUILD_DATA=ON。
