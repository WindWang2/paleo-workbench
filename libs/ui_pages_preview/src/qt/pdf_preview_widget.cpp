#include <pwb/ui_pages_preview/qt/pdf_preview_widget.hpp>

#include <QApplication>
#include <QBuffer>
#include <QClipboard>
#include <QHBoxLayout>
#include <QLabel>
#include <QPointF>
#include <QPushButton>
#include <QScrollArea>
#include <QScrollBar>
#include <QStackedWidget>
#include <QStringList>
#include <QTimer>
#include <QVBoxLayout>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>

#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
#include <QPdfDocument>
#include <QPdfSelection>
#endif
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
#include <QPdfPageNavigator>
#include <QPdfView>
#endif

#include <pwb/ui_pages_preview/pdf_zoom.hpp>
#include <pwb/ui_pages_preview/preview_settings.hpp>

#include "../qt/style_util.hpp"

namespace pwb::ui_pages_preview {

PdfPreviewWidget::PdfPreviewWidget(QWidget* parent)
    : QWidget(parent) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
    document_ = new QPdfDocument(this);
#endif
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
    if (document_ != nullptr) {
        pdf_view_ = new QPdfView(this);
    }
#endif
    fallback_image_ = new QLabel();
    fallback_image_->setAlignment(Qt::AlignCenter);
    content_stack_ = new QStackedWidget(this);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
    if (pdf_view_ != nullptr) {
        pdf_view_->setDocument(document_);
        content_stack_->addWidget(pdf_view_);
    }
#endif
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
    connect(document_, &QPdfDocument::statusChanged, this,
            [this](QPdfDocument::Status) { on_document_status_changed(); });
#endif
    content_stack_->addWidget(fallback_image_);
    // fallback 连续页面：所有页按宽度渲染进滚动区
    fallback_pages_ = new QWidget();
    fallback_pages_layout_ = new QVBoxLayout(fallback_pages_);
    fallback_pages_layout_->setContentsMargins(0, 0, 0, 0);
    fallback_pages_layout_->setSpacing(qt_internal::SPACE_1);
    fallback_scroll_ = new QScrollArea(this);
    fallback_scroll_->setWidgetResizable(true);
    fallback_scroll_->setWidget(fallback_pages_);
    if (QScrollBar* scrollbar = fallback_scroll_->verticalScrollBar()) {
        connect(scrollbar, &QScrollBar::valueChanged, this,
                [this](int value) { on_fallback_scroll(value); });
    }
    content_stack_->addWidget(fallback_scroll_);
    content_stack_->setCurrentWidget(
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
        pdf_view_ != nullptr ? static_cast<QWidget*>(pdf_view_)
                             :
#endif
                             static_cast<QWidget*>(fallback_image_));
    layout->addWidget(content_stack_, 1);

    auto* controls = new QHBoxLayout();
    controls->setSpacing(qt_internal::SPACE_2);
    prev_btn_ = new QPushButton(QStringLiteral("上一页"));
    prev_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(prev_btn_, &QPushButton::clicked, this,
            &PdfPreviewWidget::previous_page);
    page_label_ = new QLabel(QStringLiteral("0 / 0"));
    page_label_->setAlignment(Qt::AlignCenter);
    next_btn_ = new QPushButton(QStringLiteral("下一页"));
    next_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(next_btn_, &QPushButton::clicked, this,
            &PdfPreviewWidget::next_page);
    copy_all_btn_ = new QPushButton(QStringLiteral("复制全部文本"));
    copy_all_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(copy_all_btn_, &QPushButton::clicked, this,
            [this] { copy_all_text(); });

    // 缩放控件
    fit_page_btn_ = new QPushButton(QStringLiteral("适应窗口"));
    fit_page_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    fit_page_btn_->setCheckable(true);
    fit_width_btn_ = new QPushButton(QStringLiteral("适应宽度"));
    fit_width_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    fit_width_btn_->setCheckable(true);
    zoom_out_btn_ = new QPushButton(QStringLiteral("−"));
    zoom_out_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    zoom_in_btn_ = new QPushButton(QStringLiteral("+"));
    zoom_in_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    zoom_label_ = new QLabel(QStringLiteral("%1%").arg(zoom_percent_));
    zoom_label_->setAlignment(Qt::AlignCenter);
    zoom_label_->setMinimumWidth(48);

