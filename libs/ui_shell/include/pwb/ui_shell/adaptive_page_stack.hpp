#pragma once

// Port of paleo_workbench/ui/app_shell.py AdaptivePageStack (UI-01).
// 页面栈：minimumSizeHint 只反映「当前页」（V9 审计 B-1）。
// QStackedWidget 默认取全部页最大值——栈里有一个宽页，其它窄页就会带
// 幽灵横向滚动条。覆盖为逐页计算；HubPage 内部子模块栈仍取该 hub 各
// 子模块的最大值（精度止于 hub 级，滚动降级不受影响）。

#include <QStackedWidget>

namespace pwb::ui_shell {

class AdaptivePageStack : public QStackedWidget {
    Q_OBJECT
public:
    explicit AdaptivePageStack(QWidget* parent = nullptr);

    QSize minimumSizeHint() const override;
    QSize sizeHint() const override;
};

}  // namespace pwb::ui_shell
