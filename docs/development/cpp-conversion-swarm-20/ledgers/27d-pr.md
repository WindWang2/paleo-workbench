# 27d-pr — CONV-27d 桥编辑域（native edit session / session set / gestures / render snapshot）

## Scope

补齐 CONV-27（27b）D-27-01 排除、且 UI-13（PR #1406）未吸收的桥编辑域真缺口——四个
Qt-free 纯逻辑模块，全部落 `libs/mapping_document`（数据核，仅依赖 Pwb::Domain）：

- `paleo_workbench/mapping/edit_session_set.py`（166 行，全量）→ `edit_session_set.{hpp,cpp}`
  （EditSessionSet + JoinDecision：会话集合按需生长、CRS 冻结、schema/CRS 互斥、
  按栈绑定的停发窗口查询；栈绑定为非拥有身份指针，D-27d-02）。
- `paleo_workbench/mapping/edit_gesture_manager.py`（121 行，全量）→
  `edit_gesture_manager.{hpp,cpp}`（GestureRecord + EditGestureManager：整手势
  逆序 undo / 正序 redo 计划、幂等 mark、LIFO redo 队列与陈旧项清理、审计流）。
- `paleo_workbench/mapping/native_edit_session.py`（468 行，全量）→
  `native_edit_session.{hpp,cpp}`（NativeEditSessionController：三段门禁、易失
  会话、committed 增量收集、镜像读回规范化、编辑期属性写、全或无 commit +
  补偿恢复 + 手势计划 undo/redo）。duck-typed 栈 → `NativeEditBridgeStack`
  抽象 seam（能力面默认实现 = 诚实降级，D-27d-03）；VectorLayer 消费面 →
  `ICommittedDeltaSink` seam（D-27d-04）；拓扑/地质/角色门禁 → 函数与接口 seam。
- `paleo_workbench/mapping/map_document_snapshot.py`（409 行适配器）→
  `render_snapshot.{hpp,cpp}`（document_render_snapshot / extent_for_snapshot：
  Qt-free 值类型投影、单遍分组走查 + 内联 bounds、正面积垫宽、owner 级 LRU、
  style-default provider seam、确定性内容修订，D-27d-07）。

范围外（明确归类，见 27d-decisions）：`vector_layer.py`/`edit_delta.py` 核心
（UI-13 已移植，不复制）、`edit_delta.ZeroCopyEventBus`（numpy 消费脸，生产者
本已是 native/qgis_render_bridge 的 C++ 环）、`map_authoring.py`（partial/
UI-absorbed，留 UI 桥切片）、QGIS 桥栈实现（libs/qgis 桥切片）。

## Python surfaces replaced

| Python surface | C++ target | 状态 |
|---|---|---|
| edit_session_set.py EditSessionSet/JoinDecision | `edit_session_set.{hpp,cpp}` | complete（oracle 全量对账） |
| edit_gesture_manager.py GestureRecord/EditGestureManager | `edit_gesture_manager.{hpp,cpp}` | complete（oracle 全量对账） |
| native_edit_session.py NativeEditSessionController | `native_edit_session.{hpp,cpp}` | complete（oracle 全量对账） |
| map_document_snapshot.py document_render_snapshot/extent_for_snapshot | `render_snapshot.{hpp,cpp}` | complete（features/extents/styles/可见性 oracle 对账；内容派生 revision 值为 C++ 契约） |
| SESSION_SET 进程单例 | 宿主作用域持有（controller 默认内含/可注入） | C++ 契约（D-27d-06） |
| `_stable_revision` 进程内 hash | 确定性 SHA-256 内容摘要 | C++ 契约（D-27d-07） |

## Oracle

`tools/oracle/generate_map_document_bridge_fixtures.py` 从真实 Python 产品代码
冻结（确定性 uuid patch、fake 桥栈与 tests/test_topo_m1 同型）：
- session_set_cases 3：生命周期/入集生长（gate 拒绝带原文案）/按栈绑定窗口/
  CRS+schema 互斥文案/逐层 discard/关闭返回集合。
- gesture_cases 2：finish 保序去重/undo 逆序/redo 正序/幂等 mark/陈旧队列
  清理/clear/audit 流。
