// UI-06 — data_detail_panel.py :: PdfPreviewPanel Qt shell.
//
// The document seam keeps Qt6::Pdf optional: the host injects a
// PdfDocumentApi factory (wrapping QPdfDocument when the module is
// linked). Zoom/page math lives in PdfZoomModel (Qt-free, oracle-verified).
#pragma once

#include <QImage>
#include <QSize>
#include <QWidget>

#include <functional>
#include <memory>
#include <string>

#include <pwb/ui_pages_data/pdf_zoom.hpp>

class QLabel;
class QPushButton;
class QScrollArea;

namespace pwb::ui_pages_data::qt {

// QPdfDocument seam — page_count + render only.
class PdfDocumentApi {
public:
    virtual ~PdfDocumentApi() = default;
    virtual int page_count() = 0;
    virtual QImage render(int page, const QSize& size) = 0;
};

// Returns nullptr when the file cannot be loaded (QPdfDocument.load
// error / pageCount <= 0 in Python → _add_pdf_preview returns False).
using PdfDocumentFactory =
    std::function<std::unique_ptr<PdfDocumentApi>(const QString& path)>;

class PdfPreviewPanel : public QWidget {
    Q_OBJECT
public:
    explicit PdfPreviewPanel(std::unique_ptr<PdfDocumentApi> document,
                             QWidget* parent = nullptr);

    void zoom_in();
    void zoom_out();
    void next_page();
    void previous_page();
    double zoom_factor() const { return zoom_.factor(); }
    int page_index() const { return zoom_.page_index(); }

    QLabel* image_label() { return image_label_; }
    QScrollArea* scroll_area() { return scroll_area_; }
    QPushButton* prev_button() { return prev_btn_; }
    QPushButton* next_button() { return next_btn_; }
    QLabel* zoom_label() { return zoom_label_; }
    QLabel* page_label() { return page_label_; }

protected:
    bool eventFilter(QObject* obj, QEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;

private:
    void render_page();
    void update_zoom_label();

    PdfZoomModel zoom_;
    std::unique_ptr<PdfDocumentApi> document_;
    QLabel* image_label_;
    QScrollArea* scroll_area_;
    QPushButton* prev_btn_;
    QPushButton* next_btn_;
    QLabel* zoom_label_;
    QLabel* page_label_;
};

}  // namespace pwb::ui_pages_data::qt
