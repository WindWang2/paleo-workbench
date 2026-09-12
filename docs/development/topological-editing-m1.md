# 拓扑编辑迁移 M1 原生编辑 MVP——实施记录（2026-09-12）

> 规格与路线图：[docs/specs/topological-editing-migration-spec.md](../specs/topological-editing-migration-spec.md) §8。
> M1 内容：镜像层 startEditing + 三段门禁 + 手势管理器（层宏+逆序撤销）+
> 顶点 v2 当前层档 + committed\* 回写 + 快照基线回滚（来源 §2/§4 顶点/§3）。
> 退出标准：场景 1、3、4、5 通过；M0 回归绿。

## 编辑权迁移的落地形状

编辑权威翻转到 QGIS 镜像层（**相图草稿先行**：polygon 层 + 原生画布 +
桥能力 → 原生会话；其余层保持 Python 会话，工具面不变）。原生会话期间：
- 顶点工具 v2（当前层档）直接编辑镜像缓冲——共享节点（map CRS 下 1e-8
  精确重合）联合拖动/联合删除，**每层每手势恰一宏**（begin/endEditCommand，
  宏文本沿用桌面词汇 "Moved vertex"/"Deleted vertex"/"Added vertex"/"Added
  feature"）；数字化几何直写缓冲（宿主生成 id → add_mirror_feature 一宏）。
- M0 停发窗口开（SESSION_SET 绑定发布栈）——宿主重发短路，镜像实时渲染
  编辑缓冲；**编辑期间 Python 不动**（崩溃/退出即丢，无 sidecar）。
- 撤销 = 宿主手势管理器计划（逆序逐层 undoStack 宏，M1 单层直通）。

保存 = 整集合全或无（§3）：角色门禁复查 + 拓扑零错误（几何从镜像
**读回**校验——编辑缓冲即事实）全集合判定 → 逐层 commitChanges →
committed\* 增量同步捕获回传 → 宿主吸收为提交审计（EditCommand 同族）→
**M0 台账对齐直跳新基线（align，无重发）** → 关停发窗口。任一失败全
保持（commit 失败 QGIS 缓冲不清，会话保持）。回滚 = rollBack 复位快照
基线（真源未动，台账冻结在基线 → 关窗后发布判 no-op）。

## 落地清单（实现件 → 代码坐标）

| 实现件 | 位置 |
|---|---|
| 会话生命周期（桥） | `map_stack_service.{hpp,cpp}`：`startMirrorLayerEditing`/`commitMirrorLayer`/`rollBackMirrorLayer`/`mirrorLayerEditing`/`undoMirrorEdit`/`redoMirrorEdit`/`addMirrorFeature`/`setCommittedCallback`；四 committed\* 信号连接（context=layer 自动断连 + alive token） |
| committed 增量捕获 | 同上 `handleCommitted*`：added（`QgsJsonExporter` 导出 + `__pwb_fid` 注入，宿主 id 按 addMirrorFeature 序配对）、removed、geometry_changes、attribute_changes；**fid 表按 provider 现值增量重建**；`fireCommittedDelta` per-canvas 回传 |
| 读回（含编辑缓冲） | `mirrorFeaturesJson`：`limit<=0` 不限 + 注入宿主 id（fid 表解析）——拓扑门禁的校验输入 |
| 顶点工具 v2（当前层档） | `edit_tools.{hpp,cpp}`：`setEditLayerProvider`（QgisMapStack 注入：画布当前层 + M1 会话表）；`verticesNear` 共享节点发现（线性扫 `getFeatures()` 合并缓冲）；联合拖动（公共节点 marker 高亮）/联合删除（同要素闭合环重复点去重 + 最小顶点守卫原子拒绝）/双击插点直写；`edit_gesture` 手势回调；无会话时**逐字节保持 v1 回调模式**（回归锚点） |
| 原生会话控制器（宿主） | `mapping/native_edit_session.py`：open（gate 拒绝则不 startEditing——场景 1）/commit_all（全或无 + 读回拓扑校验 + on_committed 对齐钩子）/rollback/readback_features/undo_gesture/redo_gesture；能力探测 `bridge_supports`（旧桥诚实拒绝） |
| 手势管理器 | `mapping/edit_gesture_manager.py`：手势→受影响层有序表；undo 逆序/redo 正序；审计记录（手势 id/宏文本/层序列） |
| 提交增量写回 | `vector_layer.apply_committed_delta`：几何/属性/增删直更已提交状态（QGIS commit 清 undo 栈的同语义——不可撤销）+ data_revision 跳新值 + EditCommand 同族审计流 |
| 拓扑校验输入 | `topology.validate_records`（validate 重构出的记录级入口） |
| 接线 | `composite_editing`：start/save/rollback/flush/edit_command/activate_tool/ensure_layer_session（互斥：原生会话期间不开第二 Python 会话）/commit_native_capture/record_native_gesture/editing 事实（工具求值器与快照 metadata 均含原生）；`canvas_shim`：edit_gesture 路由 + 数字化完成的原生路由；`qgis_mirror.align_publish_ledger_for_layer`（VectorLayer→token 适配） |

