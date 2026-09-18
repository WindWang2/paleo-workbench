# CONV-27 Findings — Python screen/panel/action → C++ 状态 → QGIS 原生组件

## Python 真相面（读了什么）

| Python 面 | 语义 | C++ 现状（CONV-27 前） | 缺口 |
|---|---|---|---|
| `mapping_workspace/stages.py` | 三阶段值/标签/别名 | `tool_policy/stages.cpp` 已移植 ✓ | 无 UI 入口 |
| `mapping_workspace/stage_profiles.py` | 每阶段编辑动作集/就绪度检查清单/锁定组 | 未移植 | 检查清单 → `stage_readiness` |
| `mapping_workspace/readiness.py` | 15 个检查实现 + 状态梯（error<warning<info<ok）+ 只提示不阻断 | 未移植 | 全部 → `stage_readiness` |
| `ui/workstation/mapping_stage_panel.py` | 阶段 dock：切换按钮+说明+就绪度清单，只发请求信号 | 无 | `StageDock` |
| `ui/native_layer_tree.py` + 痛点记录 | hide/show 不一致、selection/active 不同步、group 重排丢状态 | MapSession 裸树；MainWindow 用 **row→index** 映射 active layer（分组下错位） | `LayerTreePanel`（join-key 解析） |
| 编辑工具集（select/add_*/delete） | evaluator 已有词表 | 评估器已移植；MainWindow 只接了 pan/zoom/vertex | `EditToolController` + `delete_selected` |
| `ui/map_layer_properties.py` + `map_symbology_bridge.py` | QGIS 原生属性/符号化桥 | 无 | `layer_style`（原生 dialog + QML sidecar） |
| 约束面板（constraint layer list） | 按角色过滤 + 计数 | 无 | `ConstraintPanel` |
| `ui/layout_persistence.py` | QSettings 键约定 + 版本迁移 | 无 C++ 布局持久化 | `WorkbenchLayout` |

## 状态模型判定

- 唯一编辑权威：`ProjectSession → EditController`（QGIS edit buffer 即唯一可变几何状态）。
- 唯一动作可用性权威：`tool_policy::evaluate_all(snapshot)` —— 新工具（select/add_*/delete_selected）只接线不自制门规。
- 阶段语义：`ProjectSession::set_mapping_stage` → snapshot → evaluator 的 stage 白名单（`map_export` 仅综合编图、`factor_workbench` 仅约束阶段）。
- 领域图层身份：`layer_adapter` join key（`pwb/layer_id`），树/面板/约束全部 join-key 寻址，永不用 QGIS layer id 或行号。

## 诚实偏差（当前 C++ 面与 Python 文档模型的差异）

1. `target_horizon`：从 B store 文档 `stratigraphy.target_horizon` 读（无 store → 就绪度诚实报"未设定编图层位"）。C++ 平台尚无层位选择器。
2. 预测任务：C++ 壳无预测面板 → 就绪度"测井预测未关联"warning（ truthful）。
3. `initial_facies_present` detail 计"相面多边形数"而非 Python 的"文档数"（输入粒度不同，语义同级）。
4. `seismic_prediction_confidence` 的 all-mock 判定以"real==0 且有概率摘要"近似（输入结构无 per-task adapter_kind 粒度）。
5. freshness/staleness 恒为最新（freshness 归 CONV-26 workflow 线，接口就绪后接上）。
6. QA 几何问题计数恒 0（QA 面归后续方向）。
7. `initial_facies_crs`：QGIS 新工程自带默认 CRS，"工程 CRS 未设置" error
   分支实际不可达（Python 的 coordinate.project_crs 真可为空）——状态保真
   差异，随 B 侧文档 CRS 面接入后消除。
8. 预测/freshness/QA 输入恒为默认（readiness 中 "测井预测未关联" warning、
   "单因素均为最新"、"QA 无几何错误" 为常量），待预测面板（Science 线）与
   freshness（CONV-26）接上后自然点亮。
10. 验收步骤「保存项目」是分层的：矢量编辑经「提交编辑」走 staged→B
    目录事务；UI 布局在关闭时保存；整工程（工作区 state/QGIS 工程）保存
    归 CONV-26 数据线（file 菜单尚无「保存工程」动作）。
11. 就绪度随动作态刷新（refreshActionStates 一并重算，纯内核无 I/O）。

已接受的既有面：anyDirtyEditSession 只检查活动图层（多图层脏关闭提示
   属后续加固）；edit_indicators_ 对已删节点不显式 removeIndicator（QGIS 视
   图侧按活节点查询，仅遗留无害簿记）；PwbQgisSdk 的 deps 前缀默认值是本机
   路径（cache/env 可覆盖）。
