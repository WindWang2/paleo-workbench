# 01 — 基线量化（BASE `926f3335`，改动前）

- 脚本：`docs/development/render-increment-v12/bench_baseline.py`（独立脚本，非 pytest）。
- 运行环境：Linux / CPython 3.12.13 / `QT_QPA_PLATFORM=offscreen`；
  依赖取自 **BASE 检出 + 其配套 venv**（`main/` 干净于 BASE，editable 安装指向
  该检出——量得的就是 BASE 行为）。native/bridge 路径用本机预构建 `.so`
  （cpython-312，与 BASE 同检出构建）。
- 每项均含「无收益即跳过」判定（goal §4.1）。

## 1. 标量栅格每帧绘制（平移序列 30 帧，帧缓存按设计失效）

网格 600×450（RGBA 1.03 MiB/幅），输出 900×675：

| payload | median ms/帧 | p90 ms | rasterize 调用/帧 | 拷贝 MB/帧 |
|---|---|---|---|---|
| 纯 Python `_ScalarPayload`（生产 GUI 路径） | **15.52** | 16.41 | 1.0 | **2.06** |
| native `grid_render_core.ScalarGridLayer` | 1.15 | 1.36 | 1.0 | **2.06** |

拷贝构成：`rasterize()` 产出的全新 numpy 缓冲（1.03 MiB；native 侧为 C++→Py
memcpy，纯 Python 侧为全量 LUT 重算）+ `QImage(...).copy()`（1.03 MiB）。
滚轮/平移每帧都付这笔钱；**收益判定：有，做**（方案见 00-D2）。

## 2. `_prepared_layer` 重复调用（无数据变化）

1500 个 32 顶点多边形：

| 首次（miss） | 重复（hit） | hits | misses |
|---|---|---|---|
| 21.07 ms | **0.17 µs** | 200 | 1 |

**结论：提示词 §3.2「_PreparedLayer 没有任何缓存」在 BASE 上不成立**——
`_prepared` 字典 + `revision` 校验 + 命中计数 + `seen_layers` 剪除均已存在
（map_render_backend.py:661, :1093-1126, :1021-1027），「未变图层零重建」已是
现状。**收益判定：实现无收益，跳过重写**；本 Goal 改为补齐 §3.4 失效矩阵中
缺失的测试（含反向对照），并把该缓存并入公共缓存类（§D3，属一致性而非性能）。

## 3. `topology.validate_records` 随要素数扩展

记录集：90% 有效多边形 + 10% 自相交（bow-tie）：

| 模式 | 50 条 | 200 条 | 1000 条 | 桥 validate 调用数 |
|---|---|---|---|---|
| fake 桥（计数） | 15.31 ms* | 0.82 ms | 3.36 ms | **50 / 200 / 1000（=N）** |
| 真桥（GEOS，本机预构建） | 140.65 ms* | 3.98 ms | 21.61 ms | N（按构造） |
| 无桥（Shapely 回退） | 138.25 ms* | 4.19 ms | 20.01 ms | —（纯 Python） |

\* 首行含引擎一次性加载（真桥冷加载实测 ~496 ms，页缓存热后 ~140 ms）。

- **跨语言往返 = N 已实测**（fake 精确计数）。
- 稳态单要素 ~20 µs（真桥 GEOS 与 Shapely 同量级）——往返次数是主要结构问题，
  与提示词判断一致。**收益判定：有，做**（批量接口 + 探针 + 回退，00-D4）。
- 注意：BASE 真桥 `geometry` 无 `validate_many`（实测 `hasattr=False`）；故本机
  真桥路径在 Goal 之后仍是逐要素回退——批量化收益在提供批量签名的桥上兑现，
  fake 桥测试给出 N→1 的调用数证据（Known limitations 如实声明）。

## 4. 无收益/跳过项汇总

| 项 | 判定 | 依据 |
|---|---|---|
| 重写 `_PreparedLayer` 缓存 | **跳过**（已存在） | §2：hit 0.17 µs，misses 仅首触 |
| `_reprojected` 增量 | 不动（本已按 (rev,src,dst) 增量） | 侦察 + 代码 :1047-1091；仅并入公共类 |
| 帧缓存/剔除/LOD | 不动 | `test_fallback_render_incremental` 已钉（#391） |
| 镜像发布（qgis_mirror 主路径） | 不动（V11 已增量） | 提示词 §3.2 自认「镜像侧已解决」；仅迁移缓存容器 + 修 reset 死代码 |
