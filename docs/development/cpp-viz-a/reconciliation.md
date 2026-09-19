# VIZ-A LAS 解析对账裁决（lasio/Python 遗留路径 vs WLE LasSourceAdapter）

口径：Python 参考路径 = 真实生产 Python 预览
（`paleo_workbench/resources/preview_parsers/well_log_parsers.py::las_preview`
→ `geoviz_well_log.las_preview.inspect_las_file` + `native_backend` 快解析回退 +
`lasio` 回退），由 `tools/oracle/generate_viz_a_las_fixtures.py` 逐 fixture 实跑冻结
（`tests/cpp/viz_a/fixtures/las_preview_oracle.json`，18 案例 + 18/18 负面自检）。
WLE 参考 = `well-log-engine/src/io/las.cpp @ f845e7ab` 契约转录（生成器内逐条引用行号），
由 C++ 测试（`viz_a.las_preview_wle`）用真实 WLE 验证。

**总原则（一致性优先）**：WLE 是生产解析器（dock/preview/worker 三路共用同一
`LasSourceAdapter::parse` 字节流调用，不做任何预归一化）。凡 Python 更宽容而 WLE
拒绝的输入，三路一致失败（诚实 message），不为了预览单独放宽——否则同一文件
dock 打不开而预览"成功"，违反硬性 Oracle 1。Python 更宽容的行为保留在 Python
产品入口（M12 前不动），作为 legacy reference 冻结在 oracle 的 `python_result` 里。

## 裁决清单

