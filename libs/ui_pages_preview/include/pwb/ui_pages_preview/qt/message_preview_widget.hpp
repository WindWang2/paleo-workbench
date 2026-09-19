#pragma once

// Port of paleo_workbench/ui/pages/message_preview_widget.py (UI-07).

#include <QLabel>

namespace pwb::ui_pages_preview {

class MessagePreviewWidget : public QLabel {
    Q_OBJECT
public:
    explicit MessagePreviewWidget(QWidget* parent = nullptr);

    void set_message(const QString& text) { setText(text); }
};

}  // namespace pwb::ui_pages_preview
