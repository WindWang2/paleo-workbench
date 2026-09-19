#include "pwb/ui_widgets/badges.hpp"

#include "pwb/ui_widgets/icon_factory.hpp"
#include "pwb/ui_widgets/ui_context.hpp"

#include <QHBoxLayout>

#include <optional>

namespace pwb::ui_widgets {

const char* const kBadgeTones[] = {"neutral", "primary", "success",
                                   "warning", "error"};

BadgeToneIcon badge_tone_icon(const QString& tone) {
    static const QHash<QString, BadgeToneIcon> table = {
        {"neutral", {"", "TEXT_SECONDARY"}},
        {"primary", {"", "PRIMARY"}},
        {"success", {"circle-check.svg", "SUCCESS"}},
        {"warning", {"alert-triangle.svg", "WARNING"}},
        {"process", {"refresh-cw.svg", "ACCENT"}},
        {"error", {"alert-triangle.svg", "ERROR"}},
    };
    return table.value(tone, {"", "TEXT_SECONDARY"});
}

namespace {

bool is_badge_tone(const QString& tone) {
    for (const char* t : kBadgeTones) {
        if (tone == QLatin1String(t)) return true;
    }
    return false;
}

// Python None-vs-"" semantics: null QString = None (use tone default /
// explicit icon), non-null "" = explicitly no icon.
std::optional<QString> none_if_null(const QString& s) {
    return s.isNull() ? std::nullopt : std::optional<QString>(s);
}

}  // namespace

PwbBadge::PwbBadge(const QString& text, const QString& tone, QWidget* parent)
    : QLabel(text, parent) {
    setObjectName(QStringLiteral("PwbBadge"));
    setAlignment(Qt::AlignCenter);
    set_tone(tone);
}

void PwbBadge::set_tone(const QString& tone) {
    tone_ = is_badge_tone(tone) ? tone : QStringLiteral("neutral");
    setProperty("tone", tone_);
    repolish(this);
}

PwbInlineStatus::PwbInlineStatus(const QString& text, const QString& tone,
                                 const QString& icon_name, QWidget* parent)
    : QWidget(parent), tone_(tone), explicit_icon_(icon_name) {
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(6);
    icon_label_ = new QLabel(this);
    icon_label_->setFixedSize(16, 16);
    icon_label_->setVisible(false);
    text_label_ = new QLabel(text, this);
    text_label_->setObjectName(QStringLiteral("PwbInlineStatusText"));
    text_label_->setWordWrap(true);
    layout->addWidget(icon_label_);
    layout->addWidget(text_label_, 1);
    layout->addStretch(0);
    apply(text, tone, none_if_null(icon_name));
}

void PwbInlineStatus::set_status(const QString& text, const QString& tone,
                                 const QString& icon_name) {
    const QString effective_tone = tone.isEmpty() ? tone_ : tone;
    apply(text, effective_tone,
          icon_name.isNull() ? none_if_null(explicit_icon_)
                             : std::optional<QString>(icon_name));
}

void PwbInlineStatus::apply(const QString& text, const QString& tone,
                            const QString& icon_name) {
    apply(text, tone, none_if_null(icon_name));
}

void PwbInlineStatus::apply(const QString& text, const QString& tone,
                            const std::optional<QString>& icon_name) {
    tone_ = tone;
    text_label_->setText(text);
    text_label_->setProperty("tone", tone);
    repolish(text_label_);
    const BadgeToneIcon tone_icon = badge_tone_icon(tone);
    const QString resolved =
        icon_name.has_value() ? *icon_name : tone_icon.icon_name;
    if (!resolved.isEmpty()) {
        const QString color =
            palette_token(tone_icon.color_token.toUtf8().constData());
        const QIcon icon = workstation_icon(resolved, color);
        icon_label_->setPixmap(icon.pixmap(16, 16));
        icon_label_->setVisible(true);
    } else {
        icon_label_->setVisible(false);
    }
}

void PwbInlineStatus::clear() {
    apply("", "neutral", none_if_null(explicit_icon_));
}

}  // namespace pwb::ui_widgets
