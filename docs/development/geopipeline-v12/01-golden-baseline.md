# V12-B 黄金值基线（不可跳过的第一步）

**生成时间**：2026-09-13 · **BASE**：`926f3335`（origin/main）
**脚本**：`scripts/geopipeline_v12_golden.py` · **数据**：`tests/data/geopipeline_golden/`

```
python: 3.12.13   numpy: 2.5.3   BLAS: scipy-openblas (pip wheel)
platform: Linux-6.18.49-2-lts x86_64, glibc 2.44
venv: geopipeline-v12/.venv（无 geoviz → 克里金走 _pure_numpy_kriging 回退路径，
      即侦察实测的热点路径；IDW 走 cKDTree 路径）
```

## 数据集

固定种子（`BASE_SEED=20260913` + 尺寸偏移），场函数 = 线性趋势 + 双正弦结构 +
N(0, 0.8) 噪声，坐标域 [20, 980]²。全部由 `scripts/geopipeline_v12_golden.py`
的 `_samples/_dataset/_polygon_grid` 生成，跨机器可复现。

覆盖矩阵（25 案例）：

| 维度 | 取值 |
|---|---|
| 方法 | Kriging（spherical）/ IDW（power=2） |
| 样本数 | 50 / 500 / 2000 |
| 网格 | 50² / 200² / 300² |
| 边界多边形 | 无 / 8 点环（D6 域掩膜 → nodata 单元） |
| 各向异性声明 | 无 / angle=30, ratio=2.5（回退路径不消费 → 输出必须与未声明一致） |
| 井点级 nodata | 0% / 10%（NaN 值 → valid_points 过滤） |
| 多边形化场 | speckle（最坏场：洞×外环×顶点超线性）/ smooth（常规大网格） |
| 等值线场 | smooth 100/200/300（为下一轮统一化预置基线） |

## 基线墙钟（本机，单次运行；compare 输出带基线对照）

| 案例 | 耗时 | 案例 | 耗时 |
|---|---|---|---|
| krig_n50_g50 | 0.426s | idw_n50_g50 | 0.002s |
| krig_n500_g50 | 0.557s | idw_n500_g50 | 0.016s |
| krig_n2000_g50 | **1.032s** | idw_n2000_g50 | **0.061s** |
| krig_n500_g200 | 1.621s | idw_n500_g200 | 0.300s |
| krig_n500_g300 | 3.143s | idw_n500_g300 | 0.567s |
| krig_n50_g300 | 0.337s | idw_n50_g300 | 0.061s |
| krig_n500_g50_boundary | 0.702s | idw_n500_g50_boundary | 0.020s |
| krig_n500_g50_aniso_declared | 0.731s（== 未声明案例，回退路径确不读各向异性） | | |
| krig_n500_g50_nodata | 0.466s | idw_n500_g50_nodata | 0.025s |
| poly_speckle_50 | 0.370s | poly_smooth_200 | 0.043s |
| poly_speckle_100 | 1.541s | poly_smooth_300 | 0.080s |
| poly_speckle_150 | **2.979s** | | |
| contour_smooth_100 | 0.088s | contour_smooth_200 | 0.218s |
| contour_smooth_300 | **0.626s** | | |

独立复测（同机、直接调用，非黄金脚本）：

- 克里金 N=2000/100² 全局路径 cProfile：总 2.42s，其中 2001² 的
  `np.linalg.solve` 0.85s、逐块协方差求值 ~1.1s——**O(N³) 分解 + O(M·N²)
  求值**是结构性成本，随 N 立方增长（侦察环境同结构为 27.6s）。
- 多边形化 speckle 噪声（单类阈值化，最坏形态）：50²→0.17s、100²→2.35s、
  150²→**9.98s**（面积 ×2.25，耗时 ×4.25，超线性确认；侦察环境同结构
  为 24.2s）。黄金值脚本用三分类默认阈值，绝对值更低（3.0s@150²）但
  同样超线性（0.37→1.54→2.98，×4.16/×1.93）。

## 比对策略（已实现于脚本）

- 默认路径输出**字节级一致**（IDW/多边形/等值线/克里金参数标量）；
  克里金网格容差 max|Δ| ≤ 1e-5（论证见 00-decisions.md D5）。
- 每个产物记录 SHA-256 于 `manifest.json`；`compare` 子命令重算并输出
  OK/FAIL + 差异量级诊断 + 提速倍数。

## BLAS 末位噪声的复现记录（容差依据）

`krig_n2000_g50` 在 generate 与 compare 两个进程间出现 max|Δ|=4.77e-07
（float32 存储）差异；同进程重复运行、以及"单案例跨进程"均字节一致。
定位：线程化 OpenBLAS 对大矩阵按缓冲区对齐/分块选择内核，进程历史（此前
的分配）改变后续矩阵的堆对齐 → 末位归约次序不同。这不是代码非确定性
（纯 numpy 路径与 IDW 全部字节稳定），而是平台 BLAS 的已知行为，故克里金
网格采用论证容差而非字节闸门。

## 复现命令

```bash
cd <worktree>
.venv/bin/python scripts/geopipeline_v12_golden.py generate --out tests/data/geopipeline_golden
.venv/bin/python scripts/geopipeline_v12_golden.py compare --against tests/data/geopipeline_golden
```

## 环境敏感性事件（2026-09-13，验证期发现）

为尝试收集 m6 对抗套件临时安装的 matplotlib 使 editable 安装指向的
`geoviz_plots`（位于 main worktree 的 geo-viz-engine 检出）导入成功 →
`KrigingInterpolator` 默认路径从 numpy 回退翻转到 geoviz 引擎 → 黄金值
比对 9 个克里金案例 FAIL（max|Δ| ~1.0——两条完全不同的实现路径）。

处置（两层）：

1. 卸载偏离规格的包（matplotlib/pyproj/pyqtgraph/segyio 均非 dev extras
   成员），恢复声明的最小环境；
2. **黄金值脚本显式钉死回退路径**（`sys.modules.setdefault("geoviz", None)`）：
   geoviz 可导入性是环境属性而非代码属性，不钉死则被钉对象会随环境漂移。

该事件是"先建黄金值基线"的直接价值证明：环境级翻转被字节级闸门当场
捕获，而非混进性能数字里被合理化。
