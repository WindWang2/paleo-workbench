#pragma once

// Port of paleo_workbench/ui/pages/pdf_preview_widget.py (UI-07):
// QPdfView continuous-scroll view when Qt6::PdfWidgets is available;
// otherwise a whole-document fallback renders every page into a scroll
// area via QPdfDocument::render; without Qt6::Pdf at all the widget shows
// the "PDF 预览不可用" fallback text — same degraded paths as Python.
//
// The QtPdf members are forward-declared so this header is identical
// across build configurations; the .cpp compiles them in under
// PWB_UI_PAGES_PREVIEW_HAVE_PDF / _HAVE_PDFWIDGETS.

#include <QByteArray>
#include <QString>
#include <QWidget>
#include <vector>

class QBuffer;
class QHBoxLayout;
class QLabel;
class QPdfDocument;
class QPdfView;
class QPushButton;
class QScrollArea;
class QStackedWidget;
class QVBoxLayout;

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class PdfPreviewWidget : public QWidget {
    Q_OBJECT
public:
    explicit PdfPreviewWidget(QWidget* parent = nullptr);

    void apply_settings(const PreviewSettings& settings);

    // load(path, revision, pdf_bytes): reloads on identity change.
    void load(const QString& path, const QString& revision = QString(),
              const QByteArray& pdf_bytes = QByteArray());

    void next_page();
    void previous_page();

    // Python-compatible accessors (tests + host panels).
    int page() const { return page_; }
    int zoom_percent() const { return zoom_percent_; }
    const std::string& fit_mode() const { return fit_mode_; }
    bool load_failed() const { return load_failed_; }
    bool load_pending() const { return load_pending_; }
    QPdfDocument* document() const { return document_; }
    QPdfView* pdf_view() const { return pdf_view_; }

    QLabel* page_label() const { return page_label_; }
    QPushButton* prev_button() const { return prev_btn_; }
    QPushButton* next_button() const { return next_btn_; }
    QPushButton* copy_all_button() const { return copy_all_btn_; }
    QPushButton* fit_page_button() const { return fit_page_btn_; }
    QPushButton* fit_width_button() const { return fit_width_btn_; }
    QPushButton* zoom_out_button() const { return zoom_out_btn_; }
    QPushButton* zoom_in_button() const { return zoom_in_btn_; }
    QLabel* zoom_label() const { return zoom_label_; }

protected:
    bool eventFilter(QObject* obj, QEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

private:
    void sync_zoom_ui();
    void apply_fit_mode();
    void apply_custom_zoom();
    void on_fit_page_clicked();
    void on_fit_width_clicked();
    void zoom_in();
    void zoom_out();
    void on_current_zoom_changed(double zoom);
    void on_current_page_changed(int page);
    void update_page_status();
    void goto_page();
    void render_page();
    void render_fallback_pages();
    QLabel* ensure_fallback_label(int index);
    void on_fallback_scroll(int value);
    void copy_all_text();
    void show_fallback_message(const QString& text);

    // Document load pipeline (QPdfDocument may finish asynchronously:
    // statusChanged -> finish_document_load resolves Loading/Error/Ready).
    void load_document(const QString& path, const QByteArray& pdf_bytes);
    void on_document_status_changed();
    void finish_document_load();
    void release_source_buffer();

    QPdfDocument* document_ = nullptr;
    QPdfView* pdf_view_ = nullptr;
    QLabel* fallback_image_ = nullptr;
    QStackedWidget* content_stack_ = nullptr;
    QWidget* fallback_pages_ = nullptr;
    QVBoxLayout* fallback_pages_layout_ = nullptr;
    QScrollArea* fallback_scroll_ = nullptr;
    std::vector<QLabel*> fallback_page_labels_;

    QPushButton* prev_btn_ = nullptr;
    QLabel* page_label_ = nullptr;
    QPushButton* next_btn_ = nullptr;
    QPushButton* copy_all_btn_ = nullptr;
    QPushButton* fit_page_btn_ = nullptr;
    QPushButton* fit_width_btn_ = nullptr;
    QPushButton* zoom_out_btn_ = nullptr;
    QPushButton* zoom_in_btn_ = nullptr;
    QLabel* zoom_label_ = nullptr;

    int page_ = 0;
    QString path_;
    QString revision_;
    bool load_failed_ = false;
    bool load_pending_ = false;
    QBuffer* source_buffer_ = nullptr;
    // 默认以宽度为主拉伸页面（连续滚动视图下最自然的阅读方式）
    std::string fit_mode_ = "width";
    int zoom_percent_ = 100;
};

}  // namespace pwb::ui_pages_preview
