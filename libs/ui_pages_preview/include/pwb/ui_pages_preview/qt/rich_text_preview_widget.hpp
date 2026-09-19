#pragma once

// Port of paleo_workbench/ui/pages/rich_text_preview_widget.py (UI-07).

#include <QTextBrowser>

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class RichTextPreviewWidget : public QTextBrowser {
    Q_OBJECT
public:
    explicit RichTextPreviewWidget(QWidget* parent = nullptr);

    void load_html(const QString& html) { setHtml(html); }
    void apply_settings(const PreviewSettings& settings);

protected:
    // Blocks non-file resources (network); "" and "file" pass through so
    // local embedded figures render.
    QVariant loadResource(int type, const QUrl& name) override;
};

}  // namespace pwb::ui_pages_preview
