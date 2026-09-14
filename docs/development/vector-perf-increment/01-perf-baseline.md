# 01 — 性能基线实测（Phase 1，优化前）

**测量环境**：Windows 11 / Git Bash / 项目 `.venv`（uv cpython 3.12）/
vendored-QGIS 桥 0.7.0a0（worktree 自建 .pyd，链接主仓 2026-09-14 14:09
vendor 构建）/ `QT_QPA_PLATFORM=offscreen`。

**方法**：真实生产代码路径（无 mock）；`time.perf_counter`；重复采样取
中位数（snap 15 次、topo/render 3–12 次）。测量脚本：
`tests/perf/test_vector_perf_baseline.py`（`pytest -s -m "qgis or slow"`），
本文件所有数字可在同一命令下复现。单机单轮，量级用于定序与验收对比。

## B1 吸附拾取（snap）— 真手势 press（当前层档，miss-only press）

| 规模 | press 中位 | min | max | 备注 |
|---|---|---|---|---|
| 1,000 顶点（200 面） | **0.132 ms** | 0.126 | 0.682 | 线性扫描 C++ 侧 |
| 10,000 顶点（2,000 面） | **1.09 ms** | 0.963 | 1.833 | |
| 20,000 / 50,000 | — 崩溃（既有 vendor 回归，见 00-D8） | | | |

解读：当前层单层 scope 的 C++ 线性扫描 ≈ 0.11 ms/千顶点——20k 规模外推
≈2.2 ms、50k ≈5.5 ms，**已经接近但仍超 <1 ms SLA**；且 discoverAllLayers
（全层档）对每个候选层各扫两遍（锚点拾取 + 1e-8 并集），多候选层场景
成倍恶化。微基准（Ticket 1 落地 `vertex_pick_bench` 绑定后）将给出
20k/50k 与多层场景的精确分解。

（`press_floor_5vert`：5 顶点空层 press 地板 ≈0.13 ms——即 1k 规模的
计时几乎全是扫描成本。）

## B2 拓扑校验（topo）— 桥 `run_geometry_checks` 全量扫描

规则集 `is_valid+overlap+dangle`，网格平铺面（无错误负载的健康数据）：

| 规模 | 全量扫描中位 | 节点移动后复检中位 | SLA（<35 ms） |
|---|---|---|---|
| 1,000 顶点（200 面） | 7.4 ms | 10.3 ms | 已达 |
| 10,000 顶点（2,000 面） | **179.5 ms** | 180.6 ms | 差 5.2× |
| 50,000 顶点（10,000 面） | **4,029 ms** | 3,920 ms | 差 115× |

现状确认：**每次复检都是完整重扫**（post_move ≈ full_scan），无任何增量
通道。50k 规模一次校验 4 秒，正是"编辑一顶点、停顿一呼吸"的停顿源。
（提示词假设的 300–1200 ms 在 10k–50k 之间；实测两端更极端。）

## B3 渲染（render）— 回退 QPainter 相带花纹层（800×600）

 categorized 多边形 + `fill_patterns`（delta/sand 两花纹）：

| 规模 | 首帧（含懒烘焙） | 缩放扫中位（12 帧） | 平移扫中位 | 等效 FPS |
|---|---|---|---|---|
| 1,000 顶点（200 面） | 23.2 ms | 15.1 ms | 8.3 ms | 66 / 121 |
| 10,000 顶点（2,000 面） | 52.7 ms | 28.8 ms | 29.8 ms | 35 / 34 |
| 50,000 顶点（10,000 面） | 221.6 ms | **158.7 ms** | **89.6 ms** | **6.3 / 11** |

SLA（<16 ms、60 FPS）在 2k 面时已破（~29 ms），10k 面时差 10 倍。
首帧烘焙（QSvgRenderer 逐张）在 50k 规模 0.22 s，是缩放第一帧尖刺。

## B4 FFI / JSON 通道（ffi）

| 项 | 实测 | 备注 |
|---|---|---|
| `json.loads` 事件解码 ×10,000 | 67.7 ms（6.8 µs/次） | edit_gesture 量级载荷 |
| 同上 + tracemalloc 追踪 | 614.9 ms，peak 4 KB | 追踪开销本身 9× |
| GC 停顿（10k 次循环） | 0 次 / 0 ms | 本机 Python 3.12 该负载不触发 |
| 镜像 delta 发布（1/10,000 变更，Python 侧） | **153.1 ms** | `_feature_signature` 逐要素 json.dumps 主导 |
| delta 编码（100 变更要素 json.dumps） | 0.55 ms | |
| delta 经 upsert 应用（100/10,000，桥侧） | **344.3 ms** | QJsonDocument 解析 + 删重加 |
| 读回拉取（10,000 要素，桥序列化） | **265.2 ms** | `mirror_features_json` |
| 读回解析（10,000 要素 json.loads） | 41.6 ms | |

现状确认：**跨语言通道全部为 JSON 字符串拼装/解析**；单要素级发布
（153 ms）与 100 要素级应用（344 ms）在 10k 图层上都是硬卡顿源。

## 汇总：SLA 缺口排序

| 维度 | SLA | 现状（本机实测代表值） | 缺口 |
|---|---|---|---|
| 万级顶点吸附拾取 | <1 ms | 1.09 ms @10k（单层，外推 5.5 ms @50k；多层成倍） | 1–5×+ |
| 节点移动后拓扑验证 | <35 ms | 180.6 ms @10k / 3,920 ms @50k | 5–115× |
| 花纹缩放重绘 | <16 ms（60 FPS） | 28.8 ms @2k 面 / 158.7 ms @10k 面 | 2–10× |
| FFI 序列化抖动 | 0 分配/0 GC | 全 JSON；153 ms 单要素发布 | 架构级 |

## 复现命令

```bash
cd ../paleo-workbench-vector-perf
export PALEO_QGIS_BUILD_DIR="$PWD/../paleo-workbench/native/qgis_render_bridge/build/qgis-vendor"
export PYTHONPATH="$PWD/native/qgis_render_bridge"
export QT_QPA_PLATFORM=offscreen
../paleo-workbench/.venv/Scripts/python.exe -m pytest tests/perf/test_vector_perf_baseline.py -s -q
```
