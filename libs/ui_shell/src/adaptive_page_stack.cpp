#include "pwb/ui_shell/adaptive_page_stack.hpp"

namespace pwb::ui_shell {

AdaptivePageStack::AdaptivePageStack(QWidget* parent)
    : QStackedWidget(parent) {
    connect(this, &QStackedWidget::currentChanged, this,
            [this](int) { updateGeometry(); });
}

QSize AdaptivePageStack::minimumSizeHint() const {
    QWidget* page = currentWidget();
    if (page != nullptr) {
        // Effective minimum = max(layout hint, explicit setMinimumSize).
        return page->minimumSizeHint().expandedTo(page->minimumSize());
    }
    return QStackedWidget::minimumSizeHint();
}

QSize AdaptivePageStack::sizeHint() const {
    QWidget* page = currentWidget();
    if (page != nullptr) {
        return page->sizeHint().expandedTo(page->minimumSize());
    }
    return QStackedWidget::sizeHint();
}

}  // namespace pwb::ui_shell
