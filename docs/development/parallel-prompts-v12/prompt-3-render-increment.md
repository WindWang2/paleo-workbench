# Prompt 3 — 渲染/镜像增量通道（V12-C）

> **用法**：把本文件全文作为 `/goal` 的输入交给 zcode。全自动，无需人工选择；
> 遇到歧义按「默认最佳」自行决策并记录。
> **注意**：本 Goal 涉及 Qt 渲染路径，但**不需要 QGIS 桥**——
> 回退后端（`FallbackMapRenderBackend`）是纯 Qt 的，你的验证都在它上面做。

---

## 0. 你的身份与目标

你是 **Paleo Workbench** 仓库的独立开发代理，在一个**全新 worktree 分支**上
完成一个完整的工程目标。

**Goal（一句话）**：把 2D 渲染与拓扑校验从「每帧/每要素全量」改成增量——
① 标量栅格绘制不再每帧全幅拷贝；② `_PreparedLayer` 按数据修订号缓存，
未变图层零重建；③ 拓扑校验从「每要素一次跨语言往返」改成批量接口。
**渲染结果必须逐像素等价**（除非显式声明并可见）。

**预期规模**：约 10 亿 tokens。本方向的正确性风险**集中在缓存陈旧**，
请把「缓存失效的对照测试」当作核心交付物，而不是附带。

---

## 1. 强制前置：环境与并发预算

### 1.1 工作目录

```bash
cd /c/Users/wangj.KEVIN/projects/paleo-workbench
git fetch origin main
git rev-parse origin/main      # BASE

git worktree add ../paleo-workbench-render-v12 \
    -b feat/render-increment-v12 origin/main
cd ../paleo-workbench-render-v12
```

> ⚠️ 不要用 `git worktree prune`。收尾用 `git worktree remove <path>`。

### 1.2 环境

- Python **3.12**。新 worktree 建自己的 venv：
  ```bash
  python -m venv .venv
  .venv/Scripts/python.exe -m pip install -e ".[dev]" -r requirements-geoviz.txt
  ```
- Qt 测试用 **offscreen**：
  ```bash
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest ...
  ```
  （`tests/conftest.py` 的 `pytest_configure` 已处理 Qt 环境准备，
  读一遍它确认。）
- Shell 是 **Windows / GitBash**。coreutils 可能缺失
  （`dirname`/`cat`/`head`/`tail`/`ls` 可能 command not found）。

### 1.3 ⛔ 编译资源预算（硬约束）

- **本 Goal 不需要编译 C++，不需要 QGIS 桥。**
- 你的验证对象是 **`FallbackMapRenderBackend`**（纯 Qt 路径）。
  `QgisMapRenderBackend`（需桥）**只做静态审查，不要求运行验证**。
- **禁止**跑 `tests/perf/` 全量、`-m slow`、`-m opengl`。
  ⚠️ 注意：`tests/perf/test_mirror_publish_scale.py::[50]` 在基线
  已是**既有失败**（预算 60ms，实测 64.6/201.4ms），**不是你的问题**，
  不要试图修它，也不要因为它红就以为自己引入了回归。
- 只跑你改动的模块相关测试文件。

### 1.4 ⛔ 并发预算（硬约束）

**最多同时启用 2 个 subagents。** 单条消息最多 2 个 `Agent` 调用。

| 阶段 | subagent A | subagent B |
|---|---|---|
| 侦察 | 读 `map_render_backend.py` 绘制路径 | 读 `topology.py` + `qgis_mirror.py` 缓存范式 |
| 实现 | 改 prepared-layer 缓存 | 改标量栅格绘制 / 拓扑批量 |
| 评审 | Standards 轴 | Spec 轴 |

需要第 3 个视角时**串行**执行。

### 1.5 ⛔ 无 CI

**不依赖任何 CI**。不要 `gh pr checks --watch`。本地验证完即止。

---

## 2. 可用的 skills（按需加载）

1. **`wayfinder`** — 把"缓存键需要包含什么"这类决策变成 ticket 并当场解决。
2. **`planning-with-files`** — **强制**在 worktree 内维护：
   - `docs/development/render-increment-v12/00-decisions.md`
   - `docs/development/render-increment-v12/01-baseline.md`（先量化）
   - `docs/development/render-increment-v12/02-design.md`
   - `docs/development/render-increment-v12/03-verification.md`
   - `docs/development/render-increment-v12/04-known-limitations.md`
3. **`codebase-design`** — 抽公共缓存类时用它评估设计
   （本仓有 `DESIGN-IT-TWICE.md` / `DEEPENING.md`）。
4. **`implement`**、**`code-review`**（双轴并行 2 subagent）、**`gstack` `/ship`**。
5. **`diagnosing-bugs`** — 缓存陈旧类 bug 系统排查。
6. **`tdd`** — 缓存失效对照测试非常适合 TDD。

