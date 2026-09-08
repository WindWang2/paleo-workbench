# 05 — Verification（验证证据）

> 本机 Windows（16C/31.2GB）。venv：`<worktree>/.venv`（Python 3.12.13，
> PySide6 6.11.2，uv 管理，仓库依赖 + geoviz 子包 + 5 个本地 native 扩展
> 就位）。全量证据采用**逐文件批驱动**（`scripts/run_suite_batched.py`）：
> 本机单进程全量在 main 与本分支都以访问冲突/挂死终止（基线既有，见
> 08-7），批驱动可完整收集两侧结果并区分「确定性失败」与「顺序污染崩溃」。

## 1. 分层测试执行记录

### 1.1 纯契约层（headless，必绿）

```
.venv/Scripts/python.exe -m pytest tests/test_authoring_contracts.py -q
→ 62 passed（capability 快照/上下文/30 工具状态机全矩阵/EditDelta 纯函数与会话集成）
```

### 1.2 工作站集成（headless，必绿）

```
.venv/Scripts/python.exe -m pytest tests/test_workstation_authoring_kernel.py -q
→ 9 passed（evaluator 端到端/reason 通道/dirty 门/RAW 锁/fallback 溯源/
   split 标注/拓扑传播+门禁/compound undo/token 注入）
```

### 1.3 稳定性/性能探针（headless，必绿）

```
.venv/Scripts/python.exe -m pytest tests/test_v7_stability_probes.py -q
→ 12 passed（复杂度比/journal 上界/1k-100k 规模/100x 循环/50 层切换）
```

### 1.4 受影响存量文件（headless，必绿）

```
tests/test_composite_editing.py tests/test_composite_gis.py
tests/test_map_action_controller.py tests/test_map_tools.py
tests/test_map_topology.py tests/test_map_topology_rebuild.py
tests/test_m3_stress_topological_remediation.py
tests/test_workstation_context.py tests/test_workstation_lifecycle.py
→ 全部通过（23/58/6/10+4新增/30/… 具体计数见批驱动 JSON）
```

### 1.5 全量批驱动对比（worktree vs main；逐文件，崩溃重试一次）

- worktree 侧：~554 文件 → **510 pass / 44 fail（0 crash 未重试成功）**。
- main 侧：545 文件 → **501 pass / 44 fail**（同口径，共有的环境性失败）。
- 差集分析（`wt-only - main-only` 交集脚本）：
  - 本分支引入的新增失败 **2 个**，已全部定位并修复（commit
    `7ef00861`）：
    1. `test_map_dock_manager.py::test_single_toolbar_strip_carries_every_action`
       — reshape 新动作未同步到编图页工具条（已加入工具条分组）。
    2. `test_round3_convergence.py::test_topology_validate_labels_missing_shapely`
       — 旧测试只假设 shapely 单引擎；V7 为双引擎（QGIS 优先），
       `validator_unavailable` 合一判词已更新。
  - 修复后两腿失败集回归为**同一组环境性失败（42 个共有）**，
    无分支引入增量。
- 42 个共有失败均为无桥环境的既有状态：`test_qgis_*` 系列（桥未装，
  skip/exit=5）、geoviz/数据资产/厂商相关、窗口包完整性等——main 同
  口径逐文件运行同样失败，非本分支引入。
- `tests/test_theme_and_sidebar.py`（全量顺序挂死源头）在批驱动的
  单文件运行下**通过**——证实为顺序污染（table_preview + theme
  setStyleSheet 链在 Qt 全局样式表更新时的死循环），08-7 记录。

### 1.6 QGIS 腿（PALEO_REQUIRE_QGIS=1；桥构建完成后）

- [ ] vendored QGIS 4.2.0 构建（Windows 首建）成功 + 产物清单
- [ ] `qgis_render_bridge` 0.3.0a0 扩展构建成功（setup.py Windows 路径）
- [ ] `PALEO_REQUIRE_QGIS=1 pytest -m qgis`：43 个既有 QGIS 文件 + 
      `test_qgis_v7_authoring.py` 全绿（含 capability manifest 权威性、
      validate/reshape、原生 measure、endpoint/intersection 下推）
- [ ] `probe_qgis_capability()` → available；工作站 `_qgis_capability`
      token 注入端到端

## 2. 三轮 Review

- Review 1（Correctness）：完成——0 P0 / 5 P1 / 11 P2，P1 全修、P2 除
  P2-11 记录已知限制外全修（07-review-findings.md）。
- Review 2（Architecture）：完成——0 P0 / 1 P1 / 10 P2，P1 已修、P2
  处置见同文件。
- Review 3（UX/Performance/Adversarial）：待桥构建与 QGIS 测试后执行。

## 3. 端到端人工脚本（原生栈冒烟）

桥就绪后以最小工程驱动：新建图层 → 开编辑 → 原生加点/线/面 → 顶点拖动
（含拓扑传播）→ 移动 → 选择/框选 → measure（椭球）→ reshape → split/
merge → 保存编辑（拓扑门禁）→ undo/redo → 回滚。逐步截图/日志存证。
（以 QGIS 标记测试的形式落地于 test_qgis_v7_authoring.py，不依赖人工。）