## 验收证据

- `tests/test_topo_m1_native_editing.py`（12 项，fake stack）：场景 1
  （RAW 拒绝且零 startEditing）、场景 3（B 层坏几何 → 全集合保持零提交；
  修复后两层同提交 + 增量写回 + 台账对齐 + 关窗）、场景 4（未提交编辑
  不达真源——工程持久化只含已提交）、回滚复位、旧桥拒绝、手势管理器
  逆序/正序/审计。
- `tests/test_qgis_topo_m1_native_editing.py`（5 项，真桥 qgis-marked）：
  **场景 5**（共享节点联合拖动、一次 undo 整体回退、无缝隙）+ 提交增量
  双要素几何变化 + 快照基线回滚 + 无会话时 v1 行为不变 + 数字化宏与
  fid 配对。
- 回归：M0+M1 合并批 **225 过 / 3 条件跳过**（含 test_qgis_v10_edit_tools
  等既有真桥 v1 行为回归）；工作站/工程批相对 M0 终态基线**零新增失败**
  （既有 41+2 失败全为 HEAD 潜伏/V10 在途，见 M0 记录）。受 M1 语义
  影响的两个测试已按新世界调整：split 测试显式禁用原生翻转（钉 Python
  路径，M3 接线原生分割）；编辑中事实纳入原生会话（工具求值器一致）。
- 桥构建：GCC 16.2.1 对本代码 ICE（chrono/qtextstream 头段错误），
  以 **clang-22** 构建（`CC=clang CXX=clang++ ... setup.py build_ext
  --inplace`）；`__version__` 0.7.0a0。

## M1 内的显式后置（M2/M3 接线）

- 全部层档 + 拓扑点散布 + 避免重叠 + 追踪 + 框选多节点（M2）：手势
  管理器的跨层生长（request_join 门禁复查入集）随之启用。
- 分割/合并/reshape/ring/part 在原生会话中暂不可用（Python 会话工具面，
  ensure_layer_session 互斥拒绝并提示先保存/回滚）——M3 无缝分割/合并
  接进原生缓冲。
- 字段 schema 变更互斥（§3）的桥/宿主执行点：会话集合互斥谓词已在
  （M0），原生会话路径的 UI 入口随 M2 补。
- 首次导入的推断**对话框**（M0 记录移交给 M1 的项）：谓词与 `crs_locked`
  已就绪，导入 UX 整合归入 M2（编辑会话/工具面收敛后再接确认流）。
- 编辑窗口内的样式推送（§3「样式允许」）：窗口内层样式变化**顺延到关窗**
  （无样式单推的桥面——upsert 会连带全量 geojson 毁编辑缓冲）；M2 增
  `setMirrorLayerStyle` 桥面后兑现。窗口内样式**读回验证**照跑（漂移可诊断）。
- `beforeCommitChanges` 桥侧钩子（§2 提交段的防纵深版）：M1 以宿主
  `commit_all` 预检等价实现（提交唯一触发方是宿主）；M2 工具直连 commit
  时补桥侧拦截。

## 审查修复记录（/code-review 两轴）

- `commit_all` 失败路径状态一致性（失败层保持会话、已提交层出表、其余
  层回滚并收敛停发窗口）——Spec 轴 c3。
- 会话集合按需生长：`open` 在已有集合时经 `request_join` 入集（替换语义
  会把既有层踢出停发窗口造成状态分叉）——Spec 轴 c2；CRS 失配层拒绝入集。
- 数字化路由补手势记账（"Added feature" 宏——否则 Ctrl+Z 到不了桥
  undoStack）——Spec 轴 c1；`undo/redo_gesture` 部分失败不标记手势。
- C++：`beginSharedDrag` 死参删除、不可达兜底改诚实 pick_miss、
  undo_text 复数一致性、`mirrorLayerByDoc` 收拢四处同形解析——Standards 轴。
- `canvas_shim` 手势记账异常可诊断（不再静默吞）——Standards 轴。
- 已知且暂留（判断题，M2 收敛）：`_layer_ledger_tokens` 与发布循环的
  token 公式手工同步（对齐后多一次重发的安全回落语义）；CRS 域失配
  判定在 crs_chain/domain/composite_document 的多处出现（M2 随导入推断
  接线统一）。
