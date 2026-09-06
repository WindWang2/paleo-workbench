# Workstation UX V6 — 06 视觉系统与状态语言

Date: 2026-09-07

## 1. Design System V5 基座不动

`tokens.py`（单源词汇 + 3 主题 + DENSITY_TOKENS）、`ui/theme.py`（运行时切换 + QSettings）、`ui/style.py`（style.bind 动态重渲染）、Pwb* 组件族、QSS objectName 纪律全部保持。V6 不重写样式系统。

## 2. 统一状态语言（`ui/workstation/state_language.py`）

一处定义全域状态 → `StateToken(glyph, label, tone)`：

| 类别 | 值域 |
|------|------|
| maturity | raw ▣ / derived ◈ / intermediate ◇ / output ★ / working ✎ / draft ✎ / reviewed ✓ / frozen ❄ / published ◉ |
| freshness | current ✓ / stale ↻ / missing ✕ |
| editability | editable ✎ / raw ▣ / locked 🔒 / none · |
| task | queued … / running ▶ / cancelling ⏸ / cancelled ■ / failed ✕ / done ✓ |
| backend | native ◆ / fallback ◌ / missing ✕ |
| permission | granted ✓ / read_only ▣ |

纪律：**glyph+文字双信号**（绝不只靠颜色/ tone）；未知值诚实「未知」（muted）；未知类别 = KeyError（编程错误尽早暴露）。消费者：状态条工作台段、检查器域行、WRITE 授权对话框（动作卡 ▣ 前缀）。取消中(⏸)≠已取消(■) 的任务中心既有区分并入词汇。

## 3. 本轮 bounded 视觉/可达性修复

- **DPR**：`components/states.py` 移除 `setDevicePixelRatio(1.0)` 强制，改显式 DPR 的 Qt6 pixmap 重载（HiDPI 不再模糊/倍增；DPR 1 行为不变）。
- **图标按钮可达名**：workstation chrome 内 icon-only 按钮（面板菜单、活动栏折叠、资源管理器刷新）补 accessibleName/Description（状态感知文案）；文本标签按钮不加机械名（负断言钉住）。
- **快捷键单绑**：Ctrl+S/N/O/F 直连 QShortcut 收敛入中央注册表。
- 218 处 legacy 页面内联样式与 density 盲字面量的**机械迁移未做**（见 10——需 lint ratchet 推进而非本轮手改）。

## 4. visual QA V6（`visual_qa_v6.py` + `baseline-v6-matrix/`）

- 6 个新确定性状态：mapping_stage_phase1/2/3、command_palette_context、write_grant_dialog、status_workbench_segment（全部 offscreen/无桥可构造，回退态诚实可见）。
- **语义检查**（非像素）：阶段条标记 + 面板页 + add_line 阶段可见性；palette 禁用项含原因且不可激活；授权对话框拒绝默认；状态段含后端/阶段文案。检查结果落 `_checks/*.json`。
- 36 张新基线（6 状态 × light × 2 密度 × 3 尺寸）；v5 的 30 张基线未动（测试钉住）。
- 证据页与再生成说明：`visual_qa/v6_evidence/README.md`（含并发 QSettings 注册表竞态告警）。
