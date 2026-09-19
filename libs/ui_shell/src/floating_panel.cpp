#include "pwb/ui_shell/floating_panel.hpp"

#include <QHBoxLayout>
#include <QSizeGrip>
#include <QVBoxLayout>

namespace pwb::ui_shell {

namespace {
// Python uses workstation_icon("pane-restore.svg") / ("rb-clear.svg") —
// native fallback: text glyphs keep the affordance without the icon theme.
constexpr int kSpace1 = 4;
constexpr int kSpace2 = 8;
}  // namespace

FloatingPanel::FloatingPanel(std::string key, const QString& title,
                             QWidget* parent)
    : QWidget(parent), key_(std::move(key)) {
    setWindowTitle(title);
    // A real top-level window even when a parent widget is handed over.
    setWindowFlags(Qt::WindowType::Window);
    setObjectName(QStringLiteral("FloatingPanel"));
    setMinimumSize(240, 180);

    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(kSpace1, kSpace1, kSpace1, kSpace1);
    root->setSpacing(kSpace1);

    // Thin custom title bar: title · dock-back · close.
    auto* title_bar = new QWidget(this);
    title_bar->setObjectName(QStringLiteral("FloatingPanelTitleBar"));
    auto* bar_layout = new QHBoxLayout(title_bar);
    bar_layout->setContentsMargins(kSpace2, 0, 0, 0);
    bar_layout->setSpacing(kSpace1);
    title_label_ = new QLabel(title, title_bar);
    title_label_->setObjectName(QStringLiteral("FloatingPanelTitle"));
    bar_layout->addWidget(title_label_);
    bar_layout->addStretch(1);
    auto* dock_back_button = new QToolButton(title_bar);
    dock_back_button->setText(QStringLiteral("⇩"));
    dock_back_button->setToolTip(QStringLiteral("停靠回原位 (Dock back)"));
    QObject::connect(dock_back_button, &QToolButton::clicked, this, [this] {
        emit dock_back_requested(
            QString::fromStdString(key_));
    });
    bar_layout->addWidget(dock_back_button);
    auto* close_button = new QToolButton(title_bar);
    close_button->setText(QStringLiteral("×"));
    close_button->setToolTip(QStringLiteral("隐藏浮动面板 (Hide)"));
    QObject::connect(close_button, &QToolButton::clicked, this,
                     &QWidget::close);
    bar_layout->addWidget(close_button);
    root->addWidget(title_bar);

    // Central slot for the reparented panel widget.
    content_host_ = new QWidget(this);
    content_host_->setObjectName(QStringLiteral("FloatingPanelContent"));
    content_layout_ = new QVBoxLayout(content_host_);
    content_layout_->setContentsMargins(0, 0, 0, 0);
    root->addWidget(content_host_, 1);

    // Bottom-right resize grip.
    auto* grip_row = new QHBoxLayout();
    grip_row->setContentsMargins(0, 0, 0, 0);
    grip_row->addStretch(1);
    grip_row->addWidget(new QSizeGrip(this));
    root->addLayout(grip_row);
}

void FloatingPanel::set_content(QWidget* widget) {
    content_layout_->addWidget(widget);
}

QWidget* FloatingPanel::take_content() {
    QLayoutItem* item = content_layout_->takeAt(0);
    QWidget* widget = item != nullptr ? item->widget() : nullptr;
    if (widget != nullptr) {
        widget->setParent(nullptr);
    }
    return widget;
}

void FloatingPanel::set_panel_title(const QString& title) {
    setWindowTitle(title);
    title_label_->setText(title);
}

void FloatingPanel::showEvent(QShowEvent* event) {
    emit_visibility(true);
    QWidget::showEvent(event);
}

void FloatingPanel::hideEvent(QHideEvent* event) {
    // close() hides too, so dock-back-close, the hide button, Alt+F4 and any
    // direct hide() all report exactly once through here.
    emit_visibility(false);
    QWidget::hideEvent(event);
}

void FloatingPanel::emit_visibility(bool visible) {
    // Only panels hosting content report visibility: an empty window's
    // show/hide is controller lifecycle, not user-visible panel state
    // (dock-back closes an emptied window and must stay silent).
    if (content_layout_->count() > 0) {
        emit visibility_changed(QString::fromStdString(key_), visible);
    }
}

}  // namespace pwb::ui_shell