- native_cases 5：gate 拒绝不 startEditing、旧桥诚实降级、CRS 失配拒绝、
  能力探测矩阵（属性写/dirty 查询）、读回规范化（__pwb_fid 优先、非对象
  properties 整体放弃）、committed 增量逐层回写（含消息/审计）、三段门禁
  拒绝矩阵（角色/桥检查器/旧桥回落/地质 error 拦截 warning 放行，冻结完整
  错误文案）、全或无成功提交、中段提交失败 + 快照补偿恢复（补偿层保持会话、
  失败层保持可重试、剩余层回滚移除）+ 补偿宏手势 undo。
- snapshot_cases 6：legacy 文档分组（洞/MultiPolygon 保留、白名单属性提升、
  脏记录跳过）、records 覆盖、visibility、revision 复用、layer_revisions
  前缀桥接、空文档占位、退化 extent 垫宽、null 文档；content-revision 值
  不冻结（Python hash() 进程内），以 C++ 契约测试补位。
- 测试含负自检（文案/层序/入集结论篡改必须被检出）与 C++ 契约段（摘要
  确定性+区分性、owner LRU 复用与跨 owner 不泄漏、previous_layers 复用）。

## Product wiring

`NativeEditSessionController` + `EditSessionSet` + `EditGestureManager` +
`RenderSnapshot` 为 UI/Workflow 宿主的 C++ 单一接面：ui_composite 的
`INativeEditing` 实现方（qgis 桥切片）可直接以 `NativeEditBridgeStack` 适配器
+ `ICommittedDeltaSink` 转接 `ui_composite::VectorLayer`；render adapter 消费
`document_io::features_from_document`（JSON 记录形状），与 CONV-27 service 门面
同栈可用。C++ 主链不依赖 Python。

## Local build & test

- configure：`-DPWB_BUILD_DATA=ON -DPWB_BUILD_CONV_02=ON -DPWB_BUILD_PLATFORM=OFF
  -DBUILD_TESTING=ON`（Debug，Ninja）
- ctest：`mapping_document.roundtrip` + `mapping_document.edit_session`（回归，
  全绿）+ `mapping_document.bridge_session`（新，**582 checks, 0 failures**）
- ASan+UBSan 复跑三测试：无报告（过程中抓到并移除测试内一处死代码符号溢出）
- fixture 重跑 sha256 与提交版一致（生成器幂等）

Local verification completed; online CI is not required or awaited for this task.

## -j3 resource note

遵循 `scripts/cpp-migration/invoke-resource-gate.sh`；共享重槽被并行任务
（cpp-close-04-data-preview，Build 持锁）占用（exit 75）期间，本分支仅做
targeted build：4 个新翻译单元 + 1 测试 TU + 同库测试复编译，ninja `-j2`
（≤ -j3 硬上限），无全树编译、无 OOM；ASan 变体同 -j2。

## Known limitations

- 桥栈实现（QgsVectorLayer edit buffer 接线）不在本分支——`NativeEditBridgeStack`
  是抽象面，qgis 桥切片提供适配器；旧桥适配器返回
  `supports_native_editing()=false` 即得 Python 同款拒绝文案。
- 内容派生 revision 值与 Python 不可比（Python hash() 进程内）——C++ 为
  确定性摘要，跨进程稳定（升级：同内容跨进程可复用缓存）。
- `ZeroCopyEventBus`（numpy 排水消费脸）不移植：生产者已是 C++
  （native/qgis_render_bridge edit_delta_pod.hpp），Python 侧归类 legacy
  consumer。
- 会话集合/控制器/手势管理器为单线程契约（头文件声明），与 Python 同步回调
  语义一致。

## Parallel-branch interaction

改动以新增文件为主；共享改动仅 `libs/mapping_document/CMakeLists.txt`
（追加源文件 + 测试 target，append-only）与 4 个 Python 模块尾注 +
`CPP_EXTENSION.md` 追加段。与 open PR #1400/#1402/#1404/#1408/#1409/#1410/
#1411 的改动区无 hunk 重叠。

## No-online-CI statement

Local verification completed; online CI is not required or awaited for this task.
