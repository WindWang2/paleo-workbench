# 07 — Review Findings Record（3 轮）

## Round 1 — correctness / regression / GIS semantics

| # | 严重度 | 发现 | 处置 |
|---|---|---|---|
| 1 | P1 | legacy mapping_page 未喂 current_tool/snapping/topology 真值，apply_availability 统一写 checked 后捕捉/拓扑开关被恒置未勾选（无法关闭） | 已修：页面 context 喂三态权威 |
| 2 | P2 | palette 的 map:snapping/topology 经 isChecked() 分派是静默空操作 | 已修：以控制器权威取反分派 |
| 3 | P2 | _sync_action_state 原生探针优先是死代码（apply_availability 覆盖 checked） | 已修：删除第二写者，探针保留为检测 API |
| 4 | P2 | 三处门序偏离文档（layer-fact 先于 project；stage 覆盖角色判词；style_manager layer 先于 backend） | 已修：门序对齐 + 语义精确化 |
| 5 | P2 | 命令拒绝分支不回同步 checkable 翻转 | 已修 |
| 6 | P2 | repair 探针 raw_locked/stage_locked 活动层渗漏 | 已修：按点击图层替换 |
| 7 | P2 | build_tool_context 把显式 "" stage 强转为 None | 已修：保留 ""（fail-closed） |
| 8 | P2 | topology_error_count 无宿主生产者（合并拓扑门永不触发） | 预存（B 时代即如此）；保留契约字段，记录于 known limitations |
| 9 | P2 | 选择类工具 layer gate 从矢量放宽为任意层（raster 不可达但契约不完整） | 已修：select/select_rectangle/选择命令要求矢量 |
| 10 | P2 | select 工具 palette 侧 raster 不可判定 | 已修：snapshot 增 active_layer_is_raster |
| 11 | P2 | save_edits 对 edit_gate_open=None 放行 | 已修：fail-closed |
| 12 | P3 | _apply_tool_availability 每工具 explain 两次 | 已修：一次求值复用 |

清白区：blocking 无死锁路径（blocking_task_label 生产赋值为空）；mapping_page 迁移语义与旧 B 等价；palette 适配整体健全；artifact_keys 四处消费零行为差。

## Round 2 — architecture / duplication / authority boundaries

| # | 严重度 | 发现 | 处置 |
|---|---|---|---|
| 1 | P1 | 阶段面板动作 + stage:* palette 完全绕过 evaluator（无 re-gate） | 已修：STAGE_ACTION_TOOLS 单一词表 + stage_action re-gate |
| 2 | P1 | 树面板 context menu 用 metadata editable 旗标自判，RAW 层无属性表（与 evaluator 矛盾） | 已修：查看/导出类对任意注册图层开放 |
| 3 | P2 | checked 双写者 + 原生优先死逻辑 | 已修（同 R1-3） |
| 4 | P2 | capability_model.LayerCapabilitySnapshot 死代码第二门禁表 + with_capability 零消费者 | 已修：删除（测试同步迁移） |
| 5 | P2 | 同名快照类型双处定义（manifest vs runtime） | 半修：capability_model 侧死类型已删；tool_surface.QgisCapabilitySnapshot（runtime 三态）保留并在 docstring 标注概念区分 |
| 6 | P2 | 适配器 vector_writable 从 editable 推断（事实混同） | 已修：active_layer_writable 独立字段（provider 接线） |
| 7 | P2 | legacy 页 loose heuristics（split_ready=selected>0） | 预存行为等价迁移；记录 known limitations |
| 8 | P2 | evaluate_all 双导入路径 | 已修：composite 直连 |
| 9 | P2 | labels/快捷键三处手维护 | 已修：action_help 单一来源，测试对 QAction 注册钉一致 |
| 10 | P2 | explain_action 零消费者 | 保留为公共 API（M4 承诺面），Inspector 接线记录 known limitations |
| 11 | P2 | stage_profiles docstring 指向旧 TOOL_GROUPS 归属 | 已修 |
| 12 | P2 | 三个 evaluator 测试文件重叠钉 | 记录为后续合并建议（不阻塞） |

清白区：setEnabled 全扫无 map 工具业务重复；无 .reason 鸭子双读残留；tool_surface 无 gate 规则；无循环导入；update_state/hidden_by_stage_profile 全删；native/ 与 submodule 零改动。

**裁决**：单一真源主张在分支触及的表面成立；两处未及表面（阶段面板、树菜单）按 R2-1/R2-2 修复后，「所有表面是呈现投影」成立。

## Round 3 — UX / performance / adversarial / lifecycle

| # | 严重度 | 发现 | 处置 |
|---|---|---|---|
| F1 | **P0** | review-1/2 修复引入 topology 分派 NameError（enabled 局部变量残留）；工具条+palette 每次拓扑切换必炸 | 已修 + 补 topology/snapping 分派测试（该路径此前零覆盖） |
| F2 | P2 | 溢出菜单禁用原因 tooltip 不可见（QMenu 默认不显示）+ 三种原因格式 | 已修：setToolTipsVisible(True) + statusTip 词汇统一 |
| F3 | P2 | blocking 期间阶段隐藏组以 disabled 闪现（toolbar 库存churn） | 已修：表面存在性裁决先于 blocking 早退 + 回归测试 |
| F4 | P3 | 负 selection_count 使选择命令可用 | 已修（<= 0） |
| F5 | P3 | blocking 期间 pan checked 熄灭（enabled 条件过严） | 记录 known limitations（保守语义的代价，刻意取舍） |
| F6 | P3 | pan 自身失败的消息谎称「已回退」 | 已修 |

实测（offscreen/fallback）：evaluate_all 0.16ms/次；tool_availability() 0.60ms/次；全工具条刷新含 help 1.93ms/次（预算 50ms）；700 畸形上下文 + 200 随机变异 × 45 工具 0 异常 0 不变量违例；构造+50×分派+50×刷新+关闭 ×3 无异常无悬挂；主题切换 ×3 无 stale callback；双失败/pan 失败/blocking 中失败无递归。
