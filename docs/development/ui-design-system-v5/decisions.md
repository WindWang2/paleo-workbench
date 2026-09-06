# UI Design System V5 — Decisions（ADR 级决策记录）

## D1. 演进而非推翻 token 架构
`tokens.py` 已是经 #1047 收敛的单一真源（三主题同词汇表 + 单一 build_qss）。
V5 只做加法：新增缺失语义 token（disabled/degraded/canvas chrome/overlay）、
修复 QSS 语法损坏、补组件层规则段。不引入第二套样式系统。
*理由：风险最低；现有 88+ targeted tests 钉住现有词汇。*

## D2. 组件层样式策略 = 全局 QSS objectName hook，不用 per-widget setStyleSheet
新组件（`ui/components/`）一律通过 objectName + 动态属性（`tone`/`variant`/`density`）
消费 `build_qss` 规则；主题/密度切换由全局 stylesheet 重载自然生效，
不需要每个组件订阅信号。需要运行时计算样式的地方用现有 `style.bind()`。
*理由：这是 style.py docstring 记录的既有方向；消灭「构造时快照」类 bug 的根治手段。*

## D3. 旧 objectName 词汇渐进迁移，不做大改名爆炸
`MapDockTitle` 等 25+ 处复制用 `PwbSectionHeader` 组件替换，但 tokens.py 中旧
QSS 规则保留一个别名期（旧 objectName 规则与新组件规则同渲染），
未迁移完不删旧规则。每处迁移以 grep 证据为准。
*理由：跨 12 页面的机械改名是大冲突面；别名期让迁移可分批验证。*

## D4. 密度感知用「访问器 + 订阅」，不改 Qt 布局系统
新增 `tokens.density_metric(name, density)` 访问器；固定高度调用点迁移为
构造时 + `theme_changed` 订阅更新（`style.bind_metrics` 助手）。
不引入 QSS 变量 hack 或自定义布局管理器。
*理由：Qt QSS 不支持自定义变量；订阅点数量可控（toolbar 3 文件 + app bar/rail）。*

## D5. QGIS 宿主边界（对应 U5）
QGIS 原生 `QgsMapCanvas`/`QgsLayerTreeView`/C++ 菜单 provider 的内部 chrome
**不做** QSS 覆写或重绘——保留 QGIS 专业语义（AGPL 边界 + 升级稳定性）。
宿主侧（docks、面板、状态条、工具按钮）全部 Design System 化。
Canvas 底色属地图渲染属性，不视为 UI chrome，不动。
*理由：goal 明确「目标不是重画 QGIS」；避免 native bridge ABI 面。*

## D6. 降级态是 UI 组件而非字符串协议变更
`backend_status` 文本协议保留（#1164 契约），只在渲染端统一为
`PwbInlineStatus`/`PwbErrorState`。不改 bridge/harness 语义。
*理由：不越 ownership 边界；最小接口改动。*

## D7. Command Palette 真源 = 命令注册表；最近使用是 UI 态
`ui/command_registry.py` 单例注册（id/label/shortcut/keywords/runnable），
来源：页面导航、面板显隐、主题/密度、布局 preset、项目动作。
最近使用存 QSettings（UI 态，非数据权威，不进 catalog）。
快捷键注册走 `ui/shortcuts.py` 中央表并做冲突检测（同 QKeySequence 双注册 →
log warning + 后注册者胜出，遵循 Qt 语义）。
*理由：现有 CommandPalette 是写死的页面列表；注册表让它可持续扩展且喂 shortcut hints。*

## D8. Visual regression：offscreen grab + 阈值报告，不设自动像素门禁
沿用 `capture_workstation_screens.py` 的 offscreen `QWidget.grab()` 机制，
扩展矩阵驱动与 masking；diff 以报告形式输出（像素比例 + 区域结构），
**不**作为 CI 门禁——重要结构仍靠语义 Qt tests 钉住。
*理由：goal 明确「不要把像素差阈值当唯一验收」；offscreen 渲染在不同
GPU/字体环境下有合法抖动。*

## D9. Prototype 处理 = 注记，不移动
`ui/pages/prototypes/*.html` 被 wheel 资产测试钉住（`test_wheel_assets.py:48`）；
`workstation_composite_prototype.py` 零 importer。统一加 NON-PRODUCTION 头注 +
lint allowlist 分组，不移动文件。
*理由：移动会破坏打包资产断言与 git 历史；风险无收益。*

## D10. 科学/引擎域色是例外而非债务
数据 colormap（`mapping_page.py:797`）、岩性图例色（lithology 语义）、
地震剖面色标、几何编辑 pen 色（编辑会话红/蓝语义）**保留**为 allowlist：
它们编码领域语义而非 UI chrome。但统一改为引用 token 常量或具名常量 + 注释。
*理由：UI token 化不应改变科学视觉语义（goal 硬约束）。*

## D11. 编译/测试纪律
UI 方向零 native 重建（vendored QGIS 复用 main worktree 的 engine checkout，
`run_env.sh` 包装）；pytest 串行/小批；offscreen 平台；
每个里程碑 commit 前跑 targeted tests。
