# 08 — 已知限制(本轮明确不修,含理由)

| 项 | 理由 |
|---|---|
| D-08 CompositeDocument rebuild_composition / LayerManagerPanel canvas hook 完整接线 | 独立子史诗(复合面板产品接线,与 #1446 约束链正交);本轮只接通约束创作主链 |
| F-10 surface_state 统一状态词汇全面接入 | UI 统一属独立 UX 线;库保留待接线(矩阵如实标注) |
| N-4 CI nightly perf SLA(test_zoom_pan_sla 20.09s vs 16) | 需基准环境归因(2 核 CI vs 本机不可比);非本轮代码回归 |
| #1429 Windows offscreen 崩溃家族根因 | 需 Windows core dump;#1434 已隔离为独立步 |
| B-03 WorkerHost shutdown 超时后的 epoch 重构(双 body 并发) | 触发前提是先发生 shutdown 超时(长内核);#1449 的 generation 已封 busy_ 篡改面;完整 epoch 重构留待并发专项 |
| B-07 fallback 后端 threaded 模式锁 | 当前生产 threaded=false(工厂未开线程);开启时需快照原子交换,专项处理 |
| C-07 CONV-29 蕴含语义双源(IMPLIES vs FATAL) | feature-graph 统一重构(PwbFeatures 收敛全部手工 imply)属独立架构线 |
| F-11 reduced 构建行号映射错位 | 仅影响非产品 reduced configure 路径 |
| E-1 推理快照哈希跨语言字节不兼容 | 影响面:Python→C++ 混合世代工程恒判 stale(保守方向,多算不丢数);统一哈希编码器属专项 |
| B-06/B-08/B-10/D-09/D-10/D-11/F-06/F-08 | 已在 #1451 issue 记录;非阻断,后续批次 |
| cpp-close-01 InstalledCatalogClosure 产品接线 | line-12 组合根工作未落地;死 option 已诚实删除(#1444),测试直编覆盖仍在 |
| compile_map/integrated_compilation/map_product 的生产 TU 接线 | #1448 将矩阵改为如实 NOT_WIRED;接线属「先接线再退役」的后续工作(Python 侧仍是生产路径) |

## 环境限制(非代码)

- final-closure-gate configure/all 需本机以 env 注入 vendored SDK 路径(脚本默认 `/home/kevin/main/...` 是他机假设)
- geoviz 族 pytest 需 Python<3.13(本机 3.14);以 venv 外证据替代并记录
- CI runner 积压(main push run 排队 8h+),CI 系列 issue 的关闭依据为代码双重核实+本地复现,待后续 run 佐证

## 本轮新增归类(终审 R-08..R-10 等)

| 项 | 理由 |
|---|---|
| R-08 WorkerHost generation 残留竞态(检查点横跨 shutdown+重启) | 需 shared_ptr<atomic> per-generation 重构;概率极低,专项做 |
| R-09 project_controller workarea 段 worker 调 host_ | 控制器尚未接产品(line-12);接线时一并做 |
| R-10 测试空白(mirror dance 多覆盖、fingerprint oracle 值、双脏层关闭) | 补测试专项;主链已有测试区分度(负对照实证) |
| final-closure-gate `all` 口径:build 只编 pwb-platform 而 tests 期望全部测试可执行 | 脚本缺陷(非分支回归,基线同样失败);修复=build 阶段加测试目标。已在 09 记录等价证据(gate Test vs native-product:71/71) |
| geoviz 族 pytest(Python<3.13 约束) | 本机 Python3.14;以 ctest 对应 C++ 测试+作者本地记录替代 |
