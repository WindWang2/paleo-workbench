#pragma once

// UI-02 — PwbButton / PwbToolButton / PwbSplitButton, ported from
// paleo_workbench/ui/components/buttons.py (V5-U2).
//
// Variants map to the existing global-QSS object names (PrimaryButton /
// SecondaryButton / WorkstationTertiaryButton / PwbDangerButton) — no
// per-widget stylesheet; theme switches re-polish via the global sheet.

#include <QFrame>
#include <QPushButton>
#include <QToolButton>

class QMenu;

namespace pwb::ui_widgets {

// variant -> global QSS objectName (existing vocabulary, zero duplication)
QString button_variant_object_name(const QString& variant);

class PwbButton : public QPushButton {
    Q_OBJECT
public:
    explicit PwbButton(const QString& text = QString(),
                       const QString& variant = QStringLiteral("secondary"),
                       const QString& icon_name = QString(),
                       QWidget* parent = nullptr);

    void set_variant(const QString& variant);
    QString variant() const { return variant_; }

private:
    QString variant_;
};

class PwbToolButton : public QToolButton {
    Q_OBJECT
public:
    explicit PwbToolButton(const QString& icon_name = QString(),
                           const QString& text = QString(),
                           bool checkable = false, bool chrome = false,
                           const QString& icon_color = QString(),
                           QWidget* parent = nullptr);
};

// Primary action + drop-down menu split button. The left segment is a
// SecondaryButton-semantics push button (`clicked`); the right segment is
// a menu-only arrow (InstantPopup — never emits clicked).
class PwbSplitButton : public QFrame {
    Q_OBJECT
public:
    explicit PwbSplitButton(const QString& text = QString(),
                            const QString& icon_name = QString(),
                            QMenu* menu = nullptr, QWidget* parent = nullptr);

    void set_menu(QMenu* menu);
    QMenu* menu() const;
    void set_enabled_all(bool enabled);

    // Main-action slot (equivalent to connecting `clicked`).
    template <typename Slot>
    void connect_main(Slot slot) {
        QObject::connect(this, &PwbSplitButton::clicked, slot);
    }

signals:
    void clicked();

private:
    PwbButton* main_ = nullptr;
    QToolButton* arrow_ = nullptr;
};

}  // namespace pwb::ui_widgets