`CLAUDE.md` 强制的 Karpathy guidelines 全程有效。

---

## 3. 待解决的问题（侦察结论，需你自行复核行号）

> 基线 `926f3335`。**行号可能已漂移，必须自己重读确认。**

### 3.1 标量栅格每帧全幅拷贝

`mapping/map_render_backend.py`，`_draw_scalar_grid`（约 `:1665-1688`）：

```python
rgba = scalar.rasterize()                    # 约 :1670  取全幅 RGBA
...
image = QImage(rgba.data, width, height, width*4,
               QImage.Format.Format_RGBA8888).copy()   # 约 :1677-1683  ← 全幅拷贝
```

滚轮缩放/平移时**每帧**都吃这个全幅拷贝。

### 3.2 `_PreparedLayer` 没有任何缓存

`mapping/map_render_backend.py`：

- `_prepared_layer`（约 `:1093-1127`）— 逐 layer 逐 feature 构建
  `_PreparedLayer`（含 numpy 数组组装），约 `:1099` `for feature in layer.features`
- `_native_snapshot`（约 `:1815`）— 每次 `set_layer_snapshot` 重建完整
  native snapshot 列表
- `_reship_full_snapshot`（约 `:1909`）— 名字说明一切

**对比**：`mapping/qgis_mirror.py` 已经有成熟的增量范式可以照抄——
- `_SIGNATURE_CACHE`（约 `:245-246` 注释，`:1033` 写入）：
  `(stack, layer, data_revision)` → `(fid → signature)`
- 逐要素签名 `_feature_signature`（约 `:470`）
- `LayerContentToken` / `LayerStyleToken`（约 `:161-193`）
- 发布账本 `align_publish_ledger`（约 `:271`）

**即：镜像侧已解决"发布"，渲染侧的准备阶段仍是全量。**

### 3.3 拓扑校验每要素一次跨语言往返

`mapping/topology.py`（现约 279 行），`validate`（约 `:129-139`）与
`validate_records`（约 `:141-189`）：

- `:131` `for layer in layers`
- `:161` `for record in records`
- `:170` `bridge_validate(geometry)` ← **每个几何单独过一次桥**

**N 个要素 = N 次 C++ 往返。**

注意约 `:147-149` 已有一处"单次提升探测"优化（注释提到 review-2 P2-6），
说明这类 O(N) 开销**已被识别过**，只是没做成批量接口。

### 3.4 缓存陈旧是本方向的头号风险

本仓有**前车之鉴**：issue #1257（P1，数据损坏级）——
「全量重发路径不失效捕捉定位器 → 顶点编辑命中陈旧几何」。
同类错误在本方向极易重犯。你的缓存键设计必须能抵御：
- 改一个顶点
- 加/删一个要素
- 改样式（但不改几何）
- 改可见性/不透明度
- 切换图层
- 切换 CRS
- undo/redo

---

## 4. 交付要求

### 4.1 不可跳过的第一步：量化基线

改任何代码前，用**独立脚本**测出当前：

1. 标量栅格单帧绘制的耗时与**拷贝字节数**
2. `_prepared_layer` 在「无数据变化」情况下重复调用的耗时
   （这应该趋近于 0，如果能缓存——现在是每次都全量）
3. `topology.validate_records` 的耗时 vs 要素数（证明是 O(N) 跨语言）
4. 记录到 `01-baseline.md`

若基线证明某项**没有可测量的收益**，**如实记录并跳过该项**——
不要为了凑数而优化。

### 4.2 必须达成的可验证目标

1. **标量栅格绘制**：消除每帧全幅 `.copy()`。
   做法二选一（自行判断哪个更干净）：
   - 确认 `rasterize()` 返回值生命周期后用 `QImage` 直接引用；
   - 或让 `rasterize()` 产出并缓存 `QImage`，把拷贝摊到"数据变更时一次"。
   **不要**让 `QImage` 引用已释放的 numpy buffer（会段错误）。
2. **`_PreparedLayer` 缓存**：
   - 键必须包含**完整的数据修订号**（复用 `qgis_mirror` 的 token 语义）
   - **强烈建议抽公共缓存类**，与 `qgis_mirror._SIGNATURE_CACHE` 同构共用，
     避免产生**第三处**平行实现（本仓已有"平行词表漂移"的历史教训）
3. **拓扑校验批量化**：新增批量接口（如 `bridge_validate_many`），
   N 次往返 → 1 次。**保留单要素路径作为回退**（老桥可能没有批量签名）。
   - 参考 `qgis_mirror` 的 `_stack_supports_delta`（约 `:431-450`）做法：
     `inspect.signature` 先探测，pybind11 builtin 无签名时退化为
     docstring 探测，再退化为不支持。

### 4.3 护栏与风险

