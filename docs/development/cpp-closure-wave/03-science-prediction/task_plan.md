# 03 — 科学服务与预测推理产品闭环 · Task Plan

- 分支：`codex/cpp-close-03-science-prediction-w1`（独立 worktree：
  `/home/kevin/project/worktrees/cpp-close-03-science-prediction`）
- 基线：`origin/main` @ `06211541ae1ccce22b0d5ba9258ce722170ca98b`（2026-09-19 fetch 确认；
  本地 main 落后 6 提交，不从陈旧分支起跑）
- 执行平台：ZCode 会话，**无 /goal、/goal-loop 命令或技能** —— 采用同语义的文件持久化循环
  （本目录四文件），如实记录。Token 预算上限 360,000,000（含全部子代理累计），完成即停。
- 子代理上限：root ≤3 直接子代理（已用 1 个只读盘点；计划再 ≤1 个独立审查）；每个子代理 ≤3。
- 资源约束：全部 configure/build/ctest 经 `scripts/cpp-migration/invoke-resource-gate.sh`
  （flock 互斥于 git common dir；≥8GiB 内存门；j≤4 默认 j2；CTest j≤2；OMP/BLAS=1）。

## 独占范围（本线拥有）

`libs/closure_science`（新建 Qt-free 核 + Qt 绑定 + 测试）、预测服务适配（catalog→ONNX 推断→
版本/provenance→地图层描述符的生产链）、`libs/ui_wellseis` 预测页 hooks 的生产绑定、
`closure_science_*` CMake 目标。不拥有：14 推理内核优化、06 joint host、07 seismic viewer、
12 app 组合结构、01 持久化、02 编排。

## 闭环缺口（盘点结论，基线 06211541）

1. `IPayloadSource` 只有 InMemory/Unavailable —— 无 catalog 版。
2. science envelope 无 catalog 侧 publisher（`CatalogResultPublisher` 是 volume/PWBVOL1 专用）。
3. 推断链无 C++ 生产服务：Python `inference_service.py`（start/execute/cancel/materialize）
   未迁移；run/result 落库事务（publish_result_transaction/finish_run_transaction）无调用方。
4. 预测页（well_log/seismic）在 `app_shell.cpp` hooks 全空 = "service is None" 守卫。
5. 无任务恢复、无工程身份隔离（旧工程晚到结果）。
6. 模型包→catalog Model/ModelVersion 注册路径缺失（prediction 分支 D1 明确留给后续）。

## 实施计划（轮次）

| 轮 | 内容 | 验证 |
|---|---|---|
| R1 | 盘点 + worktree + 协调登记 + ledger（本文件组） | 本文件 + 03-line.json |
| R2 | `pwb_closure_science` 核：model_registry_seed（ensure_default_models / 注册 ONNX 模型包）、CatalogPayloadSource、CatalogEnvelopePublisher、inference service（start/execute/cancel parity）、providers（demo/tiled_onnx/unknown=fail）、task journal（恢复+工程身份） | 单文件语法/增量编译 |
| R3 | `pwb_closure_science_qt`：`attach_prediction_pages`（两个预测页 hooks 生产绑定 + worker 线程 + 取消 + re-entry）；app_shell 注入（main_window wire_app_shell 命名块租约 + root/apps CMake 命名块） | offscreen smoke |
| R4 | 测试：`closure_science.core`（真实 ONNX e2e + 缺模型/缺 provider/shape/CRS/取消/恢复/晚到/身份对账）、`closure_science.qt_hooks`（页面守卫链 + demo 全链） | 资源门内 ctest |
| R5 | 独立审查（1 个子代理）→ 修复 → 复验 | 审查记录 |
| R6 | 提交/推送/PR + ledger 终稿 | PR URL |

## 预算与心跳

每轮在 progress.md 记录命令/退出码/租约。上下文压缩后先读本目录四文件再续作。
