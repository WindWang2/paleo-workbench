#pragma once

// UI-02 — PwbBadge + PwbInlineStatus, ported from
// paleo_workbench/ui/components/badges.py (V5-U2).
//
// Semantic tones map to the global QSS vocabulary (PwbBadge /
// PwbInlineStatusText selectors); tone-driven icon + text color comes
// from the theme palette at paint/set time — never a constructor snapshot.

#include <QLabel>
#include <QWidget>

#include <optional>

namespace pwb::ui_widgets {

//: tone → (default icon, icon tint token name)
struct BadgeToneIcon {
    QString icon_name;
    QString color_token;
};

// "neutral", "primary", "success", "warning", "error"
// (process is an InlineStatus-only tone).
extern const char* const kBadgeTones[];
BadgeToneIcon badge_tone_icon(const QString& tone);

class PwbBadge : public QLabel {
    Q_OBJECT
public:
    explicit PwbBadge(const QString& text = QString(),
                      const QString& tone = QStringLiteral("neutral"),
                      QWidget* parent = nullptr);

    void set_tone(const QString& tone);
    QString tone() const { return tone_; }

private:
    QString tone_;
};

// "icon + one-line" inline status (degraded/loading/error semantics, D6).
// tone ∈ {neutral, primary, success, warning, process, error}.
class PwbInlineStatus : public QWidget {
    Q_OBJECT
public:
    explicit PwbInlineStatus(const QString& text = QString(),
                             const QString& tone = QStringLiteral("neutral"),
                             const QString& icon_name = QString(),
                             QWidget* parent = nullptr);

    void set_status(const QString& text, const QString& tone = QString(),
                    const QString& icon_name = QString());
    void clear();

    QString tone() const { return tone_; }

private:
    void apply(const QString& text, const QString& tone,
               const QString& icon_name);
    void apply(const QString& text, const QString& tone,
               const std::optional<QString>& icon_name);

    QLabel* icon_label_ = nullptr;
    QLabel* text_label_ = nullptr;
    QString tone_;
    QString explicit_icon_;
};

}  // namespace pwb::ui_widgets