- ⚠️ **本仓有 tautological assertion 守卫**
  （`test_no_tautological_assertions`，见 #1266/#1028）。
  **不要写 `assert True` / `or True`**。
- ⚠️ **核心交付物是"缓存失效对照测试"**，不是缓存本身。
  每个失效场景（§3.4 列的 7 项）都要有测试，且**每个测试都要有反向对照**
  （人为破坏缓存键，断言必须变红），证明测试不是空断言。
- ⚠️ **既有失败不要误判**：`tests/perf/test_mirror_publish_scale.py::[50]`
  在基线已红（预算 60ms，实测 64.6/201.4ms），非你引入。
- 现有护栏测试（改动前先读）：
  - `tests/test_mirror_lifecycle_v11.py`（336 行）
  - `tests/test_layer_tree_diff_v11.py`
  - `tests/test_mirror_delta_publish.py`
  - `tests/test_mirror_fields_sig.py`
- Qt 对象生命周期：`QImage` 引用外部 buffer 是**已知的段错误来源**，
  务必确认所有权。本仓有过 "QTimer.segfault" 类修复（PR #1247），
  对此敏感。
- **不要**改渲染的视觉输出。若有任何像素级变化，必须在 PR 里声明并论证。

### 4.4 边界（明确不做）

- 不碰 C++（`native/`、`third_party/`）。
- **不要求** `QgisMapRenderBackend`（需桥）的运行时验证——只做静态审查，
  并在已知限制里声明「需在有 build 的环境补验证」。
- 不改 `topology.py` 的**校验规则**（只改调用方式）。
- 不碰 `catalog/`、`mapping/geological_pipeline/`（其他 Goal 的战场）。
- 不碰 `_vendored/`。

---

## 5. 执行流程（全自动，不要停）

```
1. 建 worktree + venv（§1）
2. 读 CLAUDE.md / CONTEXT.md / karpathy-guidelines
   + tests/conftest.py（Qt 环境准备）
   + qgis_mirror.py 的缓存范式（§3.2 列的那些）
   + §4.3 列的四个护栏测试
3. ★ 量化基线（§4.1）→ 01-baseline.md
4. wayfinder：把"缓存键包含什么"变成 ticket 并解决 → 00-decisions.md
5. 抽公共缓存类（若判定值得）→ commit
6. 标量栅格去拷贝 → commit
7. _PreparedLayer 缓存 + 失效对照测试 → commit
8. 拓扑批量接口 + 回退路径 → commit
9. 自测：QT_QPA_PLATFORM=offscreen，只跑相关测试文件
10. code-review（并行 2 subagent）→ 修 P0/P1
11. 更新 03-verification.md
12. 提交 PR
```

### 5.1 提交规范

`perf(render): <what>` / `refactor(render): <what>`，
每个逻辑变更一个 atomic commit。不要 `[skip ci]`。

### 5.2 PR 规范

```bash
GH="/c/Program Files/GitHub CLI/gh.exe"
"$GH" pr create --base main --head feat/render-increment-v12 \
  --title "perf(render): 渲染准备与拓扑校验增量�/批量（V12-C）" \
  --body "<见下>"
```

PR body 必须包含：
- **Base SHA**
- **before/after 实测表**（逐项：栅格拷贝字节、prepared-layer 重建耗时、
  拓扑跨语言调用次数）
- **渲染等价性声明**：有无像素变化，如何验证
- **缓存失效矩阵**：7 个失效场景 × 对应测试名
- **测试证据**：文件 + passed/skipped；并**明确标注**
  `test_mirror_publish_scale.py::[50]` 是既有失败
- **`## Known limitations`**：含"QgisMapRenderBackend 运行时未验证"
- **明确声明**：本 Goal 不涉及 C++ 构建

---

## 6. 完成定义（Definition of Done）

- [ ] worktree 分支 `feat/render-increment-v12` + PR 已提交
- [ ] `docs/development/render-increment-v12/` 五份文档齐全
- [ ] 基线已量化；无收益的项已如实跳过并记录
- [ ] 标量栅格每帧全幅拷贝已消除（有实测证据）
- [ ] `_PreparedLayer` 缓存在"无变化"时命中（有实测证据）
- [ ] 拓扑校验跨语言调用数已批量化（有实测证据）
- [ ] **缓存失效矩阵 7 项全有测试 + 反向对照**
- [ ] tautological 守卫通过
- [ ] code-review 双轴已出，P0/P1 清零
- [ ] 既有失败已明确标注，未误判为回归
- [ ] 全程 subagent 并发 ≤2（有记录）

---

## 7. 完成后回报

给出：BASE SHA、分支、PR URL、before/after 表、缓存失效矩阵、
渲染等价性结论、测试摘要（含既有失败标注）、P0/P1 处理、
以及后续需要单独一轮的事（尤其 QGIS 桥侧验证）。
任何"我没能运行验证"的部分，**必须明说**。
