# 05 — progress.md（轮次记录）

预算口径：根任务 + 子代理累计 token（上限 3.6e8，为上限非目标）。
累计：~3.1M（勘察子代理 2.61M + 根会话估算 ~0.5M）。

| 轮 | 改动 | 验证 | 结果 | 下一步 |
|---|---|---|---|---|
| 1 | fetch origin（main=06211541，与任务锚点一致）；建分支 codex/cpp-close-05-well-crosswell-20260919 + worktree /home/kevin/project/worktrees/cpp-close-05-well-crosswell；协调登记 .git/codex-coordination/cpp-close-wave/task-05-well-crosswell.md；task_plan/findings 落盘 | git rev-parse = 06211541；gh pr list 开放=0 | 通过 | 勘察 |
| 2 | 环境补齐：本机无 cmake → 用户级安装 ~/tools/cmake-4.1.2-linux-x86_64（pip 缺失，官方二进制）；init 子模块 well-log-engine@f845e7ab + geo-viz-engine@08851951；勘察子代理（Explore，1/3 配额）产出 C++ well/crosswell 全景：LAS/WLE、DTW、标定、绘制、报告、dock、sidecar、resource gate CLI 已在（不重复做）；缺口 8 项（findings.md） | 子代理报告 + ledgers A/B 对账 | 通过 | 写代码 |
| 3 | **XML worker 真加载**：well_log_xml_data.{hpp,cpp}（识别+解析纯核，逐条移植 resources/well_log_xml.py + geo-viz xml_preview.py@08851951，ss:Index 填充/深度列推断/stride 抽稀/-9000 哨兵/NaN 保留/区间表，python float 语法含下划线+inf/nan）；wle_xml_load.cpp（WLE 文档装配：轴单位诚实空、反向深度方向声明、区间/标记实体）；make_wle_load_fn XML 分派（无 ingest 配置诚实降级）；CMake 守卫 TARGET pwb_ingest | 静态自审（移植逐行对照冻结源） | 待构建验证 | oracle+测试 |
| 4 | **共享井身份**：well_identity.{hpp,cpp}（规范化键、确定性 FNV-1a 128 id wi-*、进程 registry first-wins）；viz_a_install 成功路径注册（origin=well_log_page）；viz_b dock 两处注册（origin=cross_well）；04/06 经 snapshot/find 只读消费 | 同上 | 待构建验证 | presenter |
| 5 | **viz-b 真实 LAS 通路**：viz_b_well_source.{hpp,cpp}（WLE 文档→WellColumnData，null 位图+非有限成对剔除，逐文件错误聚合，LAS 坐标诚实空）；dock 增 加载井数据（LAS）多选、load_wells_from_las、sidecar well_source_las（数组，与 JSON 来源互斥）、restore 自动重载、reset_workspace（跨工程无 sidecar 清空）、来源/结果出处 label；app CMake 05 块 PWB_WITH_VIZ_B_LAS | 同上 | 待构建验证 | presenter |
| 6 | **well/time-depth presenter（05→04）**：ui_pages_preview 两页（moc-free，WellLogPreviewPage 逐列 min-max 渲染+诊断诚实降级+摘要行；TimeDepthPreviewPage MD/TWT 折线+探针注入）；app 侧 well_presenter_install（kind well_log/time_depth → viz_e ExternalPresenter 注册表；well_log 经 make_wle_load_fn 生产 seam→中性 DTO；time_depth 经 SeismicTie+CheckshotTable 权威核探针）；根 CMake 05 块 + main_window 唯一钩子（BEGIN/END 05 标记块，登记协调文件） | 同上 | 待构建验证 | 测试 |
| 7 | **测试+oracle**：ui_workers.well_xml（oracle 对账+比较器负检+输入篡改负检+身份全语义）；ui_workers.lifecycle 空壳兑现（7 场景：检查点取消/resolve 取消传播/DTW start-cancel/task_key 迟到废止/取消后部分结果/双跑逐值一致/有界关闭+析构汇合）；tests/cpp/well_crosswell{load_path,vizb_las_path,dock_lifecycle,presenter_flow}+fixtures（LAS m/ft+反向+坏文件；WITSML 基础/反向/缺测；SpreadsheetML 全家桶；两个负例；checkshot CSV）；tools/oracle/generate_well_xml_fixtures.py 双模式（模式 A 需 numpy+PySide6 本机缺 → 模式 B 逐条转录行号级推导，如实声明） | oracle 生成 exit 0（6 案例，模式 B） | 待构建验证 | 门禁构建 |
| 8 | 资源门排队：04 线持锁（Build j2）期间完成 3-7 轮全部代码；14 线接锁（Exec bench）后启动带退避 configure 循环（exit 75 → 60s 重试，≤40 次） | 门脚本 RESOURCE_BUSY/READY 语义 | 进行中 | 构建+测试 |
