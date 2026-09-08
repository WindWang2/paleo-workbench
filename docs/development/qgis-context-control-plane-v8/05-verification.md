# 05 — Verification（V8）

全部验收本地完成（无 CI 依赖）。测试环境：Windows / offscreen Qt
（`QT_QPA_PLATFORM=offscreen`）/ 项目 `.venv`（Python 3.12.13 + PySide6
6.11.2，与 vendored QGIS 的 conda Qt 同源）。本机全量单进程易崩 →
`scripts/run_suite_batched.py`（每测试文件一进程 + 崩溃重试一次）。

## 分层测试证据

### 1. 契约纯函数层（无 Qt）

| 文件 | 覆盖 | 结果 |
|---|---|---|
| `tests/test_tool_state_contract_v8.py` | 26 状态矩阵 × 45 工具（工程/图层 RAW~published/missing/degraded/raster、编辑 clean~dirty/topology-blocked、阶段 1/2/3/未知/无语义）+ 不变量（禁用必带原因）+ palette↔toolbar 同因 + native manifest 门禁 + checked 语义 + 阶段组可见性 + 门序优先级 + 阻塞期隐藏回归 | 全绿 |
| `tests/test_authoring_contracts.py` | capability manifest 探测/降级 + evaluator 逐工具钉（A 谱系迁移） | 全绿（1 skip：桥探测） |
| `tests/test_tool_surface.py` | adapter 语义（B 谱系迁移：快照往返、组覆盖、fail-closed） | 全绿 |
| `tests/test_action_help_v8.py` | M4 帮助登记处完整性 / evaluator 派生 / 格式化 / 词表与 QAction 一致 | 全绿 |

### 2. QAction 集成层（offscreen Qt）

| 文件 | 覆盖 | 结果 |
|---|---|---|
| `tests/test_tool_surface_integration.py` | 真实 CompositeDocument：原因流到 tooltip/statusTip、RAW/冻结/几何门禁、组可见性、**execution re-gate（命令+工具双路径拒绝与回同步）**、topology/snapping 权威分派 | 全绿 |
| `tests/test_stage_tool_filtering.py` / `test_mapping_stage_ui.py` / `test_mapping_stage_e2e.py` | 阶段切换 → evaluator 单点推导的可见性、RAW gate 覆盖工具条+修复路径 | 全绿 |
| `tests/test_workstation_authoring_kernel.py` | kernel 采集器（tool_context_inputs 全量 dict）× CompositeDocument 集成 | 全绿 |
| `tests/test_visual_qa_v7.py` / `test_visual_qa_v6.py` | 既有 8+6 状态语义门禁（回归） | 全绿 |

### 3. 视觉 QA V8（M7）

`tests/test_visual_qa_v8.py`：6 个新确定性状态（空工程表面 / 编辑 dirty /
冻结成果 / palette 禁用原因 / **原生激活失败回退** / 阻塞任务工具面），
每个状态截图驱动 + 语义断言（非像素 diff，D8 政策）。

### 4. 性能 / 生命周期（M8）

`tests/test_perf_lifecycle_v8.py`（结构断言 + 宽松 wall-time）+ review-3
实测：

| 指标 | 预算 | 实测 |
|---|---|---|
| evaluate_all（45 工具纯函数） | < 1ms/次 | **0.16 ms**（3.6µs/工具） |
| 10k→100k 迭代 | 线性（ratio 8–13） | 通过 |
| tool_availability()（re-gate 用） | 便宜 | 0.60 ms/次 |
| 全工具条刷新（含 M4 help 文本） | < 50ms | 1.93 ms/次 |
| extent pan/zoom | 不触发全量 recompute | **0 次**（计数断言） |
| 500 层 25 次活动层切换 | < 2s | 通过 |
| 50 次重复命令分派 | 状态无漂移 | 通过 |
| 畸形上下文（700 个）+ 随机变异（200×45） | 0 异常 0 不变量违例 | 通过 |
| 构造+50×分派+50×刷新+关闭 ×3 | 无异常/悬挂 | 通过 |
| 主题切换 ×3 | 无 stale callback | 通过 |

### 5. 全量套件（最终提交状态）

`run_suite_batched.py` 全量：**见 PR body 最新数字**。预存基线失败
（干净 `d5181cb3` 上同样失败，与本分支无关）单列于
`08-known-limitations.md` #12。
