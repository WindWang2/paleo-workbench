# 04 — 审计发现总账(主审计员已验证)

来源:六路只读并行 workflow(47 条原始 findings,P0×1/P1×6/P2×17/P3×23)+ 主审计员独立发现(N/F 系列)+ 主审计员逐条复核。**所有 P0/P1 与主要 P2 均由主审计员打开真实代码、对照 vendored QGIS 源码或真实构建产物二次确认**;subagent 结论未直接采信。

验证标记:✅=主审计员独立验证;✅E=经真实命令/构建产物实证;🔴=未复核(subagent-only)。

## P0

| ID | 标题 | 位置 | 状态 |
|----|------|------|------|
| B-01 | SciencePageBinding 第二次推断运行对仍 joinable 的 std::thread move-assign → std::terminate,整个桌面进程崩溃(join 仅存在于 shutdown;worker_active_=false ≠ joined) | libs/closure_science/src/qt/page_binding.cpp:364(:448 只清 flag;:308-309 唯一 join) | ✅ 待修 |

## P1

| ID | 标题 | 位置 | 状态 |
|----|------|------|------|
| C-01 | mapping_kernel 唯一挂载点(:489)早于 UI-14-IMPLY 置位(:557):未显式传 kernel 的 PLATFORM+DATA 配置在 generate 阶段失败(workflow_engine 链接不存在的 Pwb::MappingKernel);注释自证 preset 掩盖 | CMakeLists.txt:489/557/633-643 | ✅(静态+注释自证) |
| C-01b | 同族时序断裂:linux-gcc-release 等 preset 在 libs/interchange(:803)FATAL——其依赖 Pwb::Ingest(:820 才挂)与 Pwb::SeismicIo(该路径未挂)不存在 | CMakeLists.txt:803/820/450;libs/interchange/CMakeLists.txt:46 | ✅E(`cmake --preset linux-gcc-release` 实测 EXIT=1) |
| C-02 | CLOSURE-SEISMIC(07 线)TARGET gate 永假:apps(:913)早于 libs/ui_wellseis(:976)→ closure_seismic_install.cpp 从未编进产品,地震预测页永远占位;该 TU 仅被 viz_d.closure 测试目标编译(测试 wiring 冒充产品 wiring) | apps/paleo_workbench_platform/CMakeLists.txt:81-87 | ✅E(build.ninja 中 PWB_WITH_CLOSURE_SEISMIC=0 处;object 文件只在 tests 目标) |
| D-01 | 组图/布局导出 z 序整体颠倒:layout_spec_exec 把 top-first 序反转后喂 QgsLayoutItemMap::setLayers,而 QGIS 语义 index 0=顶层(vendored qgsmapsettings.h:280-287) | native/qgis_render_bridge/src/layout_spec_exec.cpp:164-184(注释错误自证) | ✅(vendored QGIS 源码核verify) |
| D-02 | 生产编图页 DisplayMapCanvas 堆叠颠倒:快照约定[0]=底,但 addVectorLayer→addMapLayer 追加树尾→index0=顶,首层(底)落顶 | libs/ui_map/src/display_map_canvas.cpp:286-345;libs/qgis/src/map_session.cpp:72-73 | ✅(Python 参考显式 reversed 对拍) |
| F-01 | 脏关闭/保存只检查活动图层:多图层并行编辑会话在关窗时静默丢失(违反自身 no-silent-discard 契约) | apps/paleo_workbench_platform/main_window.cpp:2180-2211 | ✅ |
| F-02 | 无「关闭工程」路径:一窗口终身一工程,切换/重开必须重启进程;MRU 菜单打开后即失效 | main_window.cpp:1346-1349/1242-1245 | ✅ |
| F-A(主审) | Stage-2 约束创作链断裂:8 个约束按钮 emit constraint_requested 无消费者;无产品代码写 constraint_layers/设置 constraint_kind;commit_constraint_group 无调用方;消费侧(resolve_constraints→constrained IDW)完备——按钮 silently ignore,违反 fail-closed | libs/ui_composite/src/mapping_stage_panel.cpp:327;composite_document.cpp:159;全仓 grep | ✅(多角度) |

