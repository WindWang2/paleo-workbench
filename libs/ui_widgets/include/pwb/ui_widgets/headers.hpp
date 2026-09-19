#pragma once

// UI-02 — PwbSectionHeader / PwbInspectorSection / PwbPropertyEditor /
// section_header, ported from paleo_workbench/ui/components/headers.py
// (V5-U2). Reuses the global QSS vocabulary (PwbSectionHeader /
// WorkstationPanelTitle / WorkstationInspectorValue).

#include <QFrame>
#include <QLabel>
#include <QLineEdit>
#include <QToolButton>
#include <QVBoxLayout>
#include <QWidget>

namespace pwb::ui_widgets {

class PwbSectionHeader : public QLabel {
    Q_OBJECT
public:
    explicit PwbSectionHeader(const QString& text = QString(),
                              QWidget* parent = nullptr);
};

// Collapsible inspector/panel section: title row (+ optional collapse
// button) + content container.
class PwbInspectorSection : public QFrame {
    Q_OBJECT
public:
    explicit PwbInspectorSection(const QString& title = QString(),
                                 bool collapsible = false,
                                 QWidget* parent = nullptr);

    QVBoxLayout* content_layout() const { return content_layout_; }

    void set_title(const QString& title);
    bool is_collapsed() const { return collapsed_; }
    void toggle_collapsed() { set_collapsed(!collapsed_); }
    void set_collapsed(bool collapsed);

private:
    QLabel* title_ = nullptr;
    QToolButton* toggle_ = nullptr;
    QWidget* content_ = nullptr;
    QVBoxLayout* content_layout_ = nullptr;
    bool collapsed_ = false;
};

// label/value property rows (inspector semantics): the value is a
// read-only selectable QLineEdit (WorkstationInspectorValue); null/empty
// values get the `missing` property (dimmed italic em-dash).
class PwbPropertyEditor : public QWidget {
    Q_OBJECT
public:
    explicit PwbPropertyEditor(QWidget* parent = nullptr);

    PwbSectionHeader* add_header(const QString& text);
    QLineEdit* add_row(const QString& label, const QVariant& value,
                       const QString& unit = QString(),
                       const QString& placeholder = QString());
    QWidget* add_widget_row(const QString& label, QWidget* widget);
    void add_stretch();

private:
    QVBoxLayout* layout_ = nullptr;
};

// Convenience: same-look section header QLabel (migrates MapDockTitle).
PwbSectionHeader* section_header(const QString& text, QWidget* parent = nullptr);

}  // namespace pwb::ui_widgets
