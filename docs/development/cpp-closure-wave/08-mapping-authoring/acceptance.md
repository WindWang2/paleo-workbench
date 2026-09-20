# 08 — acceptance（验收口径与证据登记）

## 本线验收（任务书）

1. **真实图层编辑**：编图页编辑视图为 ui_pages_mapedit 真件（非占位文本），可选中/移动/
   顶点编辑/创建要素，经 ui_data_core 命令栈。
2. **撤销/重做**：场景命令栈 undo/redo 可用且与 dirty 联动。
3. **修改后保存/放弃**：保存走 apply_features_to_document → MapDocumentService.save_file
   （原子写+bak）；放弃恢复到上次保存态；拓扑门禁 validate_for_save。
4. **文档切换（多期次/图件）**：多 MapDocumentService bank，切换前 dirty 守卫
   （保存/放弃/取消），切换后场景重绑。
5. **恢复一致**：重开（load_file）后 crs/每层 style/extent/view_state 与保存前一致。
6. **PreparationPage 产物可被 02/03 消费**：制备提交写 project.factor_map_tasks、
   等值线提交写 project.contour_drafts（libs/project schema 段），workflow/science 面
   经既有 update_mapping_page/update_preparation_page 缝隙可达。
7. **composition_panel 真入构建且在产品显示**：pwb_ui_seqviz_qt 源表含 composition_panel.cpp
   且编译通过；产品编图页 composer dock 装真件（非“未迁移”占位）。
8. **不在范围**：审查报告/导出审签（09）、QGIS provider 内核优化（14）、原生 QGIS 桥编辑
   会话（PR #1412）。

## 证据登记（滚动更新）

| 项 | 命令/产物 | 结果 | 时间 |
|---|---|---|---|
| configure | gate Configure build/presets/linux-ninja (Release, j2) | exit 0，Generating done | R1 |
| 基线构建 | gate Build -j2 | exit 0，1163/1163 | R1 |
| composition 面板 | ui_seqviz.composition_panel（offscreen，21 检查） | exit 0 全过 | R6 |
| preparation 页 | ui_pages_data.preparation_page（offscreen，22 检查） | exit 0 全过 | R6 |
| closure 平台电池 | platform.closure_mapping（bank 深测 + MainWindow 级安装验证） | PASS | R6 |
| 受影响回归 第一遍 | ctest -j2 正则 platform\./ui_seqviz/ui_pages/mapping_document/ui_map | 36/36 100% | R6 |
| 受影响回归 第二遍 | 同上（确定性重跑） | 36/36 100% | R6 |
| composition 面板 | 待登记 | | R2 |
| preparation 页 | 待登记 | | R3 |
| closure 适配器 | 待登记 | | R4 |
| 产品装配/平台测试 | 待登记 | | R5 |
| 受影响回归×2 | 待登记 | | R6 |

## 诚实限制（预计）

- PR #1412 未合并前的原生 QGIS 桥编辑（NativeEditBridgeStack 适配）不属本线交付；
  场景级编辑闭环（ui_data_core 命令栈 + mapping_document 持久化）为真实可验收路径。
- layout_export 的 SVG/PDF 引擎若平台不可用，导出走 seam 的诚实失败面（非假成功），
  与 Python“composer_fallback 警告”对齐。
- macOS/Windows 双平台验证不在本机执行能力内，标未执行，交 12 统一矩阵。
