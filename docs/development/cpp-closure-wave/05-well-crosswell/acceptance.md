# 05 — acceptance.md（验收清单，最终快照 2026-09-20）

状态图例：✅=已实现且有测试证据 | 🚫=明示不做（归属他线）

**门禁快照（verify.sh run1，全程 invoke-resource-gate.sh，j4 build / j2 test）**：
- configure ✓（Release，PLATFORM+DATA+SCIENCE+VIZ_B+CONV_29+MAPPING_KERNEL+SCIENCE_VIEWER）
- build ✓（本线闭包 + viz_a/viz_b 回归二进制）
- test1 = test2 = **20/20 Passed（两遍，确定性回归）**
- MALLOC_CHECK_=3：**7/7**（well.* + ui_workers.*）
- **pwb-platform 完整构建+链接 ✓**（main_window 05 钩子 + well_presenter_install + viz_a/viz_b 安装块真编译进生产二进制，非仅编译覆盖）

## 本线验收项（任务书逐条）

| 项 | 状态 | 证据 |
|---|---|---|
| XML worker 真加载（WITSML/SpreadsheetML → WLE 文档，与 LAS 同载荷型） | ✅ | well.load_path（真文件→真文档曲线/井名/区间/标记）+ ui_workers.well_xml（oracle 对账 6 案例 + 比较器负检 + 输入篡改负检） |
| LAS/XML 真文件通路（真解析非占位） | ✅ | make_wle_load_fn 分派；非井 XML/坏文件诚实 nullopt |
| 不同深度单位 | ✅ | LAS m/ft fixtures（轴单位断言）；XML 深度单位诚实未声明（冻结 Python 语义） |
| 缺曲线 | ✅ | well_b_ft_reverse.las 单曲线 → curves==1 |
| 反向深度 | ✅ | LAS 降序 + WITSML 降序 → AxisDirection::decreasing |
| 取消与迟到结果 | ✅ | ui_workers.lifecycle（检查点取消/resolve 取消传播/DTW start-cancel/task_key 迟到废止/取消后部分结果/双跑逐值一致/有界关闭）；dock 级迟到投递代际丢弃（well.dock_lifecycle）；dock LAS 加载 JobCenter 化带进度取消 |
| 对象销毁（真实 dock 非仅编译） | ✅ | well.dock_lifecycle：真实 dock+JobCenter，在飞 DTW 下按生产析构序销毁，事件循环排空无 UAF |
| 编辑重开可复现 | ✅ | well.dock_lifecycle：真实 DTW 拾取 → sidecar → 重开 → picks JSON 逐值相等；迟到的第二次 DTW 不得改动已恢复拾取 |
| 标定数值可复现 | ✅ | dock tie 读数两次逐字符一致（真 AC+DEN 数据出真 R/lag）；内核 viz_b.well_tie.oracle Passed |
| 跨工程切换 | ✅ | well.dock_lifecycle：A→B（无 sidecar）工作区清空不串扰 → 切回 A 逐值恢复 |
| B 的真实 LAS 数据通路 | ✅ | viz_b_well_source + dock LAS 按钮（JobCenter 异步）；well.vizb_las_path（null 对剔除/错误聚合/坐标诚实空） |
| A 的共享井身份 | ✅ | well_identity registry + viz_a/viz_b 注册；ui_workers.well_xml 身份语义；dock 测试 find_by_name |
| 04 能消费 presenter | ✅ | well.presenter_flow：真实 VizEDataPage.preview_asset → well_log（真 WLE 曲线页）/time_depth（真校准对+标定核探针页）；非井 XML 诚实诊断页；重复注册响亮拒绝 |
| 连井会话恢复 | ✅ | sidecar well_source_las 自动重载 + 恢复逐值断言（well_source 字符串旧格式兼容不破坏） |
| 结果来源显示 | ✅ | dock source_label_（井来源 JSON/LAS + 最近结果出处：banded 引擎/会话代际/拾取数） |
| pattern 近似与导出行为复验 | ✅ | viz_a.patterns Passed（oracle 复跑）；viz_b.integration Passed（报告/剖面 SVG+PDF 导出+重开身份）；viz_b.engines_example Passed |
| 只向 04 提供 well/time-depth presenter（接口边界） | ✅ | 外部面仅 ExternalPresenter("well_log"/"time_depth") + WellIdentityRegistry 只读；无其他 04 依赖 |

## 附带修复（既有缺陷，本线文件内）
- **viz_b dock 的 DTW 按钮从未绑定 correlate_fn** → 真实作业路径恒 "kernel unavailable" 失败（B 线集成测试直接调 compute 绕过了 dock 路径，故未暴露）。已注入真 banded 核 `dtw_engine_correlate`（seam 仍可注入，未写死第二实现）。

## 跨线交接
- →04：ExternalPresenter("well_log"/"time_depth")（viz_e 注册表；生产注册在 main_window 的 05 标记块）+ WellIdentityRegistry::find/find_by_name/snapshot 只读。
- →06：井身份 seam 不变；本线 registry 独立、确定性 id 可对账。
- →13/04：发现登记——libs/ingest/preview/well_log_xml_preview.cpp 的 SpreadsheetML 分支未处理 ss:Index 列偏移（冻结 Python 有；同文件预览与加载可能列错位）。属 04 的解析注册表文件，本线不越线修改。
- 报告模板短写：未改 report_export 模板字段（复用 B 线已合并实现），如 13 发现短写缺陷按其流程修。

## 明示不做
- 井震 3D（06）；WLE SDK 本体修改（外部依赖，只读复用）；MainWindow/AppShell 全局结构（12，本线仅一个标记块钩子）；ingest 预览注册表文件（04）。

## 环境限制（如实）
- 本机无 numpy/pip/PySide6 → oracle 模式 A（真实冻结 Python 实测）未执行；已提供双模式生成器（tools/oracle/generate_well_xml_fixtures.py），模式 B（冻结源行号级转录）为交付口径；恢复条件=具备 numpy 的 Python 环境。
- 真实 GL 硬件像素验证未做（offscreen + 软件 GL；viz_a.viewer_flow 以显示器条件化 Passed）；如需真 GL 证据需有显示环境。
- 资源门为全主机共享锁：本次 verify 的排队等待跨 03/04/06/12/14 线共约 6 小时（记账见 progress.md）。
