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

### 1.6 QGIS 腿（PALEO_REQUIRE_QGIS=1；已执行，有证据）

- [x] vendored QGIS 4.2.0 构建（Windows 首建）成功：`output/lib` 三 lib +
      `output/bin` 三 DLL + `resources/srs.db`；运行时目录自包含（452 DLL，
      含 OpenSSL 3.0 对 + Qt6Core5Compat）。
- [x] `qgis_render_bridge` 0.3.0a0 扩展构建成功（setup.py Windows 路径：
      Qt include/lib 布局、vendor cmake flags、全 Qt link 集、dep 头）。
- [x] `PALEO_REQUIRE_QGIS=1 pytest -m qgis`（PROJ_DATA 指向 vcpkg proj.db）：
      **194 passed**，43 个既有 QGIS 文件全绿 + `test_qgis_v7_authoring.py`
      15/15（含 capability manifest 权威性、validate/reshape、原生 measure、
      endpoint/intersection 下推）。剩余：3 个栅格测试需 osgeo（Windows venv
      无，Linux CI 有；V7 矢量范围外）+ 1 个既有 QMenu teardown error。
- [x] `probe_qgis_capability()` → available；工作站 `_qgis_capability`
      token 注入端到端（`test_sessions_carry_engine_token`）。
- [x] Review-3 后回归：QGIS 腿 194 passed（同口径）；headless 受影响文件
      278 passed（contracts/workstation/stability/composite/gis/action/
      tools/topology/dock/mapping-page/context/lifecycle/round3）。

## 4. Windows loader 共存证据（V7 独有）

- 单 Qt 规则：进程 Qt 唯一来自 PySide6 6.8.3（C:/deps Qt 6.8.0 只做编译期
  头/库，不进运行时）；vendored QGIS DLL 按 6.8.0 构建、跑在 6.8.3 上
  （Qt 小版本前向兼容，实测 QgisMapStack 初始化/画布/工具全通）。
- MSVCP 预占：numpy 私有 trimmed msvcp 先占坑会导致 VS2022 构建的 QGIS
  DLL 报 WinError 127——`.pth` 在 site 初始化期预占系统最新版 + ensure
  内重复（幂等），contract 全文件 63 passed 为证。
- OpenSSL 对齐：uv python 占坑 libcrypto 3.5.5；vendor 栈换 conda 3.0 对
  （前向兼容方向正确），vcpkg 3.6.3 封存備用。
- CRT 伪 DLL 清理：vendor bin 删除 api-ms-win-*/msvcp/vcruntime 伪 DLL，
  PATH 前置不再遮蔽系统解析；`os.add_dll_directory` 顺序 vendor 首位。
- QtLogHandler 双版本兼容：不重写 `logging.Handler.emit`（PySide6 6.8 的
  Shiboken 把 SignalInstance.emit 误路由到同名实例方法），改写 `handle`
  入口——6.8/6.11 双绿。

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
