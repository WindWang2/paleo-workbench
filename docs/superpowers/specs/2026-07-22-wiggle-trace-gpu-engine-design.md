# 高密度地震波形道 (Wiggle Trace) GPU Instancing 绘制引擎设计规范

日期：2026-07-22
状态：已确认 (经用户 /grill-with-docs 深度访谈闭环)
落点：`geo-viz-engine/packages/geoviz_seismic` & `paleo_workbench/viz`
关联：`docs/superpowers/specs/2026-07-21-viz-perf-hardening-design.md`

---

## 1. 背景与目标

在石油地质与地球物理资料解释中，波形道 (Wiggle Trace) 是 SEG-Y 地震剖面的核心展示形式。当处理超大规模 2D 剖面（如 50,000 地震道 $\times$ 4,000 采样点 = 2 亿数据点）时，传统 CPU 绘制多边形/折线的方式会导致 CPU/PySide6 主线程极其卡顿，且产生严重内存膨胀。

本规范定义了基于 PyOpenGL / GLSL 着色器的 **GPU Instancing 波形道绘制引擎**，旨在实现：
1. **超高密度渲染**：支持视口内 50,000+ 道地震数据，60 FPS 顺畅平移与缩放。
2. **0ms 增益与截断控制**：在 Shader 中通过 Uniform 实时调节摆幅增益 ($u\_gain$) 与重叠截断上限 ($u\_clip\_limit$)。
3. **4 种全功能显示模式**：Wiggle Only、Wiggle + Positive Fill、Wiggle + Dual Fill (Variable Area) 以及 Overlaid Wiggle + VD。
4. **屏幕空间自适应 LOD**：道密 $<2\text{px}$/道 时无缝切为 VD 变密度彩图防混叠；$\ge 3\text{px}$/道 时展示完整波形。
5. **视口自适应矢量导出**：$< 500$ 道导出纯 SVG/PDF 矢量 `<polygon>`/`<polyline>`；$\ge 500$ 道高 DPI 离屏嵌入。

---

## 2. 架构设计与 GPU 管线

### 2.1 显存数据组织 (`GL_R32F` 2D Texture)
- 切片数据一次性上传至 GPU VRAM，作为 2D 浮点纹理 `GL_R32F`（Width = 采样点数 $N_{samples}$，Height = 道数 $N_{traces}$）。
- 增益、截断、颜色映射与模式切换全在 Shader 中处理，不发生帧间 CPU/GPU 内存传输。

### 2.2 Vertex Shader Instancing
- 使用 `glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, N_samples * 2, N_traces)` 绘制波形带。
- 通过 `gl_InstanceID` 索引地震道，通过 `gl_VertexID` 采样振幅。
- 坐标变换公式：
  $$x = \text{base\_x}(\text{gl\_InstanceID}) + \text{clamp}(\text{amplitude} \times u\_gain, -u\_clip, u\_clip)$$

### 2.3 Fragment Shader 模式渲染
- **Mode A (Wiggle Only)**：仅绘制边界波形线。
- **Mode B (Positive Fill)**：填充 $\text{amplitude} > 0$ 区域（默认黑色/单色）。
- **Mode C (Dual Fill)**：$\text{amplitude} > 0$ 填充 Color A（如红色），$\text{amplitude} < 0$ 填充 Color B（如蓝色）。
- **Mode D (Overlaid Wiggle + VD)**：背景根据 1D LUT 纹理渲染 VD 变密度彩图，前景叠置 Wiggle 波形线。

---

## 3. 组件接口契约

在 `geoviz_seismic/renderer/wiggle_instanced.py` 中导出 `WiggleTraceRenderer`：

```python
class WiggleTraceRenderer:
    def set_data(self, volume_slice: np.ndarray) -> None:
        """上传 2D 剖面切片 (Traces x Samples) 到 GPU R32F 纹理."""
        ...

    def set_display_mode(self, mode: str) -> None:
        """设置模式: 'wiggle', 'positive_fill', 'dual_fill', 'overlaid_vd'."""
        ...

    def set_gain(self, gain: float) -> None:
        """0ms 实时调节增益倍数 (uniform u_gain)."""
        ...

    def set_clip_limit(self, clip: float) -> None:
        """0ms 实时调节波幅重叠截断上限 (uniform u_clip_limit)."""
        ...

    def set_colormap(self, lut_256: np.ndarray) -> None:
        """更新 1D 256x1 RGBA LUT 着色表."""
        ...

    def render_export(self, dpi: int = 300) -> bytes:
        """高 DPI 离屏栅格化导出 (用于 >= 500 道矢量导出嵌入)."""
        ...
```

---

## 4. 测试与验证策略

1. **Shader 参数与模式分发单测 (`tests/test_wiggle_instanced.py`)**：
   - 验证 4 种显示模式枚举切换正确性。
   - 验证 $u\_gain$ 与 $u\_clip\_limit$ 边界值防护（非负、非 NaN）。
   - 验证屏幕空间自适应 LOD 阈值（$<2\text{px}$ 自动触发 VD 切态）。
2. **矢量导出自适应阈值测试**：
   - 验证 $< 500$ 道触发纯矢量节点输出。
   - 验证 $\ge 500$ 道触发 High-DPI 离屏嵌入。
3. **全库回归验证**：
   - 确保 `pytest` 全量测试套件 100% 保持绿色。
