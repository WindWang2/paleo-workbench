# 08 — Review findings & verification（V9）

## 1. 轮次

| 轮 | 方式 | 覆盖 |
|---|---|---|
| R1 架构 | 独立 subagent（8 条权威规则逐条核） | 第二 evaluator/角色真源/捕捉配置/CRS 真源/fallback 扩张/桥 API 纪律/生命周期/契约漂移 |
| R2 编辑正确性 | 独立 subagent（7 面对抗场景，含 offscreen Qt 实证脚本） | 拓扑计数/捕捉对话框/捕获 spec/CRS 守卫/属性表/测地测量/镜像验证 |
| R3 lifecycle/perf | 主 agent（压测矩阵 + 门禁 + 同机基线对照） | 工程×100 循环、缓存回收、计数刷新、perf 门 |

## 2. 发现与处置（全部 P0/P1 清零）

| ID | 级别 | 发现 | 处置 |
|---|---|---|---|
| R1-1/R2-1 | **P0** | 属性表 bool 编辑器 `setEditorData` 硬编码 index 0——打开 "false" 单元格按 Enter 翻转为 "true"（数据损坏路径） | 编辑器落在当前值（findText）+ 回归测试 |
| R2-1 | **P1** | 排序态差量刷新错行（Qt 在排序列 setData 即时重排，循环内 row 查找解析到别的要素——offscreen 实证 f1 显示 f2 的值） | 更新期间禁排序 + 行映射重建 + 4 要素回归测试 |
| R2-2 | **P1** | 拓扑计数跨会话复活：rollback 后新会话继承旧计数 → merge 门假拦（实证） | 缓存条目携带 session 身份；新会话=未校验；rollback/删除/切换三路径 forget |
| R2-3 | **P1** | `geometry_command` finally 只刷新活动层——split 可改写非活动 polygon 层（`_split_inputs` 回退扫描），split 引入的拓扑错误对 merge 门不可见 | 按实际触及集合刷新（mutated_layers） |
| R1-1 | **P1** | 5 处存量 quiet-4326（面板发布×2、状态条、因子提取、原型）与新契约自相矛盾 | panel_publish_crs/「未声明」呈现/记录在案的 legacy fallback |
| R3 | **P1** | `load_from_project` 层集全替换不清 per-layer 捕捉覆盖与拓扑计数——同名层 id 复用时复活过期配置（压测发现，真 bug） | 四通道 + forget_all 清空 + 回归钉 |
| R2-2 | P2 | Range 字段非数值文本绕过范围门（批量路径无校验器） | 带域字段拒绝非数值 |
| R2-3 | P2 | per-layer `intersection` 推荐在 native 无对应物且无告警 | 降级告警覆盖 per-layer 态 |
| R2-4 | P2 | 测距工具跨工程 Geod 过期；预览平面值被标「测地」 | 工程切换显式重建；预览经工具 `_measure` 重算 |
| R2-5 | P2 | CRS 守卫对散文式 CRS（"WGS 84"）假拒绝 | 仅 auth-id 形态（含 ":"）比对 |
| R2-6/R1-P2-6 | P2 | profile 应用不复活被禁用层 | apply 同时置 layer_enabled=True（docstring 记语义） |
| R1-P2-2 | P2 | Geod WGS84 替换静默 | 替换记日志 |
| R1-P2-5/R2-P2-8 | P2 | 宿主触 TopologyService 私有 `_error_counts` | forget_all API |
| R1-P2-7 | P2 | 行推荐改全局模式框（工程级副作用） | 保留（文档化：per-row 无法表达 endpoint/midpoint/intersection） |
| R1-P2-8 | P2 | 测量用工程 CRS 而非画布目标 CRS（镜像降级时偏差） | 09 记录（低频边角） |
| R1-P2-3 | P2 | CRS provider bound-method 强引用（无 detach） | 与 `_tool_controller` 同形态；09 记录 |
| R1-P2-4 | P2 | 对话框打开期间角色变化列缓存陈旧 | 09 记录（瞬时对话框，有界陈旧） |
| R1-P2-9 | P2 | 压测假工程属性名笔误 | 修正 |

**R1 结论**：八条权威规则全部 CLEAN（无第二 evaluator/角色/捕捉/CRS
真源；桥 API 三新增全部满足进入标准；fallback 无越权能力——测地 fallback
对齐原生椭球语义）。

## 3. 测试环境性失败（非 V9，同机基线对照证据）

| 测试 | 现象 | 基线对照 |
|---|---|---|
| `test_qgis_bridge_gil_contract::test_optional_module_still_importable_when_built` | 同文件先跑 3 个源码契约测试后桥 DLL 加载失败（单测独跑通过） | v8-spatial worktree 同失败 |
| `test_qgis_layer_panel_menu` teardown error | QMenu C++ 对象已删（测试侧悬空引用） | v8-spatial worktree 同失败 |
| `tests/perf/test_mirror_publish_scale::test_full_first_publish_within_budget[50]` | 167.6ms vs 60ms | v8-spatial worktree 同失败（CI 覆盖） |

## 4. 最终验证记录

- **qgis-marked 批次**（0.5.0a0 桥 + vendor bin 配方）：47 文件全绿
  （除上表 3 项预存环境项）——含 V8 全量 provider-fields/row-indicators/
  lifecycle-stress/identify/select/topology 面与 V9 新面。
- **host 面**：authoring contracts 165、tool state 106、topology 13、
  composite editing 18、GIS 36、attribute differential、stage e2e/teardown、
  perf lifecycle 6 —— 全绿（详见 05-verification 数据在 CI 复跑）。
- **V9 新增测试**：interaction facts 20、snapping capture 19、schema
  attribute 13、bridge surface 5（qgis）、lifecycle perf 5、review fixes 6。
- **桥构建**：`PALEO_QGIS_REUSE_VENDOR=1` 复用 authoring-v7 vendor build，
  仅链桥扩展 ~2min；vendored QGIS 未重建。
