#pragma once

// Port of paleo_workbench/ui/pages/web_document_preview_widget.py (UI-07):
// local-only QWebEngineView — the request interceptor and page block every
// scheme outside {file, data, about, blob}, and remote-url access from
// local content is disabled. Without Qt6::WebEngineWidgets the widget is a
// placeholder label (same degraded-path discipline as media/pdf).

#include <QString>
#include <QWidget>

class QLabel;
class QWebEngineView;

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class WebDocumentPreviewWidget : public QWidget {
    Q_OBJECT
public:
    explicit WebDocumentPreviewWidget(QWidget* parent = nullptr);

    // load_document(path, html): setHtml with the file's parent dir as base
    // URL when html is given; otherwise load the file URL directly.
    void load_document(const QString& path, const QString& html = QString());

    void apply_settings(const PreviewSettings& settings);

    // Null when Qt6::WebEngineWidgets is not in the build.
    QWebEngineView* engine_view() const { return engine_view_; }

private:
    QWebEngineView* engine_view_ = nullptr;
    QLabel* placeholder_ = nullptr;
};

}  // namespace pwb::ui_pages_preview
