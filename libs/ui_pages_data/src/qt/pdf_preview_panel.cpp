// UI-06 — PdfPreviewPanel shell (see qt/pdf_preview_panel.hpp).
#include <pwb/ui_pages_data/qt/pdf_preview_panel.hpp>

#include <QEvent>
#include <QHBoxLayout>
#include <QLabel>
#include <QPixmap>
#include <QPushButton>
#include <QScrollArea>
#include <QVBoxLayout>
#include <QWheelEvent>

namespace pwb::ui_pages_data::qt {

PdfPreviewPanel::PdfPreviewPanel(std::unique_ptr<PdfDocumentApi> document,
                                 QWidget* parent)
    : QWidget(parent), document_(std::move(document)) {
    setObjectName(QStringLiteral("PdfPreviewPanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(8);

    image_label_ = new QLabel(this);
    image_label_->setObjectName(QStringLiteral("DataPreviewPdf"));
    image_label_->setAlignment(Qt::AlignmentFlag::AlignCenter);

    scroll_area_ = new QScrollArea(this);
    scroll_area_->setObjectName(
        QStringLiteral("DataPreviewPdfScrollArea"));
    scroll_area_->setWidgetResizable(false);
    scroll_area_->setWidget(image_label_);
    layout->addWidget(scroll_area_, 1);

    auto* controls = new QHBoxLayout();
    controls->setContentsMargins(0, 0, 0, 0);
    controls->setSpacing(8);
    prev_btn_ = new QPushButton(QStringLiteral("上一页"), this);
    prev_btn_->setObjectName(QStringLiteral("DataPreviewPdfPrevious"));
    connect(prev_btn_, &QPushButton::clicked, this,
            &PdfPreviewPanel::previous_page);
    controls->addWidget(prev_btn_);

    auto* zoom_out = new QPushButton(QStringLiteral("−"), this);
    zoom_out->setObjectName(QStringLiteral("SecondaryButton"));
    zoom_out->setToolTip(QStringLiteral("缩小"));
    connect(zoom_out, &QPushButton::clicked, this,
            &PdfPreviewPanel::zoom_out);
    controls->addWidget(zoom_out);

    zoom_label_ = new QLabel(QStringLiteral("100%"), this);
    zoom_label_->setObjectName(QStringLiteral("DataPreviewPdfZoomLabel"));
    zoom_label_->setAlignment(Qt::AlignmentFlag::AlignCenter);
    zoom_label_->setMinimumWidth(48);
    controls->addWidget(zoom_label_);

    auto* zoom_in = new QPushButton(QStringLiteral("+"), this);
    zoom_in->setObjectName(QStringLiteral("SecondaryButton"));
    zoom_in->setToolTip(QStringLiteral("放大"));
    connect(zoom_in, &QPushButton::clicked, this,
            &PdfPreviewPanel::zoom_in);
    controls->addWidget(zoom_in);

    page_label_ = new QLabel(this);
    page_label_->setObjectName(QStringLiteral("DataPreviewPdfPageLabel"));
    page_label_->setAlignment(Qt::AlignmentFlag::AlignCenter);
    controls->addWidget(page_label_, 1);

    next_btn_ = new QPushButton(QStringLiteral("下一页"), this);
    next_btn_->setObjectName(QStringLiteral("DataPreviewPdfNext"));
    connect(next_btn_, &QPushButton::clicked, this,
            &PdfPreviewPanel::next_page);
    controls->addWidget(next_btn_);
    layout->addLayout(controls);

    scroll_area_->viewport()->installEventFilter(this);
    update_zoom_label();
    render_page();
}

void PdfPreviewPanel::zoom_in() {
    if (zoom_.zoom_in()) render_page();
    update_zoom_label();
}

void PdfPreviewPanel::zoom_out() {
    if (zoom_.zoom_out()) render_page();
    update_zoom_label();
}

void PdfPreviewPanel::next_page() {
    if (document_ == nullptr) return;
    const int count = document_->page_count();
    if (zoom_.next_page(count)) render_page();
}

void PdfPreviewPanel::previous_page() {
    if (zoom_.previous_page()) render_page();
}

void PdfPreviewPanel::update_zoom_label() {
    zoom_label_->setText(QString::fromStdString(zoom_.zoom_label()));
}

bool PdfPreviewPanel::eventFilter(QObject* obj, QEvent* event) {
    if (obj == scroll_area_->viewport() &&
        event->type() == QEvent::Type::Wheel) {
        auto* wheel = static_cast<QWheelEvent*>(event);
        if (wheel->modifiers() & Qt::KeyboardModifier::ControlModifier) {
            zoom_.wheel(wheel->angleDelta().y());
            update_zoom_label();
            render_page();
            event->accept();
            return true;
        }
    }
    return QWidget::eventFilter(obj, event);
}

void PdfPreviewPanel::wheelEvent(QWheelEvent* event) {
    if (event->modifiers() & Qt::KeyboardModifier::ControlModifier) {
        zoom_.wheel(event->angleDelta().y());
        update_zoom_label();
        render_page();
        event->accept();
        return;
    }
    QWidget::wheelEvent(event);
}

void PdfPreviewPanel::render_page() {
    if (document_ == nullptr) {
        page_label_->setText(QString::fromStdString(zoom_.page_label(0)));
        prev_btn_->setEnabled(false);
        next_btn_->setEnabled(false);
        update_zoom_label();
        return;
    }
    const int page_count = document_->page_count();
    const QSize render_size(zoom_.render_width(), zoom_.render_height());
    const QImage image = document_->render(zoom_.page_index(), render_size);
    if (!image.isNull()) {
        const QPixmap pix = QPixmap::fromImage(image);
        image_label_->setPixmap(pix);
        // QLabel size must track pixmap for scrollbars to appear
        // (widgetResizable=False).
        image_label_->resize(pix.size());
    }
    page_label_->setText(
        QString::fromStdString(zoom_.page_label(page_count)));
    prev_btn_->setEnabled(zoom_.page_index() > 0);
    next_btn_->setEnabled(page_count > 0 &&
                          zoom_.page_index() < page_count - 1);
    update_zoom_label();
}

}  // namespace pwb::ui_pages_data::qt
