---
status: accepted
---

# CustomPolyline 虚线模式与 CustomQuad 图案填充

CustomPolyline 增加 `dash_pattern`(显式线段数组),CustomQuad 增加 `pattern_id`(复用 PatternDefinition)。二者均与 Interval 已有能力对齐,使油藏剖面(fault/contact/tie)按中国行业标准表达虚线断层、点线接触和填充岩性。

## 背景

Phase-2 PR-C3 (T4) 实现了油藏剖面几何(`section_geometry/{fault_2d,contact_2d,tie_polygons}.py`),但 T4 决议明确 defer 了线型和填充:

- `CustomPolyline` 只有 `color` + `width`(实线)
- `CustomQuad` 只有 `fill_color`(纯色)
- T4 注释:"no dash pattern (engine CustomPolyline has color + width only)"

中国油藏剖面标准要求虚线断层、点线/点划线接触、岩性图案填充(砂岩/泥岩/灰岩等)。当前实线+纯色无法表达这些约定。

ADR 0018/0046 定义了声明式 Custom Layer;ADR 0020 定义了 PatternDefinition 作为图案的唯一矢量真值来源;Interval 已通过 `pattern_id` 引用 PatternDefinition。本 ADR 将相同能力扩展到 CustomPolyline(线型)和 CustomQuad(填充)。

## 决策

### dash_pattern 数据模型

`CustomPolyline` 增加可选 `DashPattern`:

```cpp
struct DashPattern {
  std::vector<Millimetres> segments;  // 交替 [on, off, on, off...] 场景毫米
  double offset{};                     // 起始偏移(沿线方向)
};
```

- `segments` 为空 = 实线(向后兼容默认值)
- 与 SVG `stroke-dasharray` / PDF line dash array 一一对应,矢量导出无损
- 单位为场景毫米,与 `width` 一致,物理尺度正确

_Avoid_: 枚举预设(solid/dashed/dotted)——表达力不足,无法表达一点链线 vs 两点链线等行业标准线型;原始字符串——无类型安全且泄漏 SVG 语法进内核。

### CustomQuad pattern_id

`CustomQuad` 增加 `EntityId pattern_id`(默认 nil = 纯色填充),复用 Interval 已有的 PatternDefinition 查找机制(`ScenePresentation::patterns()` + `add_pattern()`)。不引入新的图案体系。

### GL 渲染

- **dash**: CPU 切割——沿线段方向按 dash segments 计算实际绘制子段,只生成 "on" 部分的 quad ribbon。不改 shader,与现有 quad ribbon 管线完全一致。
- **pattern**: 复用 Interval 的 `PrimitiveKind::pattern` batch path(pattern atlas + UV 映射),CustomQuad 与 Interval 共享同一纹理图集。

### Manifest 序列化

`dash_pattern` 和 `pattern_id` 作为**可选 JSON 字段**写入 manifest。旧 manifest(无这些字段)读取时默认实线/纯色。`manifest_schema_version` 保持 2(加法式,向后兼容),无升级迁移。

### Host 接线

`section_geometry/{fault_2d,contact_2d,tie_polygons}.py` 的 dataclass 增加对应字段:
- `FaultSegment2D.dash_pattern`(默认虚线,中国标准断层线型)
- `ContactSegment2D.dash_pattern`(默认点线,接触面线型)
- `TiePolygon.pattern_id`(可选,引用注册的岩性 PatternDefinition)

`section_canvas.py` 将这些传递给引擎 CustomPolyline/CustomQuad。

## 后果

- **向后兼容**:空 dash_pattern / nil pattern_id = 当前行为(实线/纯色),旧 manifest 和旧 host 代码不受影响。
- **端到端传播面大**:document.hpp struct → scene prepare (PreparedCustomPrimitive) → GL/SVG/PDF/picking → manifest → host dataclass → host canvas。每层都需改动。
- **PatternDefinition 复用**:CustomQuad 与 Interval 共享 PatternDefinition 注册和 GL atlas,不重复造图案基础设施。
- **CPU dash 的局限**:极端短线段 + 高频 dash 可能产生过多微型 quad。若成为性能问题,后续可加最小段长合并(geometric LOD)。