    connect(fit_page_btn_, &QPushButton::clicked, this,
            [this] { on_fit_page_clicked(); });
    connect(fit_width_btn_, &QPushButton::clicked, this,
            [this] { on_fit_width_clicked(); });
    connect(zoom_out_btn_, &QPushButton::clicked, this,
            [this] { zoom_out(); });
    connect(zoom_in_btn_, &QPushButton::clicked, this,
            [this] { zoom_in(); });

    controls->addWidget(prev_btn_);
    controls->addWidget(page_label_, 1);
    controls->addWidget(next_btn_);
    controls->addWidget(fit_page_btn_);
    controls->addWidget(fit_width_btn_);
    controls->addWidget(zoom_out_btn_);
    controls->addWidget(zoom_label_);
    controls->addWidget(zoom_in_btn_);
    controls->addWidget(copy_all_btn_);
    layout->addLayout(controls);

    if (pdf_view_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
        pdf_view_->installEventFilter(this);
        // 同步缩放百分比显示 + 连续滚动时同步当前页码显示
        QPdfPageNavigator* navigator = pdf_view_->pageNavigator();
        connect(navigator, &QPdfPageNavigator::currentZoomChanged, this,
                [this](qreal zoom) { on_current_zoom_changed(zoom); });
        connect(navigator, &QPdfPageNavigator::currentPageChanged, this,
                [this](int page) { on_current_page_changed(page); });
#endif
    }
    sync_zoom_ui();

    if (document_ == nullptr) {
        show_fallback_message(QStringLiteral("PDF 预览不可用"));
        page_label_->setText(QStringLiteral("0 / 0"));
        prev_btn_->setEnabled(false);
        next_btn_->setEnabled(false);
        copy_all_btn_->setEnabled(false);
        copy_all_btn_->setVisible(false);
    }
    // Python parity: with a document present, __init__ never calls
    // _update_page_status — the label keeps its "0 / 0" ctor text and the
    // nav buttons keep their default-enabled state until the first load.
}

// -- 缩放核心 ---------------------------------------------------------------

void PdfPreviewWidget::sync_zoom_ui() {
    if (zoom_label_ != nullptr) {
        zoom_label_->setText(QStringLiteral("%1%").arg(zoom_percent_));
    }
    if (fit_page_btn_ != nullptr && fit_width_btn_ != nullptr) {
        fit_page_btn_->blockSignals(true);
        fit_width_btn_->blockSignals(true);
        fit_page_btn_->setChecked(fit_mode_ == PDF_FIT_PAGE);
        fit_width_btn_->setChecked(fit_mode_ == PDF_FIT_WIDTH);
        fit_page_btn_->blockSignals(false);
        fit_width_btn_->blockSignals(false);
    }
}

void PdfPreviewWidget::apply_fit_mode() {
    sync_zoom_ui();
    if (pdf_view_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
        if (fit_mode_ == PDF_FIT_PAGE) {
            pdf_view_->setZoomMode(QPdfView::ZoomMode::FitInView);
        } else if (fit_mode_ == PDF_FIT_WIDTH) {
            pdf_view_->setZoomMode(QPdfView::ZoomMode::FitToWidth);
        }
#endif
    } else {
        // fallback 路径：重新渲染以反映 fit 切换（fit 下按基础尺寸渲染）
        if (!path_.isEmpty() && document_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
            if (document_->pageCount() > 0) {
                render_page();
            }
#endif
        }
    }
}

void PdfPreviewWidget::apply_custom_zoom() {
    sync_zoom_ui();
    if (pdf_view_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
        pdf_view_->setZoomMode(QPdfView::ZoomMode::Custom);
        pdf_view_->setZoomFactor(zoom_percent_ / 100.0);
#endif
    } else {
        if (!path_.isEmpty() && document_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
            if (document_->pageCount() > 0) {
                render_page();
            }
#endif
        }
    }
}

void PdfPreviewWidget::on_fit_page_clicked() {
    // 手写互斥：点击即进入 page 模式
    fit_mode_ = PDF_FIT_PAGE;
    apply_fit_mode();
}

void PdfPreviewWidget::on_fit_width_clicked() {
    fit_mode_ = PDF_FIT_WIDTH;
    apply_fit_mode();
}

void PdfPreviewWidget::zoom_in() {
    const PdfZoomResult result = pdf_zoom_in(zoom_percent_);
    if (!result.changed) {
        return;
    }
    zoom_percent_ = result.percent;
    fit_mode_ = PDF_FIT_CUSTOM;
    apply_custom_zoom();
}

