# 08 — Design System (V11)

## 主题架构（保持单一真源）

`tokens.py`（palette_for + build_qss 覆盖字典主题）→ `ThemeManager` → `style.bind` 动态注册表 → `install_theme_hook` 图标缓存失效。**未创建任何第二样式系统。**

## V11 变更

### Token/QSS（tokens.py）

- `::item:focus`（FOCUS_RING 描边）——树/表键盘焦点首次可见（E4）。
- 密度参数化扩展：`tab_padding`/`menu_padding`/`item_padding`/`combo_item_height` 进 `DENSITY_TOKENS`（compact 更紧），舒适值与现值一致（E5）。
- 类型刻度补齐：`FONT_SIZE_MICRO`(10px)/`FONT_SIZE_MINOR`(12px) token，build_qss 内 8 处字面量替换；`ON_SOLID` 徽章文字色 token 吸收最后 6 处 `#ffffff` 字面量（渲染值不变）。

### 主题跟随修复（E1——静态样式快照清零）

约 24 处构造时 `setStyleSheet(tokens.X)` 迁移到 `style.bind`（或全局 objectName 类）：filter_chips_bar、map_edit_view、preview_settings_panel、home_page、navigation_tree（顺带删除其手写 theme_changed 订阅）、action_header、activity_card、start_guide_card、workflow_contract_panel、well_seismic_joint_page、composite_visualization_panel、data_asset_table、map_canvas_panel、map_chrome_panel、governance_dialog 等。等宽字体字面量（Consolas/Cascadia）→ `FONT_FAMILY_MONO`。**亮色输出逐位不变；暗色首次正确跟随。**

### 图标主题路由（E2）

`workstation/common.py` 新增 `tinted_map_icon()`（SourceIn 染色、DPR 感知、缓存、主题切换失效）；8 个重复的裸 `QIcon(path)` 加载器统一路由。染色策略：**仅当 SVG 全部烘焙色为无彩色**（语义/多色图标跳过——tint 会抹掉语义色，如红色删除 X）。缺资产回落空 QIcon 的既有行为保持（5 个几何工具 SVG 缺失归 #1256/#1267，不在此补）。

### 编辑状态描边（E6）

`composite_editing.py` 4 个手写描边色 → `CANVAS_EDIT/CANVAS_SNAP/CANVAS_INK/CANVAS_CURSOR` 语义 token（仅颜色查换，零行为变化）；`seismic_view_panel` "Inline 剖面" 徽章的 ERROR_RED 误用 → PRIMARY（E7）；`mapping_stage_bar` setFixed 字面量 → min/max 对。

### 组件出口

`PwbDialog` 自 `ui/components` 导出（此前仅深导入）。

### 词汇

任务/成熟度/新鲜度状态一律经 `state_language` 词表（glyph+文字+tone 双信号）；BADGE tone 经 `tone_to_badge` 桥——三处私有状态→颜色映射退役（task_center 状态表保留但补 cancelling/degraded 缺项）。

## 验证

- `tests/test_ui_token_hygiene.py` / `test_ui_sizing_ratchet_v9.py`：注册表按快照策略更新（预算清零项 = 已迁移面）。
- 亮/暗切换冒烟：迁移控件 stylesheet 重渲染含暗色 palette 值；图标缓存主题切换失效。
- 视觉 QA v6–v10 全绿（v6 措辞断言对齐 V10 M10 单一真源）+ v11 矩阵（亮/暗 × 1280×720/1920×1080）。
