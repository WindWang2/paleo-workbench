# 09 — Lifecycle（V10）

## 1. boot 顺序变更（D15；审查 R1-3 修正）

权威钩子在 **`paleo_workbench/__init__.py`**（所有入口的公共第一跳）：

```
load_local_env()          # env_bootstrap；.env 只填空，不覆盖 shell
prepare_bridge_load()     # qgis_runtime/loader；桥 DLL + Qt 预载（幂等）
ensure_geoviz_on_path()   # 之后才允许 geoviz/numpy bootstrap
```

`main.py`（main.py:19–31）保留同一钩子为冗余保险。理由：conda 配方
下桥依赖的 Qt DLL 必须先于 PySide6/geoviz（numpy）的装载——
`import paleo_workbench` 本身就触发 geoviz bootstrap，所以钩子必须在
**包 __init__ 内**，不能只挂在应用入口；顺序错 = 桥导入
ENTRYPOINT_NOT_FOUND（V10 loader 二分实证）。conda 预载时序的两条
审查修正见 01-qgis-runtime.md §5。

## 2. V10 新增生命周期面与守卫

| 新面 | 守卫/清理 |
|---|---|
| 发布账本 weakref 清理 | 栈 GC 时清 token（`_STACK_ID_REFS`，qgis_mirror.py:206 起）——04-layer-registry.md §2 R2 |
| snapping 持久化恢复 | 工程 load 时 `restore_state` + 重推（03-qgsproject-authority.md §3）；stage 切换 `repush_snapping()`（composite_document.py:1255） |
| health 探针缓存 | `probe_qgis_runtime` 进程级缓存；测试经 `reset_runtime_probe_cache()`（health.py:74）显式失效 |
| 画布拆除契约 | **不变**：`shutdown_live_shims` 仍是单点拆除（V8/V9 谱系）；edit_tools 的 bound-method 引用形态维持 V9 限制 #6 的裁定 |

## 3. 压测/回归面（既有，V10 复核）

`test_qgis_lifecycle_stress_v8`（100× 工程切换/工具循环/树重建/
StackEvents 析构竞态）在 0.6.0a0 桥上须全绿——合入前置条件；
V10 新面各自带回归钉（`tests/test_qgis_v10_runtime_foundation.py`、
`tests/test_snapping_persistence_v10.py`）。

## 4. Ops note（构建期教训，记录在案）

**桥构建运行期间禁止 `git stash`**：构建进程持有输出树文件锁，
mid-stash 锁冲突会留下半换的脏工作树（部分文件被 stash、构建产物
半写）。本 worktree 构建期（`.scratch/build_bridge_v10.ps1`，
`PALEO_QGIS_REUSE_VENDOR=1` 复用 vendor）实际踩中，人工修复。
规程：桥构建进行中只读检查，改动等构建结束；需要中途放弃时先停
构建进程再动 git。
