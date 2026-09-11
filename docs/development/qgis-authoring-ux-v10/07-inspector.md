# 07 — Inspector 上下文化（M11）

## seam 数据源扩展（`layer_domain_status`）

原有四行（角色/成熟度/可编辑/新鲜度）基础上追加：

* **几何**（点/线/面/未知）；**CRS**（声明值或「未声明」）；
* **编辑**（编辑中 · 未保存 / 编辑中）；**已选**（N 个要素，>0 时）；
* **推荐动作**（活动图层）：preferred 捕获工具 →「添加线（推荐捕获
  工具）」；否则 toggle_editing 结论（禁用带 evaluator 判词）——V8 08 #9
  的 Inspector action-hint 闭环。

检查器仍然零业务判断：seam dict {行名: 值} 由宿主（CompositeDocument）
派生，全部来自既有权威。

## 其他保持

* 样式页 `edit_style_button` 可见性规则（payload kind）不变（呈现层）。
* factor raster / MapProduct 分节（V7 §8）不变。
