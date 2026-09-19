#include "pwb/ui_pages_mapedit/tag_widgets.hpp"

#include "pwb/ui_shell/style_registry.hpp"
#include "pwb/ui_widgets/icon_factory.hpp"

#include <QDialogButtonBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QVBoxLayout>

namespace pwb::ui_pages_mapedit {
namespace {

// tokens.FONT_SIZE_STATUS / RADIUS_BUTTON etc. are palette keys in the C++
// theme token table — read at render time (style.bind parity).
QString tok(const char* key) {
    const auto& pal = ui_shell::style_palette();
    const auto it = pal.find(key);
    return it != pal.end() ? QString::fromStdString(it->second) : QString();
}

QString pal(const char* key) {
    const auto& p = ui_shell::style_palette();
    const auto it = p.find(key);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

}  // namespace

TagBadge::TagBadge(const QString& tag_name, bool removable, QWidget* parent)
    : QWidget(parent), tag_name_(tag_name.trimmed()) {
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(6, 2, 6, 2);
    layout->setSpacing(4);

    label = new QLabel(QStringLiteral("#%1").arg(tag_name_), this);
    ui_shell::style_bind(label, [] {
        return QStringLiteral(
                   "color: %1; font-size: %2; font-weight: 500;")
            .arg(pal("PRIMARY"), tok("FONT_SIZE_STATUS"));
    });
    layout->addWidget(label);

    if (removable) {
        remove_btn = new QPushButton(this);
        remove_btn->setFixedSize(14, 14);
        remove_btn->setCursor(Qt::PointingHandCursor);
        remove_btn->setToolTip(QStringLiteral("移除标签"));
        remove_btn->setIcon(ui_widgets::workstation_icon(
            QStringLiteral("rb-clear.svg")));
        ui_shell::style_bind(remove_btn, [] {
            return QStringLiteral(
                "QPushButton { border: none; background: transparent;"
                " padding: 0px; }");
        });
        connect(remove_btn, &QPushButton::clicked, this,
                [this]() { emit remove_requested(tag_name_); });
        layout->addWidget(remove_btn);
    }

    ui_shell::style_bind(this, [] {
        return QStringLiteral(
                   "QWidget { background-color: %1;"
                   " border: 1px solid %2; border-radius: %3px; }")
            .arg(pal("BG_SIDEBAR"), pal("BORDER"), tok("RADIUS_BUTTON"));
    });
}

// --- TagContainerWidget ------------------------------------------------------

TagContainerWidget::TagContainerWidget(bool removable, QWidget* parent)
    : QWidget(parent), removable_(removable) {
    layout_ = new QHBoxLayout(this);
    layout_->setContentsMargins(0, 0, 0, 0);
    layout_->setSpacing(4);  // tokens.SPACE_1

    add_btn = new QPushButton(QStringLiteral("+ 标签"), this);
    add_btn->setObjectName(QStringLiteral("SecondaryButton"));
    add_btn->setToolTip(QStringLiteral("添加新标签"));
    add_btn->setFixedHeight(22);
    ui_shell::style_bind(add_btn, [] {
        return QStringLiteral(
                   "QPushButton { font-size: %1;"
                   " padding: 0px 6px; border-radius: %2px; }")
            .arg(tok("FONT_SIZE_STATUS"), tok("RADIUS_BUTTON"));
    });
    connect(add_btn, &QPushButton::clicked, this,
            [this]() { prompt_add_tag(); });
    layout_->addWidget(add_btn);
    layout_->addStretch();
}

void TagContainerWidget::set_tags(const QStringList& tags) {
    tags_.clear();
    for (const auto& t : tags) {
        const QString trimmed = t.trimmed();
        if (!trimmed.isEmpty()) {
            tags_.append(trimmed);
        }
    }

    // Clear existing badges (keep add_btn and stretch — the last 2 items).
    while (layout_->count() > 2) {
        QLayoutItem* item = layout_->takeAt(0);
        if (item->widget() != nullptr && item->widget() != add_btn) {
            item->widget()->deleteLater();
        }
        delete item;
    }

    // Re-add tag badges before add_btn.
    for (const QString& tag : tags_) {
        auto* badge = new TagBadge(tag, removable_, this);
        connect(badge, &TagBadge::remove_requested, this,
                [this](const QString& name) { on_remove_tag(name); });
        layout_->insertWidget(layout_->count() - 2, badge);
    }
}

void TagContainerWidget::on_remove_tag(const QString& tag_name) {
    if (tags_.contains(tag_name)) {
        tags_.removeOne(tag_name);
        set_tags(tags_);
        emit tag_removed(tag_name);
    }
}

void TagContainerWidget::prompt_add_tag() {
    TagInputDialog dlg(tags_, this);
    if (dlg.exec() == QDialog::Accepted) {
        const QString new_tag = dlg.get_tag_name();
        if (!new_tag.isEmpty() && !tags_.contains(new_tag)) {
            tags_.append(new_tag);
            set_tags(tags_);
            emit tag_added(new_tag);
        }
    }
}

// --- TagInputDialog ------------------------------------------------------------

TagInputDialog::TagInputDialog(const QStringList& existing_tags,
                               QWidget* parent)
    : QDialog(parent) {
    setWindowTitle(QStringLiteral("添加标签"));
    setMinimumWidth(280);
    for (const auto& t : existing_tags) {
        existing_lower_.append(t.toLower());
    }

    auto* layout = new QVBoxLayout(this);
    label = new QLabel(QStringLiteral("请输入标签名称:"), this);
    layout->addWidget(label);

    input = new QLineEdit(this);
    input->setPlaceholderText(
        QStringLiteral("例如: 重点井, 探井, 2026..."));
    layout->addWidget(input);

    error_label = new QLabel(QString(), this);
    ui_shell::style_bind(error_label, [] {
        return QStringLiteral("color: %1; font-size: %2;")
            .arg(pal("ERROR_RED"), tok("FONT_SIZE_STATUS"));
    });
    layout->addWidget(error_label);

    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this,
            [this]() { validate_and_accept(); });
    connect(buttons, &QDialogButtonBox::rejected, this,
            [this]() { reject(); });
    layout->addWidget(buttons);
}

QString TagInputDialog::get_tag_name() const {
    QString name = input->text().trimmed();
    while (name.startsWith(QLatin1Char('#'))) {
        name = name.mid(1);
    }
    return name;
}

void TagInputDialog::validate_and_accept() {
    const QString name = get_tag_name();
    if (name.isEmpty()) {
        error_label->setText(QStringLiteral("标签名称不能为空"));
        return;
    }
    if (existing_lower_.contains(name.toLower())) {
        error_label->setText(QStringLiteral("该标签已存在"));
        return;
    }
    accept();
}

}  // namespace pwb::ui_pages_mapedit
