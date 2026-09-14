# Prompt 1 — 导入/入库 I/O 流水线消除重复读盘（V12-A）

> **用法**：把本文件全文作为 `/goal` 的输入交给 zcode。全自动，无需人工选择；
> 遇到歧义按「默认最佳」自行决策并在 `docs/development/ingest-io-v12/00-decisions.md`
> 里记录理由。不要停下来提问。

---

## 0. 你的身份与目标

你是 **Paleo Workbench** 仓库的独立开发代理，在一个**全新 worktree 分支**上
完成一个完整的工程目标。

**Goal（一句话）**：消除受管数据入库路径上的重复 I/O，使单次受管 RAW 导入
从「完整读 3 遍 + 写 2 遍」降到「读 1 遍 + 写 1 遍」，并让目录批量导入
在元数据收集阶段获得并发能力。**语义零变化**：落盘结构、原子性、只读标记、
校验和诚实性全部保持不变。

**预期规模**：约 10 亿 tokens 的开发量。这不是一次冲刺——按
`wayfinder` → `to-spec` → `to-tickets` → `implement` → `code-review` → `/ship`
的完整流程走完，中间允许自我迭代多轮。宁可多验证，不要赶工。

---

## 1. 强制前置：环境与并发预算

### 1.1 工作目录

```bash
# 仓库根（基线）
cd /c/Users/wangj.KEVIN/projects/paleo-workbench
git fetch origin main
git rev-parse origin/main      # 记下这个 SHA，作为本 Goal 的 BASE
```

**新建 worktree 分支**（沿用本仓既有约定：worktree 放在仓库**外部**同级目录）：

```bash
git worktree add ../paleo-workbench-ingest-io-v12 \
    -b feat/ingest-io-v12 origin/main
cd ../paleo-workbench-ingest-io-v12
```

> ⚠️ 不要用 `git worktree prune`（本仓曾因此清空 worktree 注册）。
> 收尾时用 `git worktree remove <path>`。

### 1.2 环境

- Python **3.12**（`requires-python = ">=3.12,<3.13"`）。
- 主 checkout 的 `.venv` 指向主仓库，**不要直接用**。在新 worktree 建自己的：
  ```bash
  python -m venv .venv
  .venv/Scripts/python.exe -m pip install -e ".[dev]" -r requirements-geoviz.txt
  ```
- Shell 是 **Windows / GitBash**。注意：本环境下 coreutils 可能缺失
  （`dirname` / `cat` / `head` / `tail` / `ls` 可能 command not found）——
  用 Python 或专用工具代替，**不要**依赖这些命令。

### 1.3 ⛔ 编译资源预算（硬约束）

- **本 Goal 不需要编译任何 C++**。不要碰 `native/`、`third_party/`、
  `geo-viz-engine/` 的扩展构建。
- **本 Goal 不需要 QGIS 桥**。所有改动与测试都应是**纯 Python**，
  用 `pytest -m "not qgis and not slow and not opengl"` 即可覆盖。
- 若某个测试因缺桥而 skip，**接受 skip**，不要为了让它跑而启动构建。
- **禁止**在仓库里跑全量重型套件（`tests/perf/`、`-m slow`、3D/OpenGL 腿）。
  只跑你改动的模块相关的测试文件。

### 1.4 ⛔ 并发预算（硬约束）

**最多同时启用 2 个 subagents。** 任何时候都不许超过 2 个在跑。
单条消息里最多发 2 个 `Agent` 调用。

推荐分工（各阶段内轮换，但同一时刻 ≤2）：

| 阶段 | subagent A | subagent B |
|---|---|---|
| 侦察 | 读 `catalog/` 写路径 | 读 `resources/` 读路径 |
| 实现 | 改 `catalog/storage.py` | 改 `resources/` |
| 评审 | Standards 轴 | Spec 轴 |

> 若你判断需要第 3 个视角，**串行**执行，不要并行开第 3 个。

### 1.5 ⛔ 无 CI

**本 Goal 不依赖任何 CI**。不要 `gh pr checks --watch`，不要等 GitHub Actions。
所有验证在本地完成。创建 PR 后即可结束。

---

## 2. 可用的 skills（按需加载，不要跳过）

按顺序使用，每个都是真实存在的：

1. **`wayfinder`** — 先把"怎么做"规划成 issue 地图上的决策票。
   本 Goal 的 destination 已经很明确（见 §0），所以你**只需**用它做
   「把未知项变成 ticket」这一步，然后**立即进入实现**——不要为了规划而规划。
   （本仓 wayfinder 约定：地图是 `wayfinder:map` label 的 issue，
   子票是 `wayfinder:research|grilling|task`。）
