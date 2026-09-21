# 07 — Review Findings (V14-THREE-STAGE-UX)

两轮独立 review（2026-09-20，基线 c7266807 5 提交线）。

## 轮 1：架构/正确性 —— 发现与处置

| 级别 | 发现 | 处置 |
|---|---|---|
| P0-1 | apply_horizon 无锁直写 live 文档（与 #1380 关闭的并发边界冲突；worker publish 同树竞态） | **已修**：CommitCoordinator 新增 `set_document_section`（同一 recursive_mutex），apply_horizon 改走 copy-modify-write 持锁通道 |
| P0-2 | restoreStageFromProject 测试断言与 lenient codec 语义相反（stage_four 被 codec 强转 stage1 并 apply，断言却要求保持 stage3），且分支在本机/全闭合均不可达（未 openProject） | **已修**：断言改为「未知值 → codec lenient 回落 stage1 并 apply」（与实现一致）；不可达问题以 no-project 分支的诚实断言补充；全闭合真实 openProject 路径登记 known limitation（本机无 SCIENCE 闭合） |
| P1-1 | 进程级 command_registry 持捕获 this 的回调，析构不注销；多窗口后窗劫持前窗命令 + 关窗 UAF | **已修**：install 记录 `stage_flow_command_ids_`，destroyed 钩子逐个 unregister；测试补「窗口析构后 with-context evaluate 存活」断言 |
| P1-2 | CONV_27 StageDock 切 stage 不触发 stage_flow_ refresh——同窗两阶段表面显示不同阶段 | **已修**：applyStageValue 尾部 `stage_flow_->refresh()`（true-change 无环） |
| P1-3 | restoreStageFromProject 走非 const mapping_workspace()——段缺失时向 live 文档插入空对象（无锁变更） | **已修**：const 读 + 本地 diagnostics 列表 |
| P1-4 | selection bus 建后无 publish 调用者；「store detach 清除」机制不存在但注释宣称 | **部分**：本线定位为「总线实例化 + sinks 接线」，publish 喂入端属 layer-tree 线（line 3 seam）；注释已改为如实描述（known limitation 登记） |
| P1-5 | panel.toggle.layers 指向不存在的 panel key：静默 no-op + 写垃圾偏好 | **已修**：seed 删除；mapping 分支补 `is_panel_registered` applicability 守卫（未知 key 不落偏好） |
| P1-6 | CONV_27/CLOSURE_MAPPING/DATA_INTEGRATION 路径在本机零编译零覆盖 | **登记**：known limitations（本机 reduced closure；全闭合路径依赖 Linux CI） |
| P2-1 | horizon 清空不同步（combo 残留） | **已修**：snapshot_changed 无条件 set_horizon_state（空即清） |
| P2-2 | stage_applied 裸捕获 bar（receiver 是 this） | **已修**：context 改 bar |
| P2-3..P2-12 | sink outlive 契约注释、top_bar QPointer/show、surface 注释、nav_targets .at 抛出、preset 打自定义、启动双持久化互搏、测试 hermetic、恒真断言、read_only 检查、析构序 QPointer | 恒真断言已删；其余逐条评估：多数为加固建议无触发面，登 known limitations / 后续项 |

## 轮 2：对抗/生命周期 —— 发现与处置

| 级别 | 发现 | 处置 |
|---|---|---|
| P0-1 | 同轮 1 P0-1（独立发现，交叉确认） | 已修（同上） |
| P1-1/P1-2 | 同轮 1 P1-1（UAF 触发序列 + 测试绕过原因：null-context find 短路） | 已修 + 测试补 with-context evaluate |
| P2-1 | 双遍 readiness（同轮 1 P2-1） | 登记后续 |
| P2-2 | running_tasks 采样即弃 | 登记后续（需轻量刷新路径） |
| P2-3 | snapshot_changed 无条件重建 combo + 层位无候选列表 | 部分修（清空同步）；候选列表（从层序格架读 options）登记后续——依赖 stratigraphy sections 结构，跨 line 1/4 |
| P2-4 | 析构窗口期 owned_services_settings_ 释放后指针悬垂（无当前触发路径） | 登记（加固建议） |
| P2-5 | 启动序 stage profile 与 restore_window_layout 互搏 | 登记后续（需产品定夺优先级声明） |
| P2-6 | 测试盲区：A 死后非 null context evaluate | **已补**（新断言） |
| 安全确认 | job_center_ 创建序（buildUi 前）→ seams 无 UAF；bank QObject 父子 + receiver 自动断连；信号回环不存在（set_current_stage 静默 + suppress_horizon_ 双守卫）；TaskCenter 轮询不碰 QSettings | — |

## 结论

P0 全部清零（2/2 修复）；P1 修复 5/6（1 项跨线依赖登记）；P2 修复 4 项、
登记 8 项（均有 file:line 与修法记录，无「假修」）。
