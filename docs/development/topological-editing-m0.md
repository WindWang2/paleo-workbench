# 拓扑编辑迁移 M0 地基——实施记录（2026-09-12）

> 规格与路线图：[docs/specs/topological-editing-migration-spec.md](../specs/topological-editing-migration-spec.md) §8。
> M0 内容：CRS 契约件（域校验+引导框+推断锁定，§6）+ 会话集合管理器 +
> 停发短路 + 台账对齐（§3）。退出标准：场景 2、15 通过；现有镜像回归全绿。

## 落地清单（实现件 → 代码坐标）

| 实现件 | 位置 | 说明 |
|---|---|---|
| 坐标域谓词 | `mapping/crs_contract.py`：`crs_coordinate_domain` / `coordinate_domain_mismatch` | 地理 CRS = 轴定义经纬度全域（精确）；投影 CRS = pyproj area_of_use 角点变换（近似框，外扩 2% 容差）；不可推导 → None（fail-open：只拦可证明的失配） |
| 推断锁定 | `mapping/crs_contract.py`：`infer_crs_from_extent`；`project/models.py` `CoordinateReference.crs_locked` | 超经纬度域 → 保持本地；域内 → 建议 EPSG:4326（用户确认后声明+锁定）；范围不可用 → 不推断 |
| 新工程不预设地理 CRS | `project/models.py`：`project_crs` 默认 `""` | 未声明即本地坐标呈现/编辑（镜像 `set_destination_crs("")` 既有语义） |
| 进前段 CRS 门 | `mapping/crs_chain.py`：`evaluate_edit_entry`（`LayerCrsFacts` 输入） | 域校验（失配 → 阻止 + 受影响层全景）→ 会话集合层与画布同 CRS（V9 raw 帧/V10 fail-closed 语义保留） |
| 旧提交门退休 | `crs_chain.evaluate_commit_guard` 删除；`canvas_shim` 数字化提交不再查 CRS；`set_capture_layer_crs_provider` 钩子及 `composite_editing.attach_canvas` 接线一并移除 | 提交前不重复查（§6）；判定表语义由 `evaluate_edit_entry` 测试延续（`tests/test_v10_crs_chain_and_identity.py`） |
| 一次性引导框 | `ui/crs_guidance.py`：`CrsGuidanceDialog`；`composite_document._apply_crs_entry_guidance` / `_clear_crs_declaration` | 受影响层列表 + 一键「改为本地坐标（清除声明）」+ 取消；两个编辑入口（工具栏 toggle_editing / 树面板）都过进前段。清除范围 = 工程声明 + 工区内**可证明失配**的层自身声明（新建层会把工程声明烙进 layer.crs） |
| 打开工程兜底 | `project/domain.py`：`crs_domain_issues`；`manager.load` 告警 | 同一检测在 load 时呈现全景（非阻断） |
| 会话集合管理器 | `mapping/edit_session_set.py`：`EditSessionSet` + 进程级 `SESSION_SET` | 进入编辑 = {活动层}；`request_join(gate)` 按需生长（拒绝 → 不参与 + 原因供提示，场景 7 前置）；CRS 冻结 `allows_crs_change`；schema 互斥 `allows_schema_change`（集合内拒/集合外不受限）；栈绑定 `active_layer_ids(stack)` |
| 停发短路 | `mapping/qgis_mirror.py`：`mirror_snapshot_to_stack` 循环内 `edit_window` 分支 | 集合内层（绑定本栈）零数据重发、台账冻结、样式读回验证照跑（集合内漂移只诊断、修复顺延到关窗——重发/重建会毁编辑缓冲）；集合外层照常发布与 no-op 样式漂移自愈。会话未开启 = 空集合，发布行为与 M0 之前逐字节一致 |
| 台账对齐 | `mapping/qgis_mirror.py`：`align_publish_ledger` + `_LedgerEntry.authoritative` | commit 后直跳新基线（data_revision 跳新值、style token 重算、状态=镜像=真源；fields_sig token 随在途 V10 schema 通道并入）；从未发布/修订不可用 → False 走正常发布。fid 反查表按 provider 现值重建由 M1 committed\* 回写接线 |

## 验收证据

- `tests/test_topo_m0_foundation.py`（18 项）：场景 2（进前阻止 + 引导事实 +
  一键修复后放行 + 文档级流 + 对话框清除动作 + 打开工程兜底）、场景 15
  （A 层数据零重发/台账冻结、B 集合外样式重发与漂移自愈照常）、会话集合
  生命周期/门禁生长/冻结互斥/栈绑定、台账对齐后 no-op 钉子与关窗恢复。
- M0 直接影响域合并回归（177 过 / 3 条件跳过）：`test_mirror_*` /
  `test_v10_crs_chain_and_identity` / `test_v10_qgis_runtime_health` /
  `test_zorder_semantics`（显示序自上而下）/ `test_topology_*` /
  `test_project_models` / `test_domain_coords_contract` /
  `test_crs_distance_policy` / `test_interpretation_v9_crs_discipline` 等。
- 工程/目录批（`test_catalog_*` + `test_project_*` + onboarding）：682+ 过，
  仅 `test_project_models` 旧默认断言按 M0 契约更新（新工程不预设 4326）。
- 全量套件在本环境不可比：HEAD 起即有两处与 M0 无关的原生崩溃
  （qgis 桥清理段错误 @test_adversarial_ux_v10 上下文；native 后端
  线程池段错误 @~60%）。以「HEAD+loader修复」干净 worktree 为基线，
  工作站/复合批 41 失败中 39 项与基线完全一致（HEAD 潜伏：组 reconcile
  程序化树移动触发选择信号重置活动层——此前 Linux 套件因 loader 的
  Windows-only API 崩溃而无法暴露）；新增 4 项归因：
  - 拓扑工具门（crs_valid 把未声明误判为无效）→ **已修**：
    `composite_editing` crs_valid 语义 = 未声明（本地帧）合法，已声明才要求
    pyproj 可解析（防假声明，ADV-6 原意保留）。
  - 参考导入 GDAL 上报测试撞未声明拒绝门（V9 W3 策略仍正确）→ **已修**：
    测试声明 CRS 走 GDAL 路径；另补未声明拒绝路径钉子
    （`test_reference_import_refused_while_project_crs_undeclared`）。
  - `test_map_layer_properties_*` 标签页词表、`test_shell_undo_*` 井打开流：
    工作区在途 V10 未提交改动的配套测试未跟上（非 M0；改动文件
    map_layer_properties.py / shell.py / linked_workspace.py M0 未触碰）。

## M0 内的显式后置（M1 接线）

- 停发窗口在 M1 `startEditing`（编辑权迁移）时才由生产路径开启——M0 期间
  Python 会话仍是编辑权威，层内编辑经快照增量发布到画布（既有行为不变）。
- 首次导入的推断**对话**（建议声明、用户确认锁定）：谓词与 `crs_locked`
  已就绪；导入 UI 的确认流随 M1 编辑 UX 整合接线。
- fid 反查表按 provider 现值重建（场景 16）：M1 committed\* 回写时落地；
  全量重发路径本就重建该表。