2. **`planning-with-files`** — 用文件做规划与进度跟踪。
   **强制**在 worktree 内维护：
   - `docs/development/ingest-io-v12/00-decisions.md` — 每个自主决策 + 理由
   - `docs/development/ingest-io-v12/01-baseline.md` — 改造前的实测 I/O 次数
   - `docs/development/ingest-io-v12/02-design.md` — 目标设计
   - `docs/development/ingest-io-v12/03-verification.md` — 验证证据
   - `docs/development/ingest-io-v12/04-known-limitations.md` — 诚实的未做项
   每完成一步就更新，**不要**最后一次性补写。
3. **`to-spec`** — 把 §3 的问题陈述写成规格。
4. **`to-tickets`** — 拆成可独立验证的 ticket。
5. **`tdd`** — 在预定的接缝上先写失败测试。
6. **`implement`** — 实现。
7. **`code-review`** — 双轴评审（Standards + Spec），并行 2 个 subagent。
8. **`gstack` `/ship`** — 收尾与 PR（若 gstack 的 `/review` 与仓库
   `agent/skills/code-review` 冲突，**用仓库自带的那份**）。
9. **`diagnosing-bugs`** — 遇到难缠失败时用。
10. **`git-guardrails-claude-code`** — 提交前自检。

同时，**`CLAUDE.md` 强制的 Karpathy guidelines 全程有效**：
Think before coding / Simplicity first / Surgical changes / Goal-driven execution。

---

## 3. 待解决的问题（已完成的侦察结论，可直接采信但需你自行复核）

> 这些是上一轮分析（基线 `926f3335`）的结论，**行号可能已漂移**。
> 你必须**自己重新读一遍代码确认**，再动手。

### 3.1 单次受管 RAW 导入 = 读 3 遍 + 写 2 遍

路径：`ui/pages/data_page.py` 的导入 worker
→ `ui/data_lifecycle_controller.py::register_imported_resources`
→ `catalog/lifecycle.py::register_resource_input`
→ `catalog/adapter.py::register_input`
→ `catalog/service.py::import_raw` / `register_version`
→ `catalog/storage.py::place_managed_file`

| 遍 | 位置（旧快照行号） | 做什么 |
|---|---|---|
| 读 1 | `catalog/adapter.py:266` | `sha256_file_or_none(resolved_path)` 先算摘要 |
| 读 2 | `catalog/storage.py:445-449` | `place_managed_file` 边读边算摘要边写临时文件 |
| 写 1 | `catalog/storage.py:452` | `os.replace` 落盘为受管 payload |
| 读 3 | `catalog/storage.py:166` | `place_blob` → `_place_blob_bytes` **再读一遍刚落盘的 target** |
| 写 2 | `catalog/storage.py:167-171` | 写 `blobs/xx/<digest>` |

**去重快路径更糟**：`catalog/storage.py:416-431` 当 `known_sha256` 命中已有
blob 时，为证明源文件确实等于该摘要又调 `_digest_of(source)`（`:419`）
——**第 4 遍全量读**，然后才走 O(1) 免拷贝。

### 3.2 目录导入串行 vs 扫描并行

- `resources/import_service.py` 的 `_collect_folder`（约 `:201-232`）—
  纯串行 `for path in paths`，每个文件 `path.stat()` + `_probe_summary`
- `resources/import_service.py` 的 `import_files`（约 `:235-269`）— 同样串行
- 但 `resources/scanner.py`（约 `:71-98`）— **已经**用
  `ThreadPoolExecutor(max_workers=workers)`（`:89`）

同一仓库里扫描并行、导入串行。

---

## 4. 交付要求

### 4.1 必须达成的可验证目标

1. **单次受管 RAW 导入**：字节完整读 **1 遍**、完整写 **1 遍**（不含
   fsync/rename 这类元数据操作）。
2. **去重命中路径**：读 **1 遍**（除非内容确实需要重新证明——见 §4.2 护栏）。
3. **目录导入**：元数据收集阶段并发化，且**结果顺序与现在完全一致**
   （现有测试依赖 `sorted(paths)` 的确定性）。
4. **语义零变化**：
   - `place_managed_file` 的 temp + fsync + `os.replace` 原子性
   - 落盘后的只读标记
   - `known_sha256` 与实际内容不符时**必须仍抛 `CatalogError`**
   - `catalog.json` manifest 行为不变
