# CONV-24 findings — factor_fusion + factor_units 核

## 切片范围

`paleo_workbench/workflow/factor_fusion.py`(790 行）+ `paleo_workbench/workflow/factor_units.py`(188 行）。

### 移植面

| Python 对象 | 语义 | 备注 |
|---|---|---|
| `Normalization` | kind∈{minmax,ramp} + finite low<high;`apply` = clip((v-low)/span,0,1) 仅作用于有限元 | ctor 校验 → `ValueError` |
| `FactorEvidence` | weight 必须 finite 且 >0;`to_dict` 携带 grid.source_refs/algorithm_id | |
| `FusionRule` | 有序 (factor,op,threshold) 三元组；op∈_RULE_OPS;threshold 必须 `isinstance(int,float)` 且 finite(bool 算 int——边缘) | ctor + `from_dict` 两路径校验文案不同 |
| `FusionModel` | kind∈{weighted_evidence,rule_based};weighted 需 evidences+class_names 且 thresholds=len-1 | `from_dict` 的 grids seam 是注入点 |
| `FusionModel.fingerprint` | sha256(json.dumps(to_dict, sort_keys=True, ensure_ascii=False, default=str))——**默认分隔符 ", "/": "**,与 conv-08 canonical_json 的紧凑分隔符不同 | 需带空格变体 |
| `_aligned_or_raise` | shape 一致 → `np.allclose` 轴一致(rtol=1e-5,atol=1e-8)→ CRS 纪律（声明/未声明混合拒绝，三种消息） | 返回首图声明 CRS 或 None |
| `_fuse_weighted` | 流式累加 w_sum/m_sum/w_sq;likelihood=m_sum/w_sum;confidence=coverage×agreement;conflict=disagree_weight/w_sum;margin=最近阈值距离；variance=Σ(w/w_sum)²·var(仅有方差的因子累加);class_grid=最高命中阈值类；qc 全套 | w_sum≤0 → 各面 nodata |
| `_fuse_rule_based` | 有序首匹配；applicable=~matched&finite&op;hits 按规则记；`{class_name: hits}` dict——同名 class_name 后者覆盖（边缘）;no_evidence 全因子非有限 | 0 evidences → `_aligned_or_raise([])` IndexError |
| `sensitivity_report` | LOFO:去掉一个因子重融合，比较分类变化率；单因子/非 weighted 特判 | `delta` 形参接受但未用（死参） |
| `_classify_grid` | weighted:阈值归类；rule:likelihood 即类码 | sensitivity 内部 |
| `_build_grid` | FactorGridResult 构造：algorithm_id="factor_fusion";source_refs=全证据 union sorted;名称模板加权 `"X 融合似然"/"X 融合置信度"/"融合方差"`、规则 `"X 融合分类"` | 输出 grid_z 经 float32 化，非有限→NaN |
| `factor_units` 全部 | FACTOR_DEFAULTS(91 条别名)/FACTOR_FAMILIES(6 族）+ normalize_factor_key(strip+lower)+ _folded_entry + unit/color_ramp 查询 + DERIVED_* 常量 + validate_factor_unit_against_values | `.3g` 格式化；`np.round`=half-even |

### 排除面

- `register_output`——catalog 服务缝（tempfile + write_grid_artifact + create_derived×3 + qc 回写），不进本切片。
- `FactorGridResult.contours`/`statistics`/`boundary` 等渲染面——fusion 不读写；`FactorGrid` 只携带 fusion 触及的字段。

## 关键语义细节（oracle 必须冻结）

1. **grid_z 存储为 float32**(`_to_float32_grid`，非有限→NaN)；融合数学全部在 `.astype(float)`=float64 上做；输出再收 float32。
2. **`_RULE_OPS["=="]`** = `np.isclose(v,t,rtol=1e-9,atol=1e-12)` → `|v-t| ≤ atol + rtol·|t|`。
3. **disagree 口径**:implied≥0 且 ≠fused_class 的可用权重占比；fused_class 在非有限处为 -1。
4. **qc 标量**:low_confidence`<0.3`、high_conflict`>0.5`、low_margin`<0.05` 占比；无有限元→`None`(JSON null)。
5. **`{lo:.3g}`** 与 printf `%.3g` 等价路径（3 有效位）。
6. **`np.round`** = round-half-**even**(`std::nearbyint`)。
7. **`np.allclose` 默认** rtol=1e-5、atol=1e-8（轴比较 + 整数化检查）。
8. **`rule_hits`** 以 class_name 为键——两规则同名时**后者覆盖**；冻结同名案例。
9. **`sensitivity_report` 重建 FusionModel 丢 `weight_provenance`**——frozen 指纹差异即证据。
10. **unit_warnings 两路**:percent 声明 + 0..1 归一化边界（`max(|low|,|high|)<=1.5`)；`validate_factor_unit_against_values` 三分支。
11. **weighted 名称模板**:似然=`{name} 融合似然`、置信=`{name} 融合置信度`、方差=`融合方差`(**无 name 前缀**)；规则= `{name} 融合分类`。
12. **`str(unit).strip()`** 后的 u 只在 `{"%","percent"}`/`{"1","v/v","fraction"}` 集合内判。
13. **`normalize_factor_key`** = `strip().lower()`(Unicode lower，需小写映射表，同 conv-22 先例）;falsy 输入→`""`。
14. **`_folded_entry`** 先精确再 folded 再族别名；族内代表按序取首个有 entry 的。
15. `factor_fusion` 顶部 `FUSION_GENERATOR_VERSION` 常量进 to_dict/provenance。

## C++ 载体设计

`pwb::factor_fusion::FactorGrid` —— FactorGridResult 运行时面（fusion 视角）:
`height/width` + `vector<float> grid_z`(row-major)+ `vector<double> grid_x/grid_y` + `optional<vector<float>> variance_grid` + `factor_name/algorithm_id` + `Json algorithm_parameters`（可写——likelihood 回写 class_thresholds/class_encoding)+ `optional<string> crs/unit/generator_version/run_ref` + `vector<string> source_refs`。

不复用 `FactorGridEnvelope`(conv-18)：那是 JSON 信封/编解码面，statistics/boundary/legacy 序列化包袱不属于运行时核；`FactorGrid` 保留 float32 语义自足。

## 依赖

`Pwb::Domain`(Json + Sha256::of_bytes)+ `Pwb::FactorHost`(`python_repr_double`——fingerprint 的浮点 repr)。CMake:`PWB_BUILD_CONV_24` 默认 OFF,imply CONV_08。
