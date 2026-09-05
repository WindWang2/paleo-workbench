# UI Design System V5 — Target State（逐项验收清单）

Goal 结束前每项必须真实完成，不留伪完成项。证据列指向 verification.md 的对应条目。

## A. Token 单一化（U1）

- [x] A1 `tokens.py:752-754` QSS 语法损坏修复（MenuBar 规则残片）。
- [x] A2 新增语义 token：禁用态（BG/TEXT）、degraded 过程态、canvas chrome 组
      （ink/chrome/selection/snap/edit）、chart/map overlay、focus 宽度等，
      三主题各自策展；现有词汇不推翻。
- [x] A3 密度访问器：提供 `control_height(density)` / `row_height(density)` /
      `toolbar_height(density)` 运行时访问器，`DENSITY_TOKENS` 仍为唯一真源。
- [x] A4 token 卫生 lint：`tests/test_ui_token_hygiene.py` 扫描
      `paleo_workbench/`（排除 prototypes + 显式 allowlist）禁止新裸 hex
      setStyleSheet / QColor 字面色 / `color: white` 字面量；allowlist 收敛到
      已知必要例外（科学 colormap、引擎语义色）。
- [x] A5 `build_qss` 新增组件层规则段（Pwb* objectName），旧规则不删除。

## B. 通用组件层（U2）— `paleo_workbench/ui/components/`

- [x] B1 `PwbButton`（variant: primary/secondary/tertiary/danger，对象名映射现有 QSS）。
- [x] B2 `PwbToolButton`（icon+text/纯 icon，DPR-safe icon）。
- [x] B3 `PwbSplitButton`（动作 + 下拉）。
- [x] B4 `PwbSearchBox`（清除按钮 + placeholder，替代 "✕" QLabel）。
- [x] B5 `PwbBadge`（tone: neutral/primary/success/warning/error/process）。
- [x] B6 `PwbInlineStatus`（icon+text 行内状态）。
- [x] B7 `PwbEmptyState` / `PwbErrorState` / `PwbLoadingState`（统一三态 + retry 钩子）。
- [x] B8 `PwbProgress`（state-colored chunk，复用任务进度 QSS 词汇）。
- [x] B9 `PwbSectionHeader`（统一标题；替换 MapDockTitle 复制 ≥ 20 处）。
- [x] B10 `PwbInspectorSection` + `PwbPropertyEditor`（label/value 行、missing 语义）。
- [x] B11 `PwbTableView` / `PwbTreeView`（密度感知行高、交替行、选中语义）。
- [x] B12 `PwbCommandBar`（context 工具条 + 分隔簇）。
- [x] B13 `PwbToast` 非阻塞通知（主窗口叠加，自动消退，不入数据权威）。
- [x] B14 form row / unit field 助手。
- [x] B15 组件全部 theme-aware（全局 QSS hook，不构造时快照）、density-aware、
       keyboard/focus-aware；`tests/test_ui_components.py` 覆盖三主题两密度渲染。

## C. 页面迁移（U3）

- [x] C1 geological_modeling_3d_page：43 处 setStyleSheet → 组件/QSS hook；
       hex 字面色清除。
- [x] C2 module_relationship：white×7 清除、radius 对齐 4px、固定 1180px 画布
       改为可伸缩（min 尺寸 + scroll）。
- [x] C3 project_well_map_page：7 个 hex + pyqtgraph 底色 token 化，dark 可用。
- [x] C4 home_page：重复空态 → PwbEmptyState；固定尺寸弹性化。
- [x] C5 inspector_panel：14 处内联 → QSS hook/组件；18/22px 控件密度化。
- [x] C6 factor_task_panel 复用 TaskPanelBase 布局词汇。
- [x] C7 data 家族（data_detail/completeness/onboarding/tag_widgets）→ 组件化。
- [x] C8 首页/数据/测井预测/地震预测/层序格架/地层对比/可视化/制备/编图/成图审核/
       井震联合/Workstation shell 全部过一遍截图 review（矩阵留档）。
- [x] C9 状态缺口：页面具备 loading/error/empty 一致语义（至少 review/sequence/
       preparation/well_seismic_joint 补齐）。

## D. Dialog / Menu / Table / Inspector（U4）

- [x] D1 12 个 QDialog 盘点统一：QDialogButtonBox 按钮序、objectName、
       去重 3 份玻璃拟态 → 统一 dialog chrome。
