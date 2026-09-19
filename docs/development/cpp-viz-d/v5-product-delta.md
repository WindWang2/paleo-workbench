# VIZ-D — 地震高级 2D 显示与呈现差量（CONV-VIZ V5 产品路径）

基线：`origin/main` f0af9d4e；冻结 oracle：`geo-viz-engine@08851951` + `native/seismic_3d_core@0.2.17a0`。
伴生审计：[r6a-audit.md](r6a-audit.md)（R6a 基础件审计门）。

## 交付面（Python 源 → C++ 落点）

| Python 源（LOC） | C++ 落点 | 说明 |
|---|---|---|
| profile_vd.py 归一/极性/缓存 (1259) | `seismic_viewer/display_core.{hpp,cpp}` + `seismic_slice_widget` percentile 路径 | 非对称 P(100-p)..P(p) 裁剪（numpy 'linear' float32 插值 parity）、显示级极性（原范围归一化取反面）、NaN→LUT 中心 128（#119）、per-(volume,axis) 裁剪缓存跨兄弟面复用、all-NaN/常量退化语义 |
| profile_wiggle.py (290) | `display_core::wiggle_geometry` + `SliceCanvas` wiggle 绘制 | 全局 amax 归一（float32 除法后加宽）、增益默认 2.0、正瓣黑填充 α200 + 过零插值、灰基线/深折线笔、视口抽取（≤1 样本/像素 + 末样本闭合）、视图适配渲染（源无缩放语义）、polarity 显示级 |
| colormap.py (358) | `seismic_viewer/color_maps.cpp` | seismic 5 停靠点（Petrel 风格，np.interp 斜率式 + uint8 截断 + linspace 舍入路径 parity）、seismic_r/gray/jet/hsv/viridis/phase_wheel 新增；grayscale/heat 保留（超集） |
| horizon.py (243) | `seismic_viewer/horizon_core.{hpp,cpp}` | parse（regex 数值刮取/偏移/缩放/重复后写/未匹配告警）、fill_nearest（整数平方距离精确 EDT + scipy 平局规则 min(\|Δrow\|,row,col)）、fill_rbf（scipy linear 核 **φ(r)=-r**、degree-0 常数项、k 近邻、smoothing 对角）、extract_along_horizon（int32 截断+裁剪、窗口 RMS、NaN 传播）、horizon_quad_faces |
| 拾取/编辑/持久化（seismic_view.py 2265-2338） | `horizon_core` HorizonPickSet + `seismic_slice_widget` 拾取交互 | 追加 Python 所缺的**稳定源绑定**（volume_id+revision+axis+slice_index+time_unit+schema 版本）；JSON 严格编解码（fail-closed）+ CSV parity（inline,crossline,time_ms @ %.1f）；点击添加/拖拽编辑/右键删除/清空；视图切换重投影 |
| crossplot.py (56) + dialogs/crossplot.py (131) | `seismic_viewer/crossplot_core.{hpp,cpp}` | GR/AI 岩性统计（总体 std、Unknown 回退、首见分组序）；属性散点（瞬时频率 vs 包络）**复用** `seismic_attributes` 冻结核（science SDK 调用，不重写 Hilbert）；numpy flatten 顺序 + step=max(1,size//5000) 子采样 + P1/P99 轴限 + hi=lo+1 退化保护 |
| colorbar_widget.py (51) | `seismic_viewer/colorbar_widget.{hpp,cpp}` | 60px 固定宽、LUT 渐变（底=最小）、%.1f min/mid/max 标注；随 colormap/显示范围同步 |
| isosurface.py (26) + native marching_cubes_3d | `seismic_viewer/isosurface_core.{hpp,cpp}` | marching tetrahedra 逐行移植（同一冻结算法）；isosurface 值精确对账；geo3d_viz SceneObject{verts,faces,Mesh} 可直接消费（不重写网格引擎，3D 呈现归 C 线） |
| PreviewKind 闭合 | `ui_pages_preview`（viz_d 专用文件） | seismic_2d：`SeismicPreviewPresenter`（SliceController 异步 + 世代守卫，E 接入缝）；xy_scatter：`well_head_scatter_core`（_well_head_payload 全语义移植，12 案例 oracle 对账）；formation_tops：真实解析表呈现（消费方为编图管线，声明 Lithology 条带呈现不在预览） |
| R6a 缺口 A1/A2/A3 | `display_core::sample_polyline_slice`；`slice_controller` prefetch；`SeismicPreviewPresenter` | 见 r6a-audit.md |

## 显示语义对账与声明容差

- **精确**（逐字节/逐值）：colormap LUT、percentile 裁剪范围（float32 插值）、normalize_to_index 索引、视口抽取、wiggle 几何（真实 paintEvent 捕获，1e-9）、horizon parse/fill_nearest/quad_faces、isosurface（同算法位精确）、lithology 统计（1e-12）、wellhead payload。
- **声明容差**：polyline 采样（scipy 内部 float64 stencil 差，1e-5；距离 f32 回传 1e-7）；fill_rbf（LU vs lstsq，1e-6）；extract 窗口 RMS（求和序，1e-4）；属性散点（核自身容差链，2e-3）。
- **有意保留的 v3 冻结行为**（不破坏既有契约）：默认自动拉伸仍为有限 min/max（percentile 模式一键开启）；v3 路径 NaN→index 0（percentile 路径才走 128）；缩放钳制 [1.0,64.0]（Python 数据窗模型 [1/32,4] 未迁，声明）；wiggle 无缩放（源语义）。
- **fill_rbf 邻居集范围**：fixture 均为"全部有效节点 ≤ neighbors"（无 KDTree 平局歧义）；有效节点 > neighbors 时等距邻居集合可能与 scipy 不同（值级 parity 不保证，声明）。

## 审核后修正与声明偏差（三轮独立审核，2026-09-19）

- polyline 坐标按 gpu_ops 语义量化到 float32（大测线坐标下插值权重 parity 关键；large_coords fixture 证明）。
- normalize_to_index 全链 float32（colormap.py dtype 链；截断边界一致）。
- 常量面：profile_vd 提前返回纯零索引（NaN 也为 0）；全 NaN 面：有限→0/NaN→中心（NaN 范围**不缓存**——有意偏离 Python 的兄弟面毒化行为，下一好面即恢复；声明）。
- fill_nearest 平局规则为确定性 min(|Δrow|, row, col)；scipy EDT 的平局解析次序在随机网格上不保证一致（值级平局 parity 声明出范围；fixture 平局均恰好一致）。
- horizon 数值刮取对 `1.e3`（→1）与尾点（`100.5.`→100.5）语义与 _NUM_RE 完全一致（exponent_and_trailing_dot fixture）。
- MiniJson 深度上限 64（敌意嵌套 fail-closed）；u64/i64/dt_ms 转换范围守卫。
- 构建接线：root 级 PWB_BUILD_SEISMIC_VIEWER 蕴含 PWB_BUILD_SEISMIC_ATTRIBUTES（同 service→io 先例）；app 的 viz_d_seismic_install.cpp 仅在 viewer 目标存在时编译；viz_d 测试自带 Qt6::Widgets find_package（精简配置可用）。

## 明确排除（既有能力，未重复实现）

tile cache/SEG-Y 读取/切片调度（seismic_io+SliceController）、属性核（seismic_attributes 10 核）、#1394 控件面（ui_wellseis 经 `viz_d_seismic_binding` 适配到真 viewer）、通用 chart 轴/图例（E 线）、任意线 3D curtain/well-tie/3D 体渲染（C/B 线范围）。

## 遗留（如实）

- 面板级 2D 属性/RGB 融合显示、slice 导出 npy/csv/png、seismic 视图态持久化、LOD 金字塔、GPU 路径：未迁（见 r6a-audit.md 裁决）。
- 预览页全局装配依赖 P-A（E 线）；ui_wellseis 绑定适配器为 lib 级（面板未挂主程序）。
- fill_rbf 大网格（有效节点 > neighbors）的邻居集语义差异如上声明。