void PdfPreviewWidget::zoom_out() {
    const PdfZoomResult result = pdf_zoom_out(zoom_percent_);
    if (!result.changed) {
        // 已在边界，避免死循环
        return;
    }
    zoom_percent_ = result.percent;
    fit_mode_ = PDF_FIT_CUSTOM;
    apply_custom_zoom();
}

void PdfPreviewWidget::on_current_zoom_changed(double zoom) {
    // Python int(round(zoom*100)) — banker's rounding via nearbyint.
    const int percent = pdf_clamp_zoom(
        static_cast<int>(std::nearbyint(zoom * 100.0)));
    // 仅更新标签显示，保持 fit_mode 不变（由交互逻辑驱动 fit_mode）
    zoom_percent_ = percent;
    zoom_label_->setText(QStringLiteral("%1%").arg(zoom_percent_));
}

void PdfPreviewWidget::on_current_page_changed(int page) {
    // 连续滚动模式下，QPdfView 滚动时同步页码显示
    if (page < 0 || page == page_) {
        return;
    }
    page_ = page;
    update_page_status();
}

void PdfPreviewWidget::update_page_status() {
    int page_count = 0;
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
    if (document_ != nullptr) {
        page_count = document_->pageCount();
    }
#endif
    page_label_->setText(QString::fromStdString(
        pdf_page_status(page_, page_count)));
    prev_btn_->setEnabled(pdf_prev_enabled(page_));
    next_btn_->setEnabled(pdf_next_enabled(page_, page_count));
}

bool PdfPreviewWidget::eventFilter(QObject* obj, QEvent* event) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
    if (obj == pdf_view_ && event->type() == QEvent::Wheel) {
        auto* wheel = static_cast<QWheelEvent*>(event);
        if (wheel->modifiers() & Qt::ControlModifier) {
            const int delta = wheel->angleDelta().y();
            // 滚轮向上放大，向下缩小
            if (delta > 0) {
                zoom_in();
            } else if (delta < 0) {
                zoom_out();
            }
            return true;
        }
    }
#endif
    return QWidget::eventFilter(obj, event);
}

void PdfPreviewWidget::apply_settings(const PreviewSettings& settings) {
    fit_mode_ = settings.pdf_fit_mode;
    zoom_percent_ = pdf_clamp_zoom(settings.pdf_zoom_percent);
    sync_zoom_ui();
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
    if (pdf_view_ != nullptr) {
        if (fit_mode_ == PDF_FIT_PAGE) {
            pdf_view_->setZoomMode(QPdfView::ZoomMode::FitInView);
        } else if (fit_mode_ == PDF_FIT_WIDTH) {
            pdf_view_->setZoomMode(QPdfView::ZoomMode::FitToWidth);
        } else {
            pdf_view_->setZoomMode(QPdfView::ZoomMode::Custom);
            pdf_view_->setZoomFactor(zoom_percent_ / 100.0);
        }
        return;
    }
#endif
    // fallback 仍需重绘以应用缩放
    if (pdf_view_ == nullptr && document_ != nullptr && !path_.isEmpty()) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
        if (document_->pageCount() > 0) {
            render_page();
        }
#endif
    }
}

void PdfPreviewWidget::load(const QString& path, const QString& revision,
                            const QByteArray& pdf_bytes) {
    if (document_ == nullptr) {
        show_fallback_message(QStringLiteral("PDF 预览不可用"));
        page_label_->setText(QStringLiteral("0 / 0"));
        prev_btn_->setEnabled(false);
        next_btn_->setEnabled(false);
        return;
    }
    if (path != path_ || revision != revision_) {
        path_ = path;
        revision_ = revision;
        page_ = 0;
        load_failed_ = false;
        load_pending_ = true;
        load_document(path, pdf_bytes);
        finish_document_load();
        return;
    }
    if (load_pending_) {
        return;
    }
    if (load_failed_) {
        show_fallback_message(QStringLiteral("PDF 预览加载失败"));
        page_label_->setText(QStringLiteral("0 / 0"));
        prev_btn_->setEnabled(false);
        next_btn_->setEnabled(false);
        return;
    }
    render_page();
}

