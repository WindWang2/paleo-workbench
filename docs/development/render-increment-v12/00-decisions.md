# 00 — 决策记录（V12-C 渲染/镜像增量通道）

- **BASE SHA**: `926f33354d17bb481cddc52c4f221160482e191a`（origin/main，已核实一致）
- **分支**: `feat/render-increment-v12`
- **Worktree**: `本机为 Linux；仓库为 bare（`.bare`）+ worktree 布局，故 worktree 建在
  `.worktrees/render-v12`（提示词中的 Windows 路径按本机实情适配：`.venv/bin/python`、
  `gh` 直接可用、coreutils 齐全）。
- **Python**: 3.12.13（uv 管理解释器，与 `main/.venv` 同源；桥 `.so` 为 cpython-312 ABI）。

## D0. 环境适配（与提示词的差异，逐条记录）

| 提示词假设 | 本机实情 | 决策 |
|---|---|---|
| Windows/GitBash，`/c/Users/wangj.KEVIN/...` | Linux，bare+worktree 布局 | worktree 置于 `.worktrees/render-v12`；PR 用本机 `gh` |
| `.venv/Scripts/python.exe` | `.venv/bin/python` | 等价替换 |
| coreutils 可能缺失 | 齐全 | 无需规避 |
| 桥不可用，全部验证走 Fallback | **本机存在 BASE 时代预构建 `.so`**（`main/native/*/`，含 `qgis_render_bridge` 与 `grid_render_core`，可 import，系统有 QGIS 运行库） | 主验证仍按提示词走 **无桥 Fallback** 路径（与 CI 主腿一致）；预构建 `.so` 仅作为**附加证据**（真实桥回退路径、真实 native payload 基线），在 PR 中明确标注来源与局限 |
| geo-viz-engine 已就位 | submodule 需 `git submodule update --init geo-viz-engine`（gdal/proj/well-log-engine 不需要，未初始化） | 已初始化 geo-viz-engine |

## D1. 侦察修正：提示词 §3 的前提有一处已过时

提示词称「`_PreparedLayer` 没有任何缓存」。**BASE 上不成立**：
`FallbackMapRenderBackend._prepared_layer`（`map_render_backend.py:1093-1126`）已按
`layer.id` 缓存、以 `cached.revision == int(layer.data_revision)` 校验，带
`_prepared_lock`、命中/未命中诊断计数，`_paint_composition` 末尾按 `seen_layers`
剪除（:1021-1027）。同族缓存还有 `_reprojected`（:665，键 `(layer, rev, src, dst)`）与
单槽 `_frame_cache`（:672）。

**决策（依提示词 §4.1「无收益项如实跳过」）**：
- ②「_PreparedLayer 缓存」的*实现*目标已在基线达成；本 Goal 对它做的是
  **量化确认 + 失效矩阵测试补全**（§3.4 的 7 个场景并非都有测试），
  而不是重写缓存。
- ①标量栅格每帧全幅拷贝、③拓扑逐要素过桥，两项**确认存在**，照做。

## D2. 标量栅格：改「每帧拷贝」为「按修订缓存的 QImage」

事实（`_draw_scalar_grid` :1665-1688）：
- 每帧 `scalar.rasterize()`。native `ScalarGridLayer.rasterize()`（bindings.cpp:173-182）
  **每次分配新 `(H,W,4)` numpy 缓冲并整体 memcpy**（C++ 内部像素有修订缓存，但
  C++→Python 的全幅拷贝每帧都发生）；纯 Python `_ScalarPayload.rasterize()`
  （layers.py:285-289 → `rasterize_rgba` :252-281）**每次全量 LUT 重算**，无任何缓存。
- 随后 `QImage(rgba.data, ...)` 非持有包装 + `.copy()`（:1677-1683）= 第二次全幅拷贝。

**决策**：在 `FallbackMapRenderBackend` 上加 per-layer QImage 缓存（提示词方案 b）：
- 键：`layer.id`；命中校验四元组 `(data_revision, style_revision,
  payload.data_revision, payload.style_revision)` + `payload is` 同一性 +
  `(width, height)`。快照修订与 payload 自身修订（native 层暴露
  `data_revision`/`style_revision`，bindings.cpp:138-141）同时纳入——belt and
  suspenders：任一来源漏 bump 都不会服陈旧像素。
- 值：`QImage(...).copy()` 一次（拥有自身数据，杜绝悬垂 numpy buffer——提示词
  §4.3 段错误红线），之后每帧零 `rasterize()`、零拷贝，直接 `drawImage`。
- 生命周期：与 `_prepared` 同锁（worker 线程会跑 `_draw_scalar_grid`）、同
  `seen_layers` 剪除、`shutdown()` 清空；条目持有 payload 强引用，随剪除释放。
- 纯 Python `_ScalarPayload` 增加 `data_revision`/`style_revision` 只读属性，
  转发所包裹的 `GridMapLayer`（`set_grid_result`→bump data；`set_color_ramp`/
  `set_value_range`→bump style，layers.py:240/245/250），使两种 payload 键语义一致。
- `rasterize()` 无 numpy（shape 探测失败）等病态输入路径保持逐字节等价的旧行为。

**等价性**：同一 `rgba` 字节 → 同一 QImage → 同一 `drawImage(QRectF, image)`
目标矩形与变换提示（painter 只有 Antialiasing，无 SmoothPixmapTransform）不变；
渲染输出逐像素等价，由像素对照测试钉死。

**否决的备选**：仅去掉 `.copy()` 直接引用 numpy buffer（方案 a）——只消掉第二次
拷贝，native 路径每帧的 C++→Py 全幅 memcpy 与纯 Python 路径的全量 LUT 重算仍在；
且 QImage 悬垂风险高。缓存方案把成本摊到「数据/样式变更时一次」。

## D3. 公共缓存类：抽 `LatestRevisionCache`，四处共用

提示词 §4.2-2 强烈建议与 `qgis_mirror._SIGNATURE_CACHE` 同构共用，避免第三处平行
实现。BASE 上同类「每主体至多保留一个修订版」的缓存实际有四处：

| 缓存 | 位置 | 主体 | 修订键 | 旧值用途 |
|---|---|---|---|---|
| `_prepared` | map_render_backend.py:661 | layer id | `data_revision` | 无 |
| `_reprojected` | :665 | layer id | `(rev, src, dst)`（store 时替换同层旧键） | 无 |
| 新增 scalar QImage | 本 Goal | layer id | 四元组+尺寸 | 无 |
| `_SIGNATURE_CACHE` | qgis_mirror.py:245-248 | `(id(stack), layer_id)` | `data_revision` | **有**：修订变化时旧签名作 delta 基线（:868-873 读旧值） |

**决策**：新模块 `paleo_workbench/mapping/revision_cache.py` 提供
`LatestRevisionCache[Subject, Value]`：
- `get(subject, revision_key)` — 仅当修订键完全相等才命中；
- `latest(subject)` — 不校验修订取最近值（供 mirror 的「旧签基线」读法）；
- `store(subject, revision_key, value)` — 同主体旧修订条目一律替换（mirror
  :1035-1040 的「同 (stack,layer) 只留一个修订」语义归一）；
- `prune(keep_subjects)` / `clear()`。
镜像侧的 `(stack,layer)` 主体键、渲染侧的 `layer.id` 主体键都成立；
`map_document_snapshot._FEATURE_CACHE` 是**有界 LRU**（按要素数淘汰），语义不同，
**不迁移**（避免为共用而共用）。

迁移范围：scalar QImage（新）、`_prepared`、`_reprojected`、`_SIGNATURE_CACHE`
四处；锁与诊断计数留在调用方（cache 类不做线程策略，保持浅显）。
`qgis_mirror` 迁移时**修复一处既有死代码 bug**（侦察发现）：
`_layer_ledger_tokens` 内 `return` 之后的 `_SIGNATURE_CACHE.clear()` 等 4 条语句
不可达（qgis_mirror.py:392-405），即 `reset_publish_ledger` 实际从未清签名缓存；
迁移后把真清理接入 `reset_publish_ledger`（行为变化由护栏测试 + 新增测试钉住，
详见 02-design）。

## D4. 拓扑批量化：探针式 `validate_many`，无桥 C++ 改动（边界 §4.4）

事实：
- C++ 桥 `geometry` 子模块（bindings.cpp:617-744）**没有**批量校验函数
  （repo 无 `validate_many/batch/geometries`）；`run_geometry_checks` 是镜像层级
  的另一通道（native_edit_session 已优先用它），不经 `validate_records`。
- `validate_records`（topology.py:141-202）对每条 Polygon/MP/LS/MLS 记录调一次
  `bridge_validate(geometry)`；桥异常→一次性降级 Shapely（P2-6 语义，保留）。

**决策**：
- `TopologyService._bridge_validate_many_fn()`：能力探针，照 `_stack_supports_delta`
  （qgis_mirror.py:431-450）两层探测——`inspect.signature`（纯 Python fake/新桥）
  → pybind11 `__doc__` 首行形参声明（`geometries:`）→ 不支持。探针不调用方法、
  不缓存结果（与 mirror 探针同一纪律）。
- `validate_records`：收集本轮所有可校验几何，一次
  `validate_many(geometries) -> list[list[dict]]`（按位置对齐）；返回长度不符或
  异常 → 记一次 warning，整批回退逐要素路径（老桥/异常桥零行为变化）。
- 校验规则、ring-closure 检查、`validator_unavailable` 语义逐字不变。
- **诚实声明**：BASE 的真桥没有批量函数，生产环境（现版桥）仍走 N 次回退——
  本 Goal 交付的是 Python 侧批量接口 + 探针 + 回退，及 fake 桥下的
  N→1 实测证据；桥侧补 `validate_many` 列入 Known limitations / 后续单轮。
  （本机恰好有可 import 的 BASE 版预构建桥：可实测「真桥→探针不支持→回退」
  路径的真实行为。）

## D5. 失效矩阵测试形态（含反向对照）

7 场景（§3.4）：改顶点 / 增删要素 / 改样式 / 可见性-不透明度 / 切换图层 /
切换 CRS / undo-redo。每场景：
- **正向测试**：操作后断言（a）缓存未命门（诊断计数）与（b）渲染结果变化
  （或不变，当且仅当语义上不应变——如「改样式零重建 prepared」）。
- **反向对照**：人为破坏缓存键（monkeypatch 使修订比较恒真 / 键退化为常数），
  断言被测输出**变为陈旧**——证明正向断言若键损坏必红，测试不是空断言。
  对照测试自身断言「陈旧发生了」，不写任何恒真断言（tautological 守卫，
  tests/e2e/test_integrity_guard.py:86-95）。

## D6. 不做（边界重申）

- 不碰 `native/`、`third_party/`、`_vendored/`、`catalog/`、`geological_pipeline/`。
- 不改校验规则、不改渲染视觉输出（逐像素等价由测试钉死；如确有差异必须在 PR 声明）。
- `QgisMapRenderBackend` 静态审查为主；本机预构建桥存在时跑附加冒烟，不作为门禁。
- 不跑 `tests/perf/` 全量、`-m slow`、`-m opengl`；`test_mirror_publish_scale.py::[50]`
  基线已红（60ms 预算 vs 64.6/201.4ms 实测），**不修不判**。
