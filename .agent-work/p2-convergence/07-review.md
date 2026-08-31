# P2 Review — Matt code-review (mattpocock-skills), fixed point origin/main

三轮（两轴并行子代理 + 修复验证轮）。Findings 分级 BLOCKER/HIGH/MEDIUM/LOW。

## Round 1（两轴）

Standards 轴 + Spec 轴共 **0 BLOCKER / 6 HIGH / 9 MEDIUM / 6 LOW**，全部修复（de0eec39）：

| 级别 | 发现 | 修复 |
|---|---|---|
| HIGH | admission 钩子在调度器锁内执行（违反文档契约，慢采样会串行化双车道） | 候选弹出到锁外执行 admission；claim 段重校验状态 |
| HIGH | background_nice 启动竞态（线程先于配置启动→恒 0） | 构造时从预算读取（default_background_nice） |
| HIGH | 动作族缺失（apply_template / create_interpretation 等） | 新增 map.apply_template、geology.create_interpretation（真实 fault lifecycle）；其余四个（well/seismic 解释类、workflow.run_step）记录为诚实范围（见 08 已知限制） |
| HIGH | compute_attribute 默认 /tmp 输出、kriging 无 catalog 产物 | 输出默认进 workspace artifacts；create_factor_map 注册 DataRun + INTERMEDIATE npz + 返回 version identity |
| HIGH | 验证在提交之后（invalid output 可能已提交成功 run） | grid 科学验证先于 publish/注册；attribute provider 注册前探测输出有效性 |
| HIGH | 文件系统边界不一致（seismic 路径任意） | `_resolve_volume_path` 工作区约束 |
| MEDIUM×9 | 导出拒结名义成功 / WRITE 默认授权 / from_app 私有属性 / 预警 provenance 缺 outputs（结构性，记录）/ monitor 私有字段 poke / 占位 viz provider / 魔法参数走私 / clamp 布线重复 / 预算无 env 路径 | 全部修复或记录 |
| LOW×6 | 命名/死参数/deferred FIFO 等 | 修复 |

## Round 2（验证轮）

**1 HIGH / 2 MEDIUM / 4 LOW** → 全部修复（323f9094）：

- HIGH：相对路径穿越（`../..`）绕过工作区约束 → resolve-then-contain（两分支都检查）
- MEDIUM：调度器 claim 非原子（双 worker 双跑 + lease 泄漏；cancel 窗口竞态）→ QUEUED→RUNNING 在 claim 临界区内原子翻转
- MEDIUM：渲染后端异常路径泄漏 → try/finally shutdown + 前置格式检查
- LOW×4：set_background_nice 文档 / 注册失败遗留 running DataRun → fail-run / geology 文档 / SDK 级 output_path（开发者面，动作面已约束）

## Round 3（终验）

全部 VERIFIED；剩余 1 LOW（cancel-vs-claim 微秒窗 KeyError）→ 修复（73c8bc74）。
最终 sweep：**BLOCKER = 0，HIGH = 0**。

## 附带的全量回归发现

`tests/test_geoviz_package_independence` 因新增 `geoviz_seismic.cache` 直连而失败 → 以 vram_cache 先例补窄豁免（带注释）。其余 2 个失败（map_edit_core / welllog binding）在 clean main 同样失败（缺已构建可选 C++ 扩展——P1 已知环境限制，非回归）。