void PdfPreviewWidget::load_document(const QString& path,
                                     const QByteArray& pdf_bytes) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
    release_source_buffer();
    if (!pdf_bytes.isEmpty()) {
        auto* buffer = new QBuffer(this);
        buffer->setData(pdf_bytes);
        if (!buffer->open(QIODevice::ReadOnly)) {
            buffer->deleteLater();
            document_->load(path);
            return;
        }
        source_buffer_ = buffer;
        document_->load(buffer);
        return;
    }
    document_->load(path);
#else
    Q_UNUSED(path);
    Q_UNUSED(pdf_bytes);
#endif
}

void PdfPreviewWidget::on_document_status_changed() {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
    const QPdfDocument::Status status = document_->status();
    if (status == QPdfDocument::Status::Ready ||
        status == QPdfDocument::Status::Error) {
        finish_document_load();
    }
#endif
}

void PdfPreviewWidget::finish_document_load() {
    // Resolve both QPdfDocument load overloads from document state.
    if (document_ == nullptr) {
        return;
    }
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
    if (document_->status() == QPdfDocument::Status::Loading) {
        load_pending_ = true;
        show_fallback_message(QStringLiteral("PDF 预览加载中…"));
        page_label_->setText(QStringLiteral("0 / 0"));
        prev_btn_->setEnabled(false);
        next_btn_->setEnabled(false);
        return;
    }
    const bool failed =
        document_->status() == QPdfDocument::Status::Error ||
        document_->error() != QPdfDocument::Error::None ||
        document_->pageCount() <= 0;
    load_pending_ = false;
    load_failed_ = failed;
    if (failed) {
        show_fallback_message(QStringLiteral("PDF 预览加载失败"));
        page_label_->setText(QStringLiteral("0 / 0"));
        prev_btn_->setEnabled(false);
        next_btn_->setEnabled(false);
        return;
    }
#endif
    render_page();
}

void PdfPreviewWidget::release_source_buffer() {
    if (source_buffer_ != nullptr) {
        source_buffer_->close();
        source_buffer_->deleteLater();
        source_buffer_ = nullptr;
    }
}

void PdfPreviewWidget::next_page() {
    if (document_ == nullptr || load_failed_) {
        return;
    }
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
    if (page_ < document_->pageCount() - 1) {
        ++page_;
        goto_page();
    }
#endif
}

void PdfPreviewWidget::previous_page() {
    if (document_ == nullptr || load_failed_) {
        return;
    }
    if (page_ > 0) {
        --page_;
        goto_page();
    }
}

void PdfPreviewWidget::goto_page() {
    // 连续模式下翻页 = 滚动定位到目标页，不重新渲染
    if (pdf_view_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
        QPdfPageNavigator* navigator = pdf_view_->pageNavigator();
        navigator->jump(page_, QPointF(), navigator->currentZoom());
#endif
    } else if (page_ >= 0 &&
               page_ < static_cast<int>(fallback_page_labels_.size())) {
        QLabel* label = fallback_page_labels_[page_];
        if (QScrollBar* scrollbar = fallback_scroll_->verticalScrollBar()) {
            scrollbar->setValue(label->y());
        }
    }
    update_page_status();
}

void PdfPreviewWidget::render_page() {
    if (document_ == nullptr) {
        show_fallback_message(QStringLiteral("PDF 预览不可用"));
        page_label_->setText(QStringLiteral("0 / 0"));
        prev_btn_->setEnabled(false);
        next_btn_->setEnabled(false);
        return;
    }
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
    const int page_count = document_->pageCount();
    if (page_count <= 0) {
        load_failed_ = true;
        show_fallback_message(QStringLiteral("PDF 预览加载失败"));
        page_label_->setText(QStringLiteral("0 / 0"));
        prev_btn_->setEnabled(false);
        next_btn_->setEnabled(false);
        return;
    }
    if (pdf_view_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS)
        content_stack_->setCurrentWidget(pdf_view_);
        // 连续页面滚动优先
        pdf_view_->setPageMode(QPdfView::PageMode::MultiPage);
        QPdfPageNavigator* navigator = pdf_view_->pageNavigator();
        navigator->jump(page_, QPointF(), navigator->currentZoom());
#endif
    } else {
        render_fallback_pages();
    }
    update_page_status();
#endif
}

