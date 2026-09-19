#include "pwb/ui_widgets/headers.hpp"

#include "pwb/ui_widgets/buttons.hpp"
#include "pwb/ui_widgets/icon_factory.hpp"

#include <QHBoxLayout>

#include <nlohmann/json.hpp>

namespace pwb::ui_widgets {

PwbSectionHeader::PwbSectionHeader(const QString& text, QWidget* parent)
    : QLabel(text, parent) {
    setObjectName(QStringLiteral("PwbSectionHeader"));
}

PwbInspectorSection::PwbInspectorSection(const QString& title,
                                         bool collapsible, QWidget* parent)
    : QFrame(parent) {
    setObjectName(QStringLiteral("PwbInspectorSection"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(4);

    auto* header = new QWidget(this);
    auto* row = new QHBoxLayout(header);
    row->setContentsMargins(0, 0, 0, 0);
    row->setSpacing(2);
    title_ = new QLabel(title, header);
    title_->setObjectName(QStringLiteral("WorkstationPanelTitle"));
    row->addWidget(title_);
    row->addStretch(1);
    if (collapsible) {
        toggle_ = new PwbToolButton(QStringLiteral("chevron-down.svg"),
                                    QString(), false, false, QString(), header);
        toggle_->setFixedSize(22, 22);
        connect(toggle_, &QToolButton::clicked, this,
                &PwbInspectorSection::toggle_collapsed);
        row->addWidget(toggle_);
    }
    outer->addWidget(header);

    content_ = new QWidget(this);
    content_layout_ = new QVBoxLayout(content_);
    content_layout_->setContentsMargins(0, 0, 0, 0);
    content_layout_->setSpacing(4);
    outer->addWidget(content_);
}

void PwbInspectorSection::set_title(const QString& title) {
    title_->setText(title);
}

void PwbInspectorSection::set_collapsed(bool collapsed) {
    collapsed_ = collapsed;
    content_->setVisible(!collapsed);
    if (toggle_ != nullptr) {
        toggle_->setIcon(workstation_icon(
            collapsed ? QStringLiteral("chevron-right.svg")
                      : QStringLiteral("chevron-down.svg")));
    }
}

PwbPropertyEditor::PwbPropertyEditor(QWidget* parent) : QWidget(parent) {
    layout_ = new QVBoxLayout(this);
    layout_->setContentsMargins(0, 0, 0, 0);
    layout_->setSpacing(3);
}

PwbSectionHeader* PwbPropertyEditor::add_header(const QString& text) {
    auto* header = new PwbSectionHeader(text, this);
    layout_->addWidget(header);
    return header;
}

QLineEdit* PwbPropertyEditor::add_row(const QString& label,
                                    const QVariant& value,
                                    const QString& unit,
                                    const QString& placeholder) {
    auto* row = new QWidget(this);
    auto* form = new QHBoxLayout(row);
    form->setContentsMargins(0, 0, 0, 0);
    form->setSpacing(6);
    auto* label_w = new QLabel(label, row);
    label_w->setObjectName(QStringLiteral("WorkFieldLabel"));
    auto* editor = new QLineEdit(row);
    editor->setObjectName(QStringLiteral("WorkstationInspectorValue"));
    editor->setReadOnly(true);  // 只读态原生支持选取
    // value None / blank-string -> missing (dimmed italic em-dash).
    const bool missing = !value.isValid() || value.isNull() ||
                         (value.typeId() == QMetaType::QString &&
                          value.toString().trimmed().isEmpty());
    if (missing) {
        editor->setProperty("missing", true);
        editor->setText(placeholder.isEmpty() ? QStringLiteral("—")
                                              : placeholder);
    } else {
        // Python str() parity: floats render repr-shortest ("3.0", not "3").
        QString text;
        if (value.typeId() == QMetaType::Double ||
            value.typeId() == QMetaType::Float) {
            text = QString::fromStdString(nlohmann::json(value.toDouble()).dump());
        } else {
            text = value.toString();
        }
        editor->setProperty("missing", false);
        editor->setText(unit.isEmpty() ? text
                                       : QStringLiteral("%1 %2").arg(text, unit).trimmed());
    }
    form->addWidget(label_w, 0);
    form->addWidget(editor, 1);
    layout_->addWidget(row);
    return editor;
}

QWidget* PwbPropertyEditor::add_widget_row(const QString& label,
                                         QWidget* widget) {
    auto* row = new QWidget(this);
    auto* form = new QHBoxLayout(row);
    form->setContentsMargins(0, 0, 0, 0);
    form->setSpacing(6);
    auto* label_w = new QLabel(label, row);
    label_w->setObjectName(QStringLiteral("WorkFieldLabel"));
    form->addWidget(label_w, 0);
    form->addWidget(widget, 1);
    layout_->addWidget(row);
    return row;
}

void PwbPropertyEditor::add_stretch() { layout_->addStretch(1); }

PwbSectionHeader* section_header(const QString& text, QWidget* parent) {
    return new PwbSectionHeader(text, parent);
}

}  // namespace pwb::ui_widgets
