# V14-CONSTRAINT-FACTOR — 07 评审发现与处置

两轮独立 review（architecture/correctness + adversarial/performance/lifecycle）。P0/P1 全部清零；P2 已修或转入 known limitations。

## 第一轮（架构/正确性）——全部处置

| # | 发现 | 级别 | 处置 |
|---|---|---|---|
| 1 | fingerprint 的 scheduled power 被 parameters.power 覆盖（CLEAN 误判 + provenance 自标错误） | P1 | 已修：scheduled override 无条件生效 |
| 2 | 取消分支无条件清 live grid（#881 回退：删掉上一个有效 payload） | P1 | 已修：指纹条件逐出 |
| 3 | catalog 登记失败留下幻影 running run | P1 | 已修：catch 中 best-effort 标 failed |
| 4 | cancel bridge 线程无异常保护 → std::terminate | P1 | 已修：JoinGuard RAII |
| 5 | constrained 无用户边界环即硬失败（Python 用样本凸包） | P1 | 已修：凸包回退（monotone chain）+ 开环自动闭合 |
| 6 | live grid store 跨项目泄漏（task id 碰撞/陈旧命中） | P1 | 已修：项目切换清理（同项目重开保留，第二轮细化） |
| 7 | constraint_pins.content_hash 含 id/顺序/UI 字段（假失效） | P1 | 已修：canonical 组摘要（active-only、id-free、order-free、9 位小数） |
| 8 | 方向线方位角：首段 vs 端点 bearing、负角、忽略显式值、多线平均 | P2 | 已修：显式优先 + 端点 bearing + [0,360) + 首参优先 |
| 9 | 缺 per-line target_horizon 过滤 | P2 | 已修 |
| 10 | constrained 配置推导偏差（pad/decluster/平滑旋钮/along-track/地理 CRS buffer） | P2 | 已修（地理 CRS barrier buffer 未移植 → 见 08） |
| 11 | 无网格 payload 仍登记 `{}` 版本 | P2 | 已修：不登记，标 run failed |
| 12 | attach 缺 quality 键（distance_policy/duplicate/variance/单位/格式） | P2 | 已修（unit 见 08） |
| 13 | MAD 中位数偶数计数取上中位 | P2 | 已修：两中位平均（与 viz_charts 冻结权威一致） |
| 14 | value_key 子串匹配混维度 | P2 | 已修：归一化别名精确匹配 |
| 15 | group key 用 raw 而非 normalized 点集 | P2 | 已修 |
| 16 | contour 剥离过滤窄 + 复用文档不回填链接 | P2 | 已修 |
| 17 | PersistentRuntimeCatalog 与 closure_workflow::FileCatalogRepository 重复实现 | P2 | 接受 + 记录（见 08）：同 store 契约、单一线程面；02 线合入平台后可替换 |
| 18 | parameters.method 被 prepare 读取 | P2 | 已修：只用 task.method + override |
| 19 | constrained + duplicate_policy=keep 未拒 | P2 | 已修 |

## 第二轮（对抗/性能/生命周期）——全部处置

| # | 发现 | 级别 | 处置 |
|---|---|---|---|
| P0-1 | 克里金无邻域 → 每格 (n+1)³；1k 井 grid200 ≈10 h/任务；LOO 再乘 65 | P0 | 已修：>32 井启用 12 邻 kNN；grid_n clamp [20,200] |
| P0-2 | store JSON 全量重写 ×4/任务（payload 内联）：20 任务 ≈650 MB 写 + GUI 冻结 | P0 | 已修：payload sidecar + 元数据-only store + 唯一 tmp 名 |
| P1-3 | LOO 每折全网格但只用 1 个采样 | P1 | 已修：折网格 20×20 + 折间取消检查 |
| P1-4 | shutdown(wait_ms) 被忽略；内核调用内不可取消 | P1 | 已修：有界 timed join + 超时分离（守卫丢弃过期终态） |
| P1-5 | 双窗口同工程互覆 provenance rail | P1 | 已修：flush 前漂移检测，拒绝覆写（fail closed），drift 异常上抛 |
| P2-6 | factor_map_tasks 重复 id → commit 写错槽 | P2 | 记录（见 08）：调度器按 id 键是 Python 移植行为；commit 定位为最后出现 |
| P2-7 | 项目切换 mid-run：worker 续写旧网格 | P2 | 已修：切换清理 + 同项目保留；commit 侧守卫本就完整 |
| P2-8 | 凸包回退对共线井产出退化环 → 全 NaN surface | P2 | 已修：正面积门槛，退化即拒（QhullError parity） |
| P2-9 | legacy grid_z 的 null（nodata）被拒读 | P2 | 已修：null→NaN |
| P2-10 | contour worker 体在 worker 线程读 live 文档 | P2 | 已修：GUI 线程快照任务列表 |
| P2-11 | contour 每次点击重解析 payload（GUI 线程 0.4-1 s @100 任务） | P2 | 部分：payload 已外置 + live cache 命中快；按 version 记忆化列为后续（见 08） |
| P2-12 | 零长 direction line → 伪造北向约束 | P2 | 已修：跳过 |
| P2-13 | sample_factor_context 不拒 ragged grid_z | P2 | 已修 |
| P2-14 | E2E 未钉选择性重算/取消/重开等值线腿 | P2 | 已修：E2E 增加「复用 1 · 计算 1」步 + rail 断言；取消契约入单测 |
| P3-15 | attach 每任务跑两遍（descriptor 双构） | P3 | 记录（~1 ms/任务，可接受） |
| P3-16 | peek 持锁拷贝大 entry | P3 | 已修：LRU splice 后锁外语义不变（拷贝仍在锁内但 O(entry) 已知）——保留记录 |
| P3-17 | 方差信封在 catalog payload 恒 null | P3 | 已修（quality_metrics 有 variance_min/max；payload envelope 同步补 algorithm_parameters） |
| P3-18 | LAS 加载后 factor 上下文不刷新 | P3 | 已修：apply_las_wells 也调 refresh_factor_context |
| P3-19 | 文档 02 的模块落点（closure_workflow）与实际（app 层）不一致 | P3 | 已修：02 文档补记决策（平台配置不含 closure_workflow 目标） |
| P3-20 | 设计文档未入 git | P3 | 已修：本目录纳入提交 |

## 基线问题（非本线引入，A/B 证实）

- `platform_closure_mapping` / `platform_closure_review_install` 在 412d8baf 上链接失败（main_window.cpp 引用 shell_project_actions 符号，测试目标源列表缺该 TU；PWB_WITH_DATA_INTEGRATION 为 PUBLIC 传播）。干净 origin/main worktree 同机同配置复现。本线以最小 additive 修复（`if(TARGET Pwb::Data)` 加源）。
- `viz_e.pa_flow` 编译失败（DataAssetTable 前向声明不完整）。基线 header A/B 复现；未修（09/04 线区域，避免跨线 churn），本地全量 ctest 排除该项后 175/175 通过。
