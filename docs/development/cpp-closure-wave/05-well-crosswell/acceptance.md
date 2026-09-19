# 05 — acceptance.md（验收清单，随轮次更新）

状态图例：✅=已实现且有测试证据 | 🔶=已实现，测试待门禁运行 | ⬜=未做（含原因）| 🚫=明示不做（归属他线）

## 本线验收项（任务书逐条）

| 项 | 状态 | 证据 |
|---|---|---|
| XML worker 真加载（WITSML/SpreadsheetML → WLE 文档，与 LAS 同载荷型） | 🔶 | wle_xml_load.cpp + well.load_path 测试；oracle well_xml_oracle.json（模式 B 转录，模式 A 本机 numpy/PySide6 缺失——如实声明） |
| LAS/XML 真文件通路（真解析非占位） | 🔶 | make_wle_load_fn 分派；well.load_path 断言真曲线/真单位/真诊断 |
| 不同深度单位 | 🔶 | LAS m/ft fixtures（轴单位断言）；XML 深度单位诚实未声明（Python 冻结语义） |
| 缺曲线 | 🔶 | well_b_ft_reverse.las 单曲线 → document.curves()==1 断言 |
| 反向深度 | 🔶 | LAS 降序 fixture → AxisDirection::decreasing；XML 降序 fixture 同 |
| 取消与迟到结果 | 🔶 | ui_workers.lifecycle（检查点取消/取消传播/task_key 迟到废止/部分结果）；well.load_path 取消检查点 |
| 对象销毁（真实 dock 非仅编译） | 🔶 | well.dock_lifecycle：在飞 DTW 下 delete dock + 事件循环排空 + shutdown_workers |
| 编辑重开可复现 | 🔶 | well.dock_lifecycle：DTW 拾取 → sidecar → 重开 → picks JSON 逐值相等 |
| 标定数值可复现 | 🔶 | dock 级：tie 读数两次逐字符一致 + checkshot 真数据；内核级：既有 viz_b.well_tie.oracle（复验见下） |
| 跨工程切换 | 🔶 | well.dock_lifecycle：A→B（无 sidecar）清空不串扰 → 切回 A 逐值恢复 |
| B 的真实 LAS 数据通路 | 🔶 | viz_b_well_source + dock LAS 按钮 + well.vizb_las_path（null 对剔除/错误聚合/空坐标诚实） |
| A 的共享井身份 | 🔶 | well_identity registry + viz_a_install/viz_b dock 注册 + ui_workers.well_xml 身份语义 + dock 测试 find_by_name |
| 04 能消费 presenter | 🔶 | well.presenter_flow：真实 VizEDataPage.preview_asset → well_log/time_depth 真页面 + 非井 XML 诚实诊断页 |
| 连井会话恢复 | 🔶 | sidecar well_source_las 自动重载 + 恢复后逐值断言 |
| 结果来源显示 | 🔶 | dock source_label_（井来源 + 最近结果出处：引擎/会话代际/拾取数） |
| pattern 近似与导出行为复验 | ⬜ | 待门禁：viz_a.patterns + viz_b 导出/报告测试在受影响集重跑，结果记 findings |
| 只向 04 提供 well/time-depth presenter（接口边界） | ✅ | 外部面仅 ExternalPresenter 注册（kind well_log/time_depth）+ WellIdentityRegistry 只读查询；无其他 04 依赖 |

## 复用面（不重复实现，已核对在 main）
- WLE LAS 解析（viz-a）、DTW（well_science + ui_workers banded）、标定/合成/auto-tie（VisualizationWellTie）、轨道绘制（VisualizationWellLog）、cross_well 模型/画布/报告（VisualizationCrossWell[Qt]）、JobCenter、sidecar 持久化、ingest LAS 预览。

## 跨线交接
- →04：ExternalPresenter("well_log"/"time_depth") + WellIdentityRegistry::find/find_by_name/snapshot 只读。
- →06：井身份 seam 不变（ui_wellseis JointHostController 属 06；本线 registry 独立、确定性 id 可对账）。
- →13/04：**发现登记**：libs/ingest/preview/well_log_xml_preview.cpp 的 SpreadsheetML 分支未处理 ss:Index 列偏移（冻结 Python xml_preview.py L87-97 有）——预览与加载对同文件可能列错位；属 04 的解析注册表文件，本线不越线修改。
- 报告模板短写：与 13 的分工——本线未改 report_export 模板字段（复用 B 线已合并实现），若 13 发现短写缺陷按其流程修。

## 明示不做
- 井震 3D（06）；WLE SDK 本体修改（外部依赖，只读复用）；MainWindow/AppShell 全局结构（12）；ingest 预览注册表文件（04）。

## 环境限制（如实）
- 本机无 numpy/pip/uv → oracle 模式 A（真实冻结 Python 实测）不可执行；已提供双模式生成器，恢复条件：装有 numpy(+PySide6) 的 Python 环境。
- 资源门为全主机共享锁，本线所有重型命令经 invoke-resource-gate.sh；排队期间仅做轻量工作。