5. **新增回归钉**：用 monkeypatch 统计 `_digest_of` / 文件打开次数，
   把「单次导入恰好 1 次摘要计算」钉死。**必须包含一个反向对照**
   （人为让它变成 2 次，断言测试会红），证明断言不是空断言。

### 4.2 护栏与风险

- **最大的诱惑是"相信调用方的摘要，不校验"**。这是错的：注释里
  `#1175` / 「Honest checksum」的语义必须保住——**在真正拷贝的路径上**，
  必须仍然验证 caller 提供的摘要与实际字节一致。可以省的是**重复读**，
  不是**校验**。
- 仓库有 **tautological assertion 守卫**（`test_no_tautological_assertions`，
  见 #1266/#1028）。**不要写 `assert True` / `or True` 凑数断言**。
- 不要为并发引入新的第三方依赖；用标准库 `concurrent.futures`。
- 并发写同一个 SQLite store 的路径**不要动**——那是 `DataCatalogService`
  的事务域，保持串行提交语义。

### 4.3 边界（明确不做）

- 不碰 `native/`、`third_party/`、QGIS 桥。
- 不改 catalog schema 版本（`STORE_SCHEMA_VERSION` / `INDEX_SCHEMA_VERSION`）。
- 不重构 `catalog/service.py` 的缓存/事务框架（那是另一个 Goal）。
- 不动 `_vendored/`。

---

## 5. 执行流程（全自动，不要停）

```
1. 建 worktree + venv（§1）
2. 读 CLAUDE.md / CONTEXT.md / agent/skills/karpathy-guidelines/SKILL.md
3. 写 docs/development/ingest-io-v12/
   00-decisions.md（空的，边做边填）
   01-baseline.md —— 先量化！用 monkeypatch 实测"现在读了几遍"
4. wayfinder：把未知项变成 ticket（只做这一步，然后继续）
5. to-spec → to-tickets → tdd → implement
   （每完成一个 ticket 就 commit 一次，message 说明改了什么、为什么）
6. 自测：只跑相关测试文件，-m "not qgis and not slow and not opengl"
7. code-review（并行 2 个 subagent：Standards / Spec）
   —— 修掉 P0/P1，P2 buffered 记录到 04-known-limitations.md
8. 更新 03-verification.md：before/after 数字 + 测试证据
9. 提交 PR
```

### 5.1 提交规范

- 每个 ticket 一个 atomic commit。
- message 用本仓风格：`perf(ingest): <what> (#<issue-if-any>)`
  或 `fix(ingest): ...`。
- **不要**加 `[skip ci]`（本 Goal 不依赖 CI，但也不需要特意跳过）。

### 5.2 PR 规范

```bash
GH="/c/Program Files/GitHub CLI/gh.exe"   # 本机 gh 在此路径
"$GH" pr create \
  --base main \
  --head feat/ingest-io-v12 \
  --title "perf(ingest): 消除入库路径重复 I/O（V12-A）" \
  --body "<见下>"
```

PR body 必须包含：
- **Base SHA**（§1.1 记下的 origin/main）
- **before/after 实测数字**（读盘/写盘遍数、目录导入墙钟）
- **语义不变性声明**：列出 §4.1 的第 4 点，逐条说明如何验证
- **测试证据**：跑了哪些文件、多少 passed/skipped
- **明确的 `## Known limitations`**：把 04-known-limitations.md 的内容带过来
- **明确声明未做 C++/QGIS 构建验证的必要性**（本 Goal 不涉及）

---

## 6. 完成定义（Definition of Done）

- [ ] worktree 分支 `feat/ingest-io-v12` 已创建，PR 已提交
- [ ] `docs/development/ingest-io-v12/` 五份文档齐全
- [ ] 单文件导入读/写遍数达标（有实测证据）
- [ ] 新增回归钉含反向对照，且 **tautological 守卫通过**
- [ ] 相关测试文件全绿（或明确记录既有失败，且证明非本次引入）
- [ ] code-review 双轴报告已出，P0/P1 清零
- [ ] `04-known-limitations.md` 诚实记录了未做项
- [ ] 全程 subagent 并发 ≤2（在 progress 文档里有记录）

---

## 7. 完成后回报

在最终消息里给出：BASE SHA、分支名、PR URL、before/after 数字表、
测试结果摘要、P0/P1 处理情况、以及**任何你认为后续需要单独一轮的事**。
不要粉饰——如果某项没做到，直说。