## P2(主审计员已验证)

| ID | 标题 | 位置 |
|----|------|------|
| A-1 | 三阶段旗舰安装(stage_flow_install.cpp + PWB_WITH_STAGE_FLOW)嵌套在 if(BUILD_TESTING) 内:BUILD_TESTING=OFF 的产品构建静默丢失整个 V14 三阶段 UX | CMakeLists.txt:1209/1259-1270 |
| C-03 | VIZ-B LAS 接线 gate 永假(UiWorkersWleLoad :953 > apps :913):跨井 dock 真实 LAS 路径永久降级「LAS 解析内核未接入」 | apps/.../CMakeLists.txt:283-287 | ✅E(define 0 处) |
| C-04 | cpp-close-01 目录闭包 gate 永假(UiControllers :1084 > apps :913);两 TU 只被测试编译;PWB_WITH_CATALOG_CLOSURE 定义后无人使用 | apps/.../CMakeLists.txt:104-119 |
| C-05 | UI-13 linked_workspace gate 永假(UiControllersQt :1084 > ui_composite :912),且每配置打印误导性 STATUS(『needs CONV_30』而 CONV_30 默认 ON);对应烟囱测试覆盖静默丢失 | libs/ui_composite/CMakeLists.txt:93-103 |
| D-03 | mirror_snapshot 平铺序漏掉 Python 显式 reversed——镜像画布 z 序颠倒(V11 04-ordering 契约违约) | mirror_snapshot.cpp:753-775 |
| D-04 | mirror 平铺重排 clone+removeChildNode 触发注册桥排队删层(未提交编辑缓冲销毁=数据丢失级);layer_tree_stack 已有正确 takeChild 舞步未用 | mirror_snapshot.cpp:764-771 |
| D-05 | mirror 比例尺域 min/max 对调:可见窗口恒空,带 scale_range 的镜像层永久不可见(vendored isInScaleRange: scale>=min && scale<max 实证) | mirror_snapshot.cpp:704-712 |
| D-06 | qgis_render_bridge apply_scale_range 同样对调且注释固化错误 QGIS 语义;与 map_stack_service.cpp:2253-2257 正确实现同二进制矛盾 | qgis_render_bridge.cpp:121-134 |
| D-07 | 桥 setSnappingConfig 比例依赖方向反了(Global 语义 scale<=minimumScale 才捕;意图分母≥阈值才捕) | map_stack_service.cpp:5095-5108 |
| F-03 | target_horizon 无任何可达 UI 写入口:阶段条 combo 永无候选且不可输入→三阶段 readiness 永久『未就绪』+不可能完成的补救指引 | stage_flow_install.cpp:402-412;mapping_stage_bar.cpp:127-133 |
| F-04 | 阶段①默认展示两个『(占位页,待实现)』dock 当工作面,真实测井/地震 dock 不受阶段管理 | stage_presentation.cpp:56-70;app_shell.cpp:144-145 |
| F-05 | openProject 部分失败早退:store 已挂载但阶段还原/viz-b/数据页/审核页重绑全跳过,叠 F-02 即不可恢复的半初始化会话 | main_window.cpp:1475-1477 vs 1478-1539 |
| B-02 | WorkerHost::wait_join 读陈旧 finished_(:110-114 spawn 不复位):第二次运行后有界关闭退化为无界 join,GUI 冻结 | closure_mapping_install.cpp:110-180 |
| B-04 | 目录维护 std::async worker 与 GUI 对 session_generation_/host_ std::function 数据竞争(UB) | libs/ui_controllers/src/project_controller.cpp:209-216 |
| A-2 | 矩阵把 compile_map/integrated_compilation/map_product 标 NATIVE_PRODUCT,但 Pwb::ClosureWorkflow 编译/融合核心产品 TU 零调用(唯一消费者 closure_review_install 只用 FileCatalogRepository)——按矩阵退役即两端失去综合编图 | closure_review_install.cpp:7-9;矩阵行 |
| A-3 | 清单/矩阵探测器结构性失真:只取最后别名+只扫直连→~50 行假 NOT_WIRED(与 A-2 假 NATIVE_PRODUCT 双向失真) | tools/migration/pwb_migration_inventory.py:250-256/393-427 |
| N-1(主审) | harness data.ingest output_schema 声明 created_entities=array,实现为 int 计数(#1439 起)→动作判 invalid 整体失败(本地+CI 双复现) | paleo_workbench/harness/actions/data_lineage.py:84 | ✅ 已修 |
| N-4(主审) | main CI nightly perf gate 红:test_zoom_pan_sla 20.09s vs SLA 16.0 | tests/perf/test_facies_atlas_bench.py(run 35580075660) | ✅E |

## P3(代表性,全部收录 GitHub issue 汇总)

- **B-05** WorkflowScheduler pending_ 注册竞态(cancel 对终态谎报成功);**B-06** JobScheduler 工作目录泄漏(release_work_dir 无生产调用);**B-07** fallback 后端 threaded 模式无锁读可变 snapshot(当前生产 threaded=false);**B-08** run_integrated_fusion sensitivity 汇总段无守卫;**B-09** on_contour_completed task_panel_ 空时不恢复按钮;**B-10** SEG-Y cancel-bridge 异常路径未 join→terminate
- **C-06** closure_review_install 双块重复挂载风险;**C-07** CONV-29 蕴含语义两源漂移(FATAL 不可达);**A-4** ui_visualqa 编译零消费者
- **D-08** CompositeDocument rebuild_composition/LayerManagerPanel hook 未绑定(复合图层 dock 死 UI——与 F-A 同族);**D-09** 树删除层后 reconcile 永久中止;**D-10** 镜像 truncate 后 addFeatures 拒绝无恢复;**D-11** 顶点抓取每次 mouseMove 全量扫描
- **E-1** 推理快照哈希跨语言字节不兼容(恒误判 stale);**E-2** validate_softmax_budget classes==0 除零
- **F-06** 任务中心 operation 取消钩未接+registry 零生产者;**F-07** 命令面板 16 vs 文档 17;**F-08** selection 总线零 producer+SelectionBus 泄漏;**F-09** 树删层后残留陈旧权威误导原因;**F-10** surface_state 词汇零消费者;**F-11** reduced 构建行号映射错位;**F-12** 状态栏双写者互踩
- **N-2(主审)** audit_ui 3 断言过时(英文文案 vs 中文断言) ✅ 已定位;**N-3(主审)** capabilities 面板 factor_fusion 等 "not wired" 标签失真(经 science_service 适配器实际可达)

## 处置决定

**本轮修复**(fix/cpp-final-postmerge-audit):B-01;CMake 家族(C-01/C-01b/C-02/C-03/A-1/C-04/C-05/C-06 防重);QGIS 语义家族(D-01/02/03/04/05/06/07);F-A 约束创作链;生命周期家族(F-01/F-02/F-05);B-02/B-04;F-03/F-04;E-2、B-09、F-12、F-09、F-07、N-3、N-1、N-2、A-2/A-3(矩阵真值);B-05/B-06/B-08/B-10 视工作量。

**明确不修并记录理由**(08-known-limitations):D-08 复合面板完整接线(独立子史诗,与 F-A 修复正交);F-10 surface 词汇全面接入(UI 统一属独立 UX 线);N-4 perf SLA(需要基准环境归因,CI 2 核 vs 本机不可比);B-03(epoch 重构,触发面先需 shutdown 超时)、B-07(当前 threaded=false)、F-11(reduced 构建路径)、C-07(语义统一属 feature-graph 重构)。
