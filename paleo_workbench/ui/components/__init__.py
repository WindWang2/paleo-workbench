"""Design System V5 共享组件层（``paleo_workbench.ui.components``）。

设计契约（decisions.md D2）：

- **theme-aware**：组件一律经 objectName + 动态属性消费
  ``tokens.build_qss`` 中的全局规则，不构造时快照主题值、不自带样式表；
  需要运行时计算的（图标染色、进度 chunk 色）每 paint/每次 set 取当前主题。
- **density-aware**：metrics 从 ``tokens.density_*`` 访问器实时取值，
  并订阅 ``theme_manager.theme_changed(theme, density)`` 重算。
- **keyboard/focus-aware**：标准 Qt focus 链 + QSS focus ring，不绕过。
- **无业务**：组件不触碰 catalog / SelectionContext / 项目模型。

入口：``from paleo_workbench.ui.components import PwbButton, ...``
"""
from paleo_workbench.ui.components.badges import PwbBadge, PwbInlineStatus
from paleo_workbench.ui.components.buttons import (
    PwbButton,
    PwbSplitButton,
    PwbToolButton,
)
from paleo_workbench.ui.components.dialog import PwbDialog
from paleo_workbench.ui.components.headers import (
    PwbInspectorSection,
    PwbPropertyEditor,
    PwbSectionHeader,
    section_header,
)
from paleo_workbench.ui.components.inputs import (
    PwbSearchBox,
    current_density,
    make_form_row,
)
from paleo_workbench.ui.components.states import (
    PwbEmptyState,
    PwbErrorState,
    PwbLoadingState,
    PwbProgress,
)
from paleo_workbench.ui.components.toast import PwbToast, notify
from paleo_workbench.ui.components.views import PwbCommandBar, PwbTableView, PwbTreeView

__all__ = [
    "PwbBadge",
    "PwbButton",
    "PwbCommandBar",
    "PwbDialog",
    "PwbEmptyState",
    "PwbErrorState",
    "PwbInlineStatus",
    "PwbInspectorSection",
    "PwbLoadingState",
    "PwbProgress",
    "PwbPropertyEditor",
    "PwbSearchBox",
    "PwbSectionHeader",
    "PwbSplitButton",
    "PwbTableView",
    "PwbToast",
    "PwbToolButton",
    "PwbTreeView",
    "current_density",
    "make_form_row",
    "notify",
    "section_header",
]
