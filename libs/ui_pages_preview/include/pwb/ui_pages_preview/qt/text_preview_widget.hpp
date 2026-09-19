#pragma once

// Port of paleo_workbench/ui/pages/text_preview_widget.py (UI-07).

#include <QTextEdit>

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class TextPreviewWidget : public QTextEdit {
    Q_OBJECT
public:
    explicit TextPreviewWidget(QWidget* parent = nullptr);

    void load_text(const QString& text) { setPlainText(text); }
    void apply_settings(const PreviewSettings& settings);
};

}  // namespace pwb::ui_pages_preview