| # | 差异 | Python 行为 | WLE 行为 | 裁决 |
|---|---|---|---|---|
| R3 | 行宽判定（`03_bad_rows`） | 有效行 = tokens **≥** 列数且深度合法（曲线 token 坏不影响行计数；长行算有效） | tokens **==** 列数（短/长行丢弃 + `short/long_ascii_row` 诊断；`invalid_ascii_value` 行也丢弃） | 采用 WLE。预览 `采样点`=WLE 接受行数；坏行以诊断存在（WLE diagnostics），预览不静默丢弃。Python 的 4 vs WLE 的 2 已冻结为证据 |
| R4 | null 判定容差（`17_null_tolerance`） | `isclose(null, abs_tol=1e-6)` | 精确 `==`（sentinel 取自 `~W NULL.`，无默认值） | 采用 WLE 精确语义。±1e-6 区间差在预览表 `%.4f` 格式下不可见（冻结案例 17 两参考一致）；worker/dock 路径语义差已记录。Python 侧 NULL. 缺省时默认 -999.25；WLE 无 sentinel 行则不判 null（NaN/Inf 仍判）——该差同样在 17 号外无观察面 |
| R5 | 深度倒序（`05_descending`） | 接受（不检查方向） | 接受（单调降，`SamplingAxis.direction` 记录） | 一致，无裁决 |
| R6 | 重复深度（`06_duplicate_depth`） | 保留、不诊断 | 保留、不诊断（方向计算跳过相等相邻值） | 一致，无裁决 |
| R7 | wrapped 数据表（`09_wrapped`） | 快路径拒绝 wrapped → lasio 回退；本案例 lasio 产生**退化表**（token 交错、GR 列全 NaN，见 oracle `python_result`） | 原生按列数切片重组，得到正确 3×2 表 | 采用 WLE（Python lasio 的 wrapped 表是已知退化行为，冻结为证据） |
| R8 | 深度道命名（`12_depth_named_md`） | 深度道缺失时回退第 0 条曲线 | 必须存在 mnemonic ∈ {DEPT, DEPTH}（首个匹配），否则整体 invalid | 采用 WLE。首列非 DEPT 命名的文件三路一致失败；如产品需要支持，应立项 SDK 扩展（本线不改 SDK） |
| R9 | 零有效行（`14_all_rows_invalid`） | inspect 成功（采样点 0），数据表仍有行（快解析不剔行，深度 null→NaN 显示）；Python 自身 summary 与 data 表不一致（0 vs 2 行） | `depths.empty()` → invalid | 采用 WLE。Python 自身不一致的行为冻结为证据 |
| R10 | WRAP 变体（`15_wrap_y`） | YES/Y/TRUE/1 | 仅 YES/NO，其余 invalid | 采用 WLE |
| R11 | VERS 缺失（`11_missing_vers`） | 不检查版本 | VERS 必须存在且 2.0≤v<4.0 | 采用 WLE（LAS 规范要求 VERS） |
| R12 | 混合深度方向（`13_mixed_direction`） | 接受（不检查） | 整体 invalid（升/降混合） | 采用 WLE（混合方向数据无明确深度轴语义） |
| R13 | DLM 逗号分隔（`16_dlm_comma`） | inspect 支持 DLM COMMA/TAB；数据表快解析仅空白切分（逗号 token 数值前缀截断，产生 NaN 列）——Python 数据表同样退化 | 仅空白/制表切分；逗号 token → `invalid_ascii_value` → 全行丢弃 → invalid | 采用 WLE。两条路径对逗号 LAS 都不产生可用数据（Python 数据表退化、WLE 明确拒绝）；支持逗号 DLM 需 SDK 扩展，另行立项 |
| R14 | 单位字段（`07_units_desc`） | unit = 点后整个 trimmed 字段（内嵌空白保留，如 `US/M\t声波`） | unit = 点后首 token（`US/M`） | 预览表采用 WLE 语义（桥接扫描取首 token），保证与 dock 单位一致；Python 内嵌空白单位是解析瑕疵，冻结为证据 |
| R15 | 行内 `#` 注释（`18_inline_comment`） | 头部行不截断（井名/描述保留 `#` 后文本，仅跳过 `#` 开头的行）；数据行 token 保留 `# tag`（ragged → 列数警告/lasio 表） | SDK 全部 section 行内 `#` 截断（`las.cpp:174-176`）：头部无观察差；数据行截断后按正常行解析 | 桥接头扫描采用 Python 语义（跳过 `#` 开头行、不截断行内），数据行由 SDK 截断——头表与 Python 一致、数据表与 dock 一致；`18` 号冻结 |
| R16 | 井名 `WELL.` 多行/空值（`19`/`20`） | last-wins（后值覆盖前值，含空值覆盖→回退 stem） | SDK 不提取（身份走 uri#checksum） | 桥接侧 last-wins（已按 Python 修正，`19`/`20` 两参考一致）；Unicode 井名（`08`）用例覆盖 |
| R17 | 数据行内注释（`18` 数据行） | 快解析保留 `# tag` token → 列数不一致警告路径 | SDK 截断 → 正常行 | 采用 WLE（数据表与 dock 一致）；Python 的列数警告（`数据表列数（X）与曲线定义数（Y）不一致`）与 lasio 回退警告在 WLE 桥下不可达（列数恒等、无回退路径），声明为不适用 |
| R18 | 坏 ~C 行（`21`/`22`） | inspect 跳过坏行：全坏 → no-curve 分支；混合 → 预览正常 | SDK 遇坏 `~C` 行整体 invalid（`las.cpp:230-234`） | 桥接头扫描跳过坏行（Python 语义）；全坏 → 不调 SDK → no-curve 分支（与 Python 一致，`22`）；混合 → SDK 拒绝 → parse_error（三路一致失败，`21` 冻结为证据） |
| — | 多 section `~O`/`~P`（`01`） | lasio 保留（不展示） | 忽略（`LasSection::none`） | 无预览差，一致 |
| — | 曲线数口径 | 含深度道的 ~C 全部条目 | document 只含非深度曲线 | 预览表/曲线数按 ~C 全量（Python 口径，坏行两侧都跳过），数据表按列序重插深度列——与 dock 的 per-curve 事实不冲突（dock 消费 document） |
| — | wrapped 检出 | YES/Y/TRUE/1 | 仅 YES/NO | 桥接诊断近似 Python 口径记录 wrapped 标志（取首个 token 归一，仅诊断展示，不参与解析） |

## 汇总

23 案例（17 变体 fixture + A1 真实文件 + 5 语义回归 fixture）：12 例两参考逐字段一致；
11 例不一致全部落在 R3/R4(不可见)/R7–R15/R17/R18 裁决内，无未标注分歧。
`lis/dlis/format716` 不在本对账范围（geoviz `las_preview.py` 只读 LAS；
WLE 的对应 io 面不迁移、不重写——见 gap-table.md 排除项）。

## 审核修订记录

- R1-P0：生成器 WLE 契约模型的 first_token/split 与 token 切分转录错误（tab 语义）已修；
  坏 `~C` 行分层（全坏=no-curve / 混合=SDK 拒绝）按 R18 建模。
- R1-P1：`py_round` 改 printf 正确舍入（`round(2.675,2)=2.67` 反例）；井名改 last-wins
  （R16）；行内 `#` 头部不截断（R15）。
- R2-P0：apps 接线因 add_subdirectory 顺序恒死的 CMake 缺陷已修（根 VIZ-A 块统一挂）；
  DATA+SCIENCE+VIEWER 配置下 bridge 静默缺失的顺序脆弱性已修（VIZ_A_LATE_BRIDGE 重入）。
- R2-P1：viewer_flow PNG 魔数断言索引错误已修；门禁脚本 `if/fi` 吞 exit 75 的假绿已修
  （`|| code=$?` 捕获 + 仅 75 重试）。
