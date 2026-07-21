# 现代浅色主题与人性化 UI/设置 优化实施计划

> **目标**：全面升级 `paleo_workbench` 的 UI 视觉语言与交互体验，打造极其现代、精致的浅色主题（Modern Crisp Light Theme），强化视觉层级、圆角动效与人性化设置选项，确保测试 100% 绿色通过。

---

## 一、 视觉设计规范与 Token 升级

在 `paleo_workbench/tokens.py` 中升级现代浅色设计代币：

- **背景与层级**：
  - `BG_BODY`: `#f6f8fa`（柔和科技浅灰背景，突出白底卡片）
  - `BG_HEADER` / `BG_SIDEBAR`: `#ffffff`（纯白清爽面板）
  - `BG_SEARCH`: `#f1f5f9`（Slate 100 微暗填充）
- **品牌与状态色**：
  - `PRIMARY`: `#2563eb`（现代蓝 - Tailwind Blue 600）
  - `PRIMARY_HOVER`: `#1d4ed8` / `PRIMARY_PRESSED`: `#1e40af`
  - `SUCCESS`: `#10b981` / `WARNING`: `#f59e0b` / `ERROR`: `#ef4444`
- **边框与阴影**：
  - `BORDER`: `#e2e8f0` (Slate 200) / `BORDER_STRONG`: `#cbd5e1`
- **圆角与间距**：
  - `RADIUS_BUTTON`: 6px / `RADIUS_CARD`: 10px / `RADIUS_PANEL`: 10px

---

## 二、 人性化设置与动态样式系统

1. **设置扩展**：在 `PreviewSettings` / `PreviewSettingsStore` 中增加：
   - `density`: `"comfortable"` (默认) / `"compact"` (紧凑模式)
   - `theme_mode`: `"light"` (现代浅色) / `"system"`
2. **动态 QSS 生成器**：根据当前 `PreviewSettings`（字号、密度、主题）生成全局统一样式表，实现实时预览与即时生效。

---

## 三、 TDD 开发与验证步骤

1. **Task 1: Design Tokens & QSS Generator Unit Tests (RED)**
   - 编写 `tests/test_tokens.py` 验证 Token 常量、现代浅色配色规范与全局 QSS 生成。
2. **Task 2: 升级 `tokens.py` 与样式系统 (GREEN)**
   - 更新 `paleo_workbench/tokens.py`，加入现代 QSS 控件生成逻辑。
3. **Task 3: 扩展 `PreviewSettings` 设置面板 (GREEN)**
   - 在 `preview_settings.py` 中增加密度控制与主题预览，支持实时全局设置更新。
4. **Task 4: 全局 AppShell 与各页面 QSS 注入与细节精雕 (GREEN)**
   - 更新 `paleo_workbench/ui/app_shell.py` 及各工作台页面，施加现代浅色阴影、卡片边框与圆角控件。
5. **Task 5: 全量回归与测试验证**
   - 运行全量 Pytest 测试，确保 1125+ 个用例 100% 绿灯。
