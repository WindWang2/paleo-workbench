# 03 — Progress Log

| 轮 | 时间(UTC) | 候选SHA | 动作/命令 | 退出码 | 结论/下一步 |
|---|---|---|---|---|---|
| R1 | 2026-09-19T15:5x | 06211541 | `git fetch origin`；`rev-parse origin/main` | 0 | origin/main=06211541（本地 main 落后 6）；建分支+worktree |
| R1 | 同上 | 06211541 | 只读盘点子代理（1/3 预算内） | 0 | 闭环缺口 1..6 见 task_plan.md |
| R1 | 同上 | 06211541 | 下载 ONNX Runtime v1.17.1 官方 release → /home/kevin/pwb-sdks/ort | 0 | `nm -D libonnxruntime.so \| grep OrtGetApiBase` = 1，可用 |
| R1 | 同上 | 06211541 | 写 03-line.json（协调登记，git common dir）+ ledger 四文件 | 0 | 命名块租约已申报 |
| R2 | 2026-09-19T16:xx | 06211541 | 写 closure_science 核 6 TU + qt 绑定 + 2 测试 + CMake + root/main_window 命名块 | 0 | 新增库面见 findings |
| R2 | 同上 | 06211541 | 逐 TU g++ -fsyntax-only（SDK 无关轻量检查，不占重型门） | 0 error | 全部 9 个新 TU 语法通过（修复 StrongId 显式转换/DataError.code/DirtySet 字符串向量等 ~30 处） |
| R2 | 同上 | 06211541 | 资源门 Probe | RESOURCE_BUSY ×2 | 另一线持锁（04/12 集成构建）；按合同退避排队，sleep 60 轮询 |
| R3 | 2026-09-19T17:3x | 06211541 | 门内 Configure 多轮退避后成功（需 -D PALEO_QGIS_* 指向主工作区 vendored SDK 只读复用 + PWB_BUILD_SEISMIC_VIEWER=ON 补 Pwb::Visualization，避免 SCIENCE 门与 CONV-28 重复目标） | 0 | build/close-03 生成 |
| R3 | 同上 | 06211541 | 门内 Build 全量（178 目标，j2 默认） | 0 | pwb-platform 含 closure_science/_qt 链接成功；期间修复 AUTOMOC 头扫描（hpp 入 target sources）与 Qt6::Test find_package |
| R4 | 2026-09-19T17:4x | 06211541 | closure_science.core 直跑（真实 ONNX e2e） | 0 fail | 修复点：fixture current_version_id 缺失、const Json operator[] UB ×3（payload source/page binding/inference）、use-after-move、spatial 契约 mirror 键、ensure_default_models 幂等（get-first）、断言语义对齐 Python |
| R4 | 同上 | 06211541 | closure_science.qt_hooks 直跑（offscreen，页面真实入口 on_demo 全链） | 0 fail | 页面守卫链 + 任务物化 + journal 全通 |
| R4 | 同上 | 06211541 | 受影响回归集（门内 ctest -r 长集合，跑两遍） | ⏳ | 门被其他线占用，队列中 |
| R5 | 2026-09-19T18:0x | 06211541 | 独立审查子代理（reviewer C，2/3 子代理预算） | FAIL→修复 | P0×2（worker 与 GUI 并发访问 CatalogDocument；可 join 线程析构 terminate）+ P1×7 + P2×5 全部记录 |
| R5 | 同上 | 06211541 | 修复：document_mutex_ 串行化 + try_lock/cached 回退；shutdown 恒 join；token 校验移至 GUI 线程；start_run 预检拒绝；canonical dump 对齐 Python json.dumps（转义+分隔符）；catalog_asset_id 梯级 + weakly_canonical；schema H5-b 仅无 recognized 键时拒绝；materialize output_version_id 参数回退 + cancelled truthy；persist 失败清理孤儿文件；publisher getter 加锁 + 头注释；core_test 移除 ORT 软跳过 + 修复恒真断言；qt_hooks 处理模态守卫（auto_close_modals + set_project） | 0 | closure_science.core / qt_hooks 直跑全绿 |
| R4' | 2026-09-19T18:2x | 06211541 | 门内 Build（增量重链）+ 受影响集 ctest 两遍 | ⏳ | 队列中（波形期其他线长构建持门） |

审查遗留（P2，如实记录，不阻塞本线）：
- B1 volume store 注册（class/prob raw → catalog DERIVED 版本行）未移植：产物经 envelope output_descriptor 路径引用，目录在 artifacts/intermediate。
- local_asset 模型被播种但无原生执行器：运行时显式失败（选择器可见性留给 12/产品决策）。
- coerce_seed 对数字字符串回退 0（Python int("5")=5）——注释已声明。
