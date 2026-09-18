# CONV-24 decisions — factor_fusion + factor_units

## D1 范围：数值核全量，`register_output` 除外

`register_output` 是 catalog 写入缝（临时目录 + `write_grid_artifact` + 三次 `create_derived` + qc 回写），按"纯核先行"原则排除；其余全部移植（Normalization/FactorEvidence/FusionRule/FusionModel/FusionResult/fuse/sensitivity_report/_aligned_or_raise/_build_grid/_classify_grid + factor_units 全模块）。

## D2 `FactorGrid` 载体独立定义，不复用 FactorGridEnvelope

conv-18 的 `FactorGridEnvelope` 是 JSON 信封面（legacy 序列化、statistics、boundary 契约）;fusion 需要的是运行时对象（float32 grid_z + float64 轴 + 可变 algorithm_parameters + source_refs)。`pwb::factor_fusion::FactorGrid` 按 fusion 触及的字段精确定义，grid_z/variance 保 `float`(float32 语义），轴保 `double`——与 `_to_float32_grid` 合同一致，非有限→NaN。

## D3 fingerprint 需", "分隔符变体

`FusionModel.fingerprint` 用 `json.dumps(sort_keys=True, ensure_ascii=False, default=str)`——Python 默认分隔符是 `", "`/`": "`,conv-08 的 `canonical_encode` 是紧凑 `,`/`:`。不复用；本库内实现 `python_dumps_sorted`（同逃逸规则、键按 UTF-8 字节序排序、浮点走 `python_repr_double`),sha256 走 `Sha256::of_bytes`。冻结指纹十六进制串直接对账。

## D4 numpy 语义的 C++ 落点

| numpy | C++ |
|---|---|
| `np.isclose(a,b,rtol,atol)` | `|a-b| <= atol + rtol*|b|` |
| `np.allclose` 默认 | rtol=1e-5, atol=1e-8 |
| `np.round` | `std::nearbyint`(half-even) |
| `np.clip` | `std::clamp` |
| `float32` 化 | `static_cast<float>` 后非有限→quiet_NaN |
| 求和 | 按证据序顺序累加（冻结规模 << 128,pairwise 无分歧） |
| `0/0` → NaN | 显式 `w_sum<=0` 分支（与 Python 一致） |

## D5 grids seam 显式化

`FusionModel::from_dict(data, grids)` 的 `grids` 是运行时网格注入点——C++ 签名 `from_dict(const Json&, const std::map<std::string,FactorGrid>&)`;dict 里的证据**必须**有对应网格否则 ValueError（原文案）。`to_dict` 只读 grid.source_refs/algorithm_id——与 Python 相同，网格数据永不序列化。

## D6 错误类型

模块只抛 `ValueError`(+ `_aligned_or_raise([])` 的 IndexError 边界、`StopIteration` 不可达——`_aligned_or_raise` 先炸）。`pwb::factor_fusion::ValueError`/`IndexError` 两类型,`python_class()` 对账。`from_dict` 的 `float(c[2])` 失败按 ValueError 冻结（生成器决定真实类别）。

## D7 factor_units 表生成式冻结

`FACTOR_DEFAULTS`(91 条）/`FACTOR_FAMILIES`(6 族）由生成器从真 Python dict 吐 `factor_units_data.inc`（与 modules_data.inc 先例一致）;`normalize_factor_key` 的 `.lower()` 走生成器产出的 `lower_map.inc` 窄字符串表（conv-22 先例，只含 lower≠identity 的码点）。

## D8 测试覆盖约定

oracle fn 分派：normalization_ctor/apply、rule_ctor/from_dict、model_ctor/to_dict/from_dict/fingerprint、fuse(weighted+rule 全路）、aligned_or_raise、sensitivity、unit_for_factor/color_ramp/normalize_key/validate_unit。案例含：全 NaN、部分 NaN、方差有/无/混合、CRS 三态、单位警告两支、规则同名覆盖、单因子 LOFO、错误文案全量。
