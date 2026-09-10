# 00 — Baseline：V10 起点（main @ 3b0e2ba2）

## 已有基础（不再重建）

* **单一 availability 权威**（V8 M1）：`mapping/tool_availability.py` 是
  45 工具/12 组的唯一业务判定源；`ui/workstation/tool_surface.py` 是呈现
  适配器；执行前 re-gate 覆盖工具条/palette/shortcut/阶段面板
  （`_on_tool_requested` / `_on_command_requested` / `stage_action`）。
* **两行工具条已入 QMainWindow 宿主行**（bdc3a664）；分隔符孤儿治理
  （`_sync_toolbar_separators`）；overflow 交给 Qt 原生扩展。
* **Dock framework V2**（V9）：声明式 DockDescriptor + viewport 分类 +
  resizeDocks 策略 + GL dock 不可浮动——本方向零重写。
* **CRS 契约**（V9 W3 `crs_contract.py`）：未声明即「未声明」，绝不静默
  4326。
* **角色捕捉 profile**（V9 W4）+ 拓扑运行时计数（W2）+ 捕获 spec（W9）。

## 起点审计发现（三路 subagent 审计汇总）

| # | 发现 | 等级 |
|---|---|---|
| F-1 | 回退树右键菜单编辑入口只看 `metadata.editable` 旗标，RAW/冻结/组锁/阻塞的禁用原因进不了菜单 | P1（本方向核心命题） |
| F-2 | 原生树面板 remove_button 同样旗标判断 | P2（结构性删除语义，保留但记录） |
| F-3 | `_repair_layer` 执行 re-gate 只复查角色门禁，缺 kind 门禁（原生面板信号路径） | P1 |
| F-5 | 阶段面板按钮无 per-item 门禁（执行时统一拦截——语义一致，呈现弱） | P2（保留） |
| F-6 | 「捕捉设置…」常驻（与 toggle 门禁不一致——配置面语义，保留） | 记录 |
| F-9 | `NativeLayerTreePanel`（独立遗留）全自判 | P2（遗留面） |
| F-11 | 树缩放三处判据略漂移 | P2 |
| F-12 | palette 快照保守适配（执行侧兜底——设计内） | 保留 |
| F-14 | Agent WRITE 授权体系与 evaluator 正交（会合点 = UIContext.write_granted） | 记录 |
| G-1 | `write_granted` 字段在生产从不填充（死字段）；`reshape_ready` 采集未消费 | P2 |
| G-2 | `STAGE_CONTEXT_ACTIONS` 与 `StageToolProfile.context_actions` 三表漂移 | P1（词汇单源化） |
| G-3 | palette 阶段判词与 evaluator 措辞两套 | P2（M10 修） |
| G-4 | 无画布右键菜单 | P1（M7 补） |
| G-5 | 无编辑会话/dirty/拓扑错误/CRS 不一致/选择计数的持久状态呈现 | P1（M4 修） |
| G-6 | palette 缺 split/merge/reshape（V8 08 #1）与 inspector 入口（V9 08 #8） | P2（M9 修） |
| G-7 | Inspector explain_action 接线缺失（V8 08 #9） | P2（M11 修） |
| G-8 | `tool_help.py` 尾部死代码（引用未导入名字的重复 explain） | P2（清理） |
| G-9 | state_changed 风暴全量刷新（explain 重拼占大头） | P2（M12 修） |

## V10 变更总览

```
mapping/action_registry.py            [新] 动作元数据登记处（身份，非可用性）
mapping_workspace/stage_vocabulary.py [新] 阶段动作词表单一真源
mapping/tool_context.py               v4：捕捉配置/CRS 呈现/计数事实（附加式）
mapping/tool_availability.py          cancel 豁免阶段隐藏（P1 修复）；判词措辞真源
ui/workstation/composite_document.py  树菜单探针/画布菜单/状态条投影/推荐动作
ui/map_status_bar.py                  v2：编辑 chip/拓扑 chip/CRS 警示/比例尺/捕捉详情
ui/workstation/tool_surface.py        LayerMenuFacts + palette 适配扩展
ui/workstation/ui_context.py          split/merge/reshape_ready + native 能力快照
ui/workstation/shell.py + app_shell.py palette 注册扩展
tokens.py                             QToolButton[preferred] 弱提示
visual_qa_v10.py + 3 个测试文件       [新] 语义门禁
```