void PdfPreviewWidget::render_fallback_pages() {
    // 无 QPdfView 时的降级路径：所有页按宽度连续渲染进滚动区
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
    const int page_count = document_->pageCount();
    const double factor = zoom_percent_ / 100.0;
    QWidget* viewport = fallback_scroll_->viewport();
    const int base_w = std::max(
        {viewport != nullptr ? viewport->width() : 0, width(), 420});
    const int width_px = std::max(1, static_cast<int>(base_w * factor));
    bool first_failed = false;
    for (int i = 0; i < page_count; ++i) {
        int height_px = 0;
        const QSizeF ps = document_->pagePointSize(i);
        if (ps.width() > 0) {
            height_px = static_cast<int>(width_px * ps.height() / ps.width());
        }
        if (height_px <= 0) {
            height_px = static_cast<int>(width_px * 1.414);  // 默认 A4 纵向
        }
        const QImage image =
            document_->render(i, QSize(width_px, height_px));
        if (i == 0 && image.isNull()) {
            first_failed = true;
            break;
        }
        QLabel* label = ensure_fallback_label(i);
        if (image.isNull()) {
            label->setText(QStringLiteral("第 %1 页渲染失败").arg(i + 1));
        } else {
            label->setPixmap(QPixmap::fromImage(image));
        }
    }
    if (first_failed) {
        show_fallback_message(QStringLiteral("PDF 页面渲染失败"));
        return;
    }
    // 尾页裁掉多余的 label（换到页数更少的文档时）
    while (fallback_page_labels_.size() > static_cast<size_t>(page_count)) {
        QLabel* label = fallback_page_labels_.back();
        fallback_page_labels_.pop_back();
        fallback_pages_layout_->removeWidget(label);
        label->deleteLater();
    }
    content_stack_->setCurrentWidget(fallback_scroll_);
#endif
}

QLabel* PdfPreviewWidget::ensure_fallback_label(int index) {
    while (fallback_page_labels_.size() <= static_cast<size_t>(index)) {
        auto* label = new QLabel();
        label->setAlignment(Qt::AlignCenter);
        label->setStyleSheet(QStringLiteral("background: %1;")
                                 .arg(qt_internal::token("BG_HEADER")));
        fallback_pages_layout_->addWidget(label);
        fallback_page_labels_.push_back(label);
    }
    return fallback_page_labels_[index];
}

void PdfPreviewWidget::on_fallback_scroll(int value) {
    // fallback 连续滚动时按可视区中点更新当前页码
    if (fallback_page_labels_.empty()) {
        return;
    }
    QWidget* viewport = fallback_scroll_->viewport();
    const int midpoint =
        value + (viewport != nullptr ? viewport->height() / 2 : 0);
    int page = 0;
    for (size_t idx = 0; idx < fallback_page_labels_.size(); ++idx) {
        if (midpoint >= fallback_page_labels_[idx]->y()) {
            page = static_cast<int>(idx);
        }
    }
    if (page != page_) {
        page_ = page;
        update_page_status();
    }
}

void PdfPreviewWidget::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    if (!path_.isEmpty() && pdf_view_ == nullptr && document_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
        if (document_->pageCount() > 0) {
            render_page();
        }
#endif
    }
}

void PdfPreviewWidget::copy_all_text() {
    if (document_ == nullptr) {
        return;
    }
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_PDF)
    const int page_count = document_->pageCount();
    if (page_count <= 0) {
        return;
    }
    QStringList texts;
    texts.reserve(page_count);
    for (int i = 0; i < page_count; ++i) {
        texts.append(document_->getAllText(i).text());
    }
    QString full = texts.join(QLatin1Char('\n'));
    bool truncated = false;
    if (full.size() > PDF_COPY_ALL_MAX_CHARS) {
        full = full.left(PDF_COPY_ALL_MAX_CHARS);
        truncated = true;
    }
    if (QClipboard* clipboard = QApplication::clipboard()) {
        clipboard->setText(full);
    }
    // feedback
    copy_all_btn_->setText(truncated ? QStringLiteral("已复制（已截断）")
                                     : QStringLiteral("已复制"));
    // Parented single-shot so the restore callback dies with this widget
    // instead of surviving test teardown (#951).
    QTimer::singleShot(1500, copy_all_btn_, [this] {
        copy_all_btn_->setText(QStringLiteral("复制全部文本"));
    });
#endif
}

void PdfPreviewWidget::show_fallback_message(const QString& text) {
    fallback_image_->clear();
    fallback_image_->setText(text);
    content_stack_->setCurrentWidget(fallback_image_);
}

}  // namespace pwb::ui_pages_preview