- [x] D2 TrackVisibilityDialog：标准按钮、无 color: white。
- [x] D3 破坏性操作确认样式统一（QSS 危险按钮）。
- [x] D4 context menu 全部走全局 QMenu QSS（清除 asset_context_menu 局部覆盖）。
- [x] D5 表格选择/多选/键盘语义一致（PwbTableView 落地 ≥ 2 处生产表格）。

## E. 宿主匹配（U5）

- [x] E1 well_log_host / well_section_host 白底 hex → token（style.bind/QSS）。
- [x] E2 unified_map_canvas painter 颜色 → palette 感知（per-paint palette_for）。
- [x] E3 qgis_stack/display_canvas `#ffe066` → canvas selection token。
- [x] E4 降级态统一组件：QGIS bridge 不可用 / welllog 绑定缺失 / 地震 lazy
       使用 PwbErrorState/PwbInlineStatus 语义（保留诚实文本，不再裸 QLabel）。
- [x] E5 QGIS 原生边界 ADR：QGIS 内部 chrome 不强行重写（决策记录）。

## F. 专业 UX 增强（U6）— 真功能

- [x] F1 Command Palette 升级：统一命令注册表（页面/面板/主题/密度/布局 preset/
       项目动作），fuzzy 过滤 + 最近使用（QSettings，UI 态非数据权威）+ 快捷键显示。
- [x] F2 中央快捷键注册表 `ui/shortcuts.py`：注册/冲突检测/喂给 palette；
       迁移现有散落 QShortcut。
- [x] F3 Escape/Enter 语义统一（palette/dialog/busy）。
- [x] F4 多显示器恢复健壮性：floating geometry 落在屏幕外时 clamp。
- [x] F5 busy/progress/cancel 统一入口（复用 TaskCenter；busy cursor helper）。

## G. Theme / Density / DPI / A11y（U7）

- [x] G1 构造时 light 快照清除：重灾区文件迁移到 QSS hook 或 style.bind
       （status_bar/page_placeholder/task_center STATE_COLORS 必改）。
- [x] G2 密度运行时切换对 toolbar/control 高度生效（metrics 订阅机制 +
       map_edit_toolbar/data_toolbar/map_factor_shelf 迁移）。
- [x] G3 截图矩阵：light/dark/high_contrast × compact/comfortable ×
       1180×720 / 1440×900 / 1920×1080 关键页面无 clipping/不可达控件。
- [x] G4 HC 模式非颜色信号：badge/状态同时有文字/图标（抽查）。

## H. Visual Regression（U8）

- [x] H1 修复 capture_workstation_screens.py stale hook（process_hub→agent_panel）。
- [x] H2 harness：deterministic fixture、page-state driver、矩阵（theme×density×
       size×page）、动态字段 masking、baseline 目录、diff 报告（像素+结构阈值，
       人工判读不入自动门禁）。
- [x] H3 baseline-v5 12 状态 + 迁移后集合入库（visual_qa/，PNG 不塞 git LFS，
       控制体积或仅留关键证据于 docs/ui-redesign/screenshots）。
- [x] H4 QA 报告（docs/development/ui-design-system-v5/qa-report.md）。

## I. 技术债清仓（U9）

- [x] I1 文本字形图标 8 处 → SVG。
- [x] I2 prototypes 注明 NON-PRODUCTION（不移动文件，wheel HTML 资产测试不动）。
- [x] I3 死 QSS / 重复尺寸清理（有 grep 证据才删）。

## J. 对抗性验证（U10）

- [x] J1 project create/open/switch/close 循环无回归（现有 lifecycle 测试通过）。
- [x] J2 dock float/dock/tabify、Inspector collapse/restore。
- [x] J3 theme/density 运行时切换往返（无残留 light 快照）。
- [x] J4 缺失 native backend / QGIS bridge 不可用合法路径。
- [x] J5 task running/cancelled/failed 显示。
- [x] J6 长 CJK/EN 文本 dialog 不截断。
- [x] J7 空项目 / 大列表（paged fixture）UI 不阻塞。

## K. 交付

- [x] K1 三轮独立 review 完成且问题当场修复。
- [x] K2 targeted Qt tests 全绿（token/theme/workstation/components/layout/lifecycle）。
- [x] K3 原子 commits（每里程碑一 commit 以上）。
- [x] K4 PR → main：背景/架构/功能/测试证据/性能证据/兼容性/风险/未做事项。
