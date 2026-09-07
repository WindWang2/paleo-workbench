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

- [ ] worktree 侧结果（scratch_wt_batched.json 摘要）
- [ ] main 侧结果（main_batched.json 摘要）
- [ ] 差集分析：本分支引入的新增失败 = ∅（预期）；两侧共有的环境性失败
      清单如实列出（非本分支引入）
- [ ] `tests/test_theme_and_sidebar.py`（批驱动含它）：单文件运行的行为
      （预期通过——挂死只在全量顺序污染下出现）

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
