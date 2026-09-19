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
| — | 多 section `~O`/`~P`（`01`） | lasio 保留（不展示） | 忽略（`LasSection::none`） | 无预览差，一致 |
| — | 井名 `~W WELL.`（`01`/`08`） | 提取 | SDK 不提取（身份走 uri#checksum） | 桥接侧自行扫描（Python `_well_item` 语义：首 `.` 到 `:` 前，trim），三路井名一致；Unicode 井名（`08`）用例覆盖 |
| — | 曲线数口径 | 含深度道的 ~C 全部条目 | document 只含非深度曲线 | 预览表/曲线数按 ~C 全量（Python 口径），数据表按列序重插深度列——与 dock 的 per-curve 事实不冲突（dock 消费 document） |
| — | wrapped 检出 | YES/Y/TRUE/1 | 仅 YES/NO | 桥接诊断按 Python 口径记录 wrapped 标志（不参与解析） |

## 汇总

18 案例：9 例两参考逐字段一致；9 例不一致全部落在 R3/R4(不可见)/R7/R8–R14 裁决内，
无未标注分歧。`lis/dlis/format716` 不在本对账范围（geoviz `las_preview.py` 只读 LAS；
WLE 的对应 io 面不迁移、不重写——见 gap-table.md 排除项）。
