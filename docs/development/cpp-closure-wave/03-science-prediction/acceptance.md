# 03 — Acceptance（对照本线验收）

构建/测试候选：本分支（base `06211541`），build/close-03
（`-DPWB_BUILD_CLOSURE_SCIENCE=ON;-DPWB_BUILD_SEISMIC_VIEWER=ON`，Release）。
真实 ONNX Runtime v1.17.1（官方 release，`OrtGetApiBase` 验证）经 ctest ENV
`PALEO_ONNXRUNTIME_LIBRARY` 注入。

| 验收项 | 证据 | 状态 |
|---|---|---|
| 真实模型 + 确定性小数据端到端 | `closure_science.core::run_real_onnx_end_to_end`：真 ONNX（identity 包 fixture，真实 ONNX Runtime 会话）+ 4×6×5 确定性 raw 体；catalog version→resolve→DataRun→tiled 推理→DERIVED 版本+run 关联+provenance→`prediction_map_layers`（classmap 形状/geotransform 断言） | ✅ |
| 数值对账 | classmap 逐字节 == 阈值化输入模式（identity 模型，sigmoid>0.5） | ✅ |
| 输出身份对账 | output_version_id == run.output_version_ids[0]；version row run_id 回链 + DERIVED；payload model/generator/run_id 为服务侧独占（reserved keys 重断言） | ✅ |
| 缺模型 → 明确失败 | 未知 model_version_id → `Unknown model version`（Python parity 文本）；未提升生产模型 → find_production_model=null → 页面诚实警告 | ✅ |
| 缺执行提供器 → 明确失败 | 无 registry / 未知 provider → `Unknown model provider: '…'`；local_asset/geoviz_online 无原生执行器 → 显式错误（HTTP 未接入如实报错）；ORT 库缺失 → `ONNX Runtime 执行器不可用` fail-fast | ✅ |
| 无效 shape/CRS/描述符 → 明确失败 | 描述符 shape 与文件大小矛盾 → run failed 无输出；无 grid_descriptor → 显式拒绝；CRS 契约交由包声明（无静默 EPSG 注入）；单位/CRS 经 `validate_prediction_input` 契约 | ✅ |
| 取消 | 协作取消 → run=cancelled（非 failed）无输出版本 + tiles_done 记录；tiled per-tile resume 标记保留（PredictionTaskRuntime resume=true） | ✅ |
| 重开恢复 | PredictionTaskJournal 重开恢复（journal restore == recorded）；run 级终态拒绝重执行 | ✅ |
| 旧工程晚到结果不污染新工程 | 工程身份 token（项目路径 sha256）：异 token 写入/加载被拒（token mismatch）；Qt 绑定完成回投前核对当前工程 token，不匹配即丢弃 | ✅ |
| 生产服务注入（well/seismic 预测页） | `closure_science.qt_hooks`：页面真实入口 on_demo() 驱动全链（demo 种子→run→worker→provider→catalog 结果版本→任务物化+journal），无工程/无生产模型走诚实守卫；`main_window.cpp wire_app_shell` 命名块装配（12 可收口） | ✅ |
| 无 fake provider 生产交付 | provider 注册表仅 demo（demo_only 诚实标注）/ tiled_onnx（真 ONNX）；未知名 fail-closed；http 未接入 → 显式失败 | ✅ |
| 科学服务 catalog 闭环（CONV-28 缺口收口） | CatalogPayloadSource（table 解码+fail-closed）+ CatalogEnvelopePublisher（envelope.json 目录契约 + run+DERIVED 版本+lineage）经 TaskRuntime e2e | ✅ |
| 受影响回归集 | 门内 ctest（closure_science/science_service/prediction/ui_wellseis/app_shell/project_session/catalog_service/workflow_runtime/workflow_engine）：**23/23 两遍全绿**（build/close-03，Release） | ✅ |
| 独立审查 | reviewer C 一轮：FAIL（P0×2 并发/线程析构 + P1×7）→ 全部修复 → 复验全绿；P2 遗留如实记录于 findings/progress | ✅ |

已知限制（如实）：
- geoviz_online（线上单井预测）与 local_asset（GR 启发式）无原生执行器——显式报错，不伪造。
- 井预测页 online 路由 → 显式"未接入原生运行时"错误（诚实不可用）。
- 任务恢复返回任务 JSON（binding.restored_tasks()）；页面 update_state 的重注入由宿主（12/01）在工程打开事件里调用——本线交付了 binding API 与语义测试，GUI 重注入口待装配。
- closure 测试固定 C++ demo 序列（与 Python MT19937 流不声称位等价；demo 语义/词汇一致）。
