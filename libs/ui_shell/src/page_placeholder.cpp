#include "pwb/ui_shell/page_placeholder.hpp"

#include <QVBoxLayout>

#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_shell {

PagePlaceholder::PagePlaceholder(const QString& page_name, QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("PagePlaceholder"));
    name_label_ = new QLabel(page_name + QStringLiteral("\n(占位页, 待实现)"), this);
    name_label_->setAlignment(Qt::AlignmentFlag::AlignCenter);
    // style_bind: the label text color refreshes with the theme (the
    // Python original snapshot the light value at construction time until
    // style.bind fixed it).
    style_bind(name_label_, [] {
        const auto pal = style_palette();
        const auto it = pal.find("TEXT_SECONDARY");
        const QString color = it == pal.end()
                                  ? QStringLiteral("#666666")
                                  : QString::fromStdString(it->second);
        return QStringLiteral("color: %1; font-size: 16px;").arg(color);
    });
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addStretch();
    layout->addWidget(name_label_);
    layout->addStretch();
}

}  // namespace pwb::ui_shell
