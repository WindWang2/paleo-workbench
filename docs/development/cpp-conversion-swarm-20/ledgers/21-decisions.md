# CONV-21 Decisions — prediction 契约核

编号 D21-n（前缀 21 防与其他 swarm 冲突）。每条：选项、决定、理由。

- **D1 范围** = `postprocess.py` 全部公开面 + `spatial_result.py` 全部 +
  `input_contract.parse_input_schema` + `model_package` 的纯半（常量/
  manifest/`load_manifest_dict`/`_strict_bool`/`parse_*`/`validate_*`）。
  理由：四个模块中仅有这些是确定性纯函数/浅文件边界，可按 swarm 方法
  冻结 oracle；`resolve_model_inputs`、`_enforce_required_curves`、
  `register_model_package` 走 service/catalog/geoviz，属编排层不迁。
- **D2 落点** = `libs/prediction`（conv-13 已建，Qt-free）。新增
  `postprocess.{hpp,cpp}`、`spatial_result.{hpp,cpp}`、
  `input_contract.{hpp,cpp}`、`model_package.{hpp,cpp}` 与内部
  `python_compat.{hpp,cpp}`（py_truthy/py_str/py_repr/py_round6/
  py_isclose）、`word_char_ranges.inc`（生成表）。
- **D3 输入输出 = `pwb::domain::Json`**（ordered_json）。region/boundary/
  payload/schema/manifest 均以 Json 进出，与 oracle 对账零转译；
  `ModelPackageManifest` 是具名字段 struct（to_dict 固定键序）因其字段
  集是冻结契约。
- **D4 依赖**：`pwb_prediction` PRIVATE 链接 `Pwb::Ingest`
  （`parse_well_tops_text` + `py_parse_float`/`py_strip`/
  `split_path_parts`/`decode_utf8`）与 `Pwb::Interchange`
  （`casefold_utf8`）。复用优于复制；两库同为 Domain 叶子无环。
  根 CMake：`PWB_BUILD_CONV_21=ON` 隐含打开 CONV_13/14/19
  （其 add_subdirectory 在更后位置，前置块先置位）。
- **D5 `\w` 判定** = 生成范围表 `src/word_char_ranges.inc`：oracle 生成器
  用真 `unicodedata.category` 扫全部码点，导出 L*∪N* 的紧凑区间
  （+ '_' 单点）。与 conv-14 unicode_tables.inc 同法，拒绝手写近似。
- **D6 `round(v,6)`** = `snprintf("%.6f")`+`strtod` 往返（Python 精确
  十进制 half-even；不做 v*1e6 近似）。`_display_probability` =
  `clamp(v,0,1)` 后 `nearbyint(v*100)/100.0`（同 double 同 half-even，
  与 f"{v:.0%}" 等价）。
- **D7 falsy/str 语义**：`py_truthy` 覆盖 Json（null/false/0/""/空
  array/object 为 falsy，number 0/-0.0 亦 falsy）；`py_str` 覆盖
  str(x)（bool→"True"/"False"、number→repr、string→自身、null→"None"、
  容器→`py_repr`）；`py_repr` 实现 Python repr（'str'、True/False/None、
  dict/list 递归）——`{stype!r}`/`{value!r}` 错误文案依赖它。
- **D8 文件边界**：
  - `resolve_formation_boundaries`：`inputs[*].path` 经
    `fs::is_regular_file` 判定（≈ Path.is_file），可读时以
    `decode_utf8(strict=false)`（=errors="replace"）解码后喂
    `ingest::parse_well_tops_text`；Python 侧 `parse_well_tops` 的
    异常分支（"井分层解析失败 {cls}"）在 tolerant parser 下不可达，
    C++ 不实现该文案并在本行记档。
  - `load_manifest_dict`：is_regular_file 否则 "Manifest not found:
    {path}"；`read_text(utf-8)` 的解码失败在 Python 是未捕获的
    UnicodeDecodeError（非 ModelPackageError）——C++ 以
    `std::runtime_error` 携带同形 "'utf-8' codec can't decode …" 文案
    抛出（oracle 可断言类型区分）；OSError/JSONDecodeError 合并为
    `ModelPackageError("Invalid manifest JSON: {exc}")`，其中 JSON
    解析细节用 nlohmann 诊断（D9）。
  - `validate_model_package` 的 artifact：`fs::is_regular_file`；
    sha256 经 `Pwb::Domain` `Sha256::of_file`（字节一致承诺）。
- **D9 偏差如实记档**：`json.loads` 的报错文案（"Expecting value:
  line 1 column 1 (char 0)"）与 nlohmann 诊断串不同源，C++ 保留
  `"Invalid manifest JSON: "` 前缀，细节文案不逐字对账（oracle 断
  言前缀 + 类别）；artifact resolve 用 `fs::weakly_canonical`
  ≈ `Path.resolve(strict=False)`。`str(exc)` 形态差异同类处理。
- **D10 校验副作用**：`validate_model_package` 在 checksum 缺省且文件
  可读时回填 `manifest.checksum`（Python 原行为），C++ manifest 传
  引用保留该可观察副作用。
- **D11 错误即数据**：`validate_*`/`postprocess_*`/`resolve_*` 以返回值
  携带错误串（对齐 Python 返回 list[str]/diagnostics），不抛异常；
  `ModelPackageError`/`SpatialResultError`/`InputContractError` 仅在
  Python 抛异常处抛（load/parse/strict_bool）。
- **D12 oracle 协议**：JSON null 表 None；NaN/Inf 不出现在 fixture
  （输入侧以 "nan"/"inf" 字符串或省略覆盖 _finite_number 分支）；期望
  errors/diagnostics/records/summary 全量冻结；容差字段随案携带。
  生成器自断言：案例 ≥80、两次运行逐字节一致。
- **D13 非目标**：真 ONNX session、inference_service、providers 注册表、
  catalog 注册链、pytest 迁移、UI 接线——均不在本片。
