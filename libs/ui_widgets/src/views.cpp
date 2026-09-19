#include "pwb/ui_widgets/views.hpp"

#include "pwb/ui_widgets/buttons.hpp"
#include "pwb/ui_widgets/ui_context.hpp"

#include <QHBoxLayout>
#include <QHeaderView>
#include <QSizePolicy>

namespace pwb::ui_widgets {

DensityRowDelegate::DensityRowDelegate(QObject* parent)
    : QStyledItemDelegate(parent) {}

QSize DensityRowDelegate::sizeHint(const QStyleOptionViewItem& option,
                                   const QModelIndex& index) const {
    const QSize base = QStyledItemDelegate::sizeHint(option, index);
    return {base.width(), qMax(base.height(), row_height())};
}

namespace {

template <typename View>
void install_density(View* view, DensityRowDelegate** delegate_out) {
    auto* delegate = new DensityRowDelegate(view);
    view->setItemDelegate(delegate);
    view->setAlternatingRowColors(true);
    view->setSelectionBehavior(QAbstractItemView::SelectRows);
    view->setWordWrap(false);
    *delegate_out = delegate;
    // density arrives on theme_changed(theme, density) — requery all rows.
    QObject::connect(theme_service(),
                     &pwb::platform_services::ThemeService::theme_changed,
                     view, [view](const QString&, const QString&) {
                         if (view->model() == nullptr) return;
                         if constexpr (requires { view->resizeRowsToContents(); }) {
                             view->resizeRowsToContents();
                         }
                         view->viewport()->update();
                     });
}

}  // namespace

PwbTableView::PwbTableView(QWidget* parent) : QTableView(parent) {
    QHeaderView* hh = horizontalHeader();
    hh->setDefaultSectionSize(120);
    hh->setHighlightSections(false);
    hh->setStretchLastSection(true);
    verticalHeader()->setVisible(false);
    verticalHeader()->setDefaultSectionSize(row_height());
    setShowGrid(false);
    install_density(this, &delegate_);
}

PwbTreeView::PwbTreeView(QWidget* parent) : QTreeView(parent) {
    setUniformRowHeights(true);
    setIndentation(14);
    setHeaderHidden(true);
    setSelectionBehavior(QAbstractItemView::SelectRows);
    install_density(this, &delegate_);
}

PwbCommandBar::PwbCommandBar(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("PwbCommandBar"));
    setFixedHeight(toolbar_height());
    layout_ = new QHBoxLayout(this);
    layout_->setContentsMargins(6, 2, 6, 2);
    layout_->setSpacing(2);
    connect(theme_service(),
            &pwb::platform_services::ThemeService::theme_changed, this,
            [this](const QString&, const QString&) {
                setFixedHeight(toolbar_height());
            });
}

QToolButton* PwbCommandBar::add_button(const QString& icon_name,
                                     const QString& text,
                                     const QString& tooltip, bool checkable,
                                     std::function<void()> slot) {
    auto* btn = new PwbToolButton(icon_name, text, checkable, /*chrome=*/true,
                                  QString(), this);
    if (!tooltip.isEmpty()) btn->setToolTip(tooltip);
    if (slot) {
        connect(btn, &QToolButton::clicked, this,
                [fn = std::move(slot)]() { fn(); });
    }
    layout_->addWidget(btn);
    return btn;
}

QFrame* PwbCommandBar::add_separator() {
    auto* sep = new QFrame(this);
    sep->setObjectName(QStringLiteral("PwbCommandSeparator"));
    sep->setFrameShape(QFrame::NoFrame);
    sep->setFixedWidth(1);
    sep->setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Expanding);
    layout_->addWidget(sep);
    return sep;
}

QWidget* PwbCommandBar::add_widget(QWidget* widget, int stretch) {
    layout_->addWidget(widget, stretch);
    return widget;
}

void PwbCommandBar::add_stretch() { layout_->addStretch(1); }

}  // namespace pwb::ui_widgets
