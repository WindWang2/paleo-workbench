# 09 — Accessibility & Keyboard (V11)

## 键盘

| 项 | V11 处置 |
|---|---|
| Tab order（此前全包零 setTabOrder） | 8 个复杂页显式链：home(3 对)/preparation(8)/seismic_prediction(14)/stratigraphy_correlation(20)/geological_modeling_3d(48)/mapping(8 对 + 面板轨道命名)/review_export(4)/visualization(5)——按视觉顺序链接真实交互控件（输入→主按钮→主列表→次级面板），不动构造序 |
| 数字快捷键守卫缺口（F2） | `focus_in_text_input` 并入 QSpinBox/QDoubleSpinBox/可编辑 QComboBox/视图内联编辑器——裸数字 1-5 页导航不再在这些控件里抢键 |
| F5 刷新 / F1 帮助（F3） | `core:page.refresh`（刷新当前页，无破坏性）/ `core:help.context`（打开 palette——工具条目携带需求/影响详情 tooltip，即上下文帮助入口；不弹大段教学窗） |
| 树/表键盘焦点可见（E4） | 全局 QSS `::item:focus`（FOCUS_RING） |
| Enter/Escape | palette/阶段条/对话框沿用既有正确处理；geo3d 的 keyPressEvent Escape 透传经测试钉住 |

## 无障碍标签

- icon-only 按钮 accessibleName 补齐：mapping 页面板菜单/5 个 dock 轨道切换、四页浮动按钮（⇱「浮动面板」）等 10 处；既有 rail 折叠钮等保持。
- rail 模式按钮 tooltip/accessibleName 统一为完整语义句（「资源管理器 · 数据资源（按类型浏览数据资产）」等）。

## whatsThis（边界决策）

未引入 whatsThis 层——palette 详情 tooltip + 状态语言双信号已覆盖主要复杂操作的解释需求；大段教学内容违反 goal §18。记录于 12-known-limitations。

## 测试

`tests/test_v11_a11y.py`（新，15+ 断言）：8 页 tab order 存在性与链方法幂等、icon-only 按钮 accessibleName 全查（home/mapping 运行时枚举 + Qt 内部件排除规则）、geo3d Escape 透传。`tests/test_a11y_dpi_v6.py` 全绿保持。
