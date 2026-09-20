// UI-06 — DataReaderPanel shell (see qt/data_reader_panel.hpp).
#include <pwb/ui_pages_data/qt/data_reader_panel.hpp>

#include <QApplication>
#include <QBuffer>
#include <QClipboard>
#include <QContextMenuEvent>
#include <QDesktopServices>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QImageReader>
#include <QLabel>
#include <QMenu>
#include <QPushButton>
#include <QStandardItemModel>
#include <QTextEdit>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>

#include <pwb/ui_pages_data/preview_dispatch.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {

// --- MessagePreview -----------------------------------------------------------

MessagePreview::MessagePreview(QWidget* parent) : QLabel(parent) {
    setObjectName(QStringLiteral("EmptyStateLabel"));
    setAlignment(Qt::AlignmentFlag::AlignCenter);
    setWordWrap(true);
}

// --- TextPreview --------------------------------------------------------------

TextPreview::TextPreview(QWidget* parent) : QTextEdit(parent) {
    setReadOnly(true);
    setObjectName(QStringLiteral("TextPreview"));
}

void TextPreview::apply_settings(int font_size_pt) {
    QFont f = font();
    f.setPointSize(font_size_pt);
    setFont(f);
}

// --- TablePreview -------------------------------------------------------------

TablePreview::TablePreview(QWidget* parent) : QTableView(parent) {
    model_ = new QStandardItemModel(this);
    setModel(model_);
    setEditTriggers(QTableView::EditTrigger::NoEditTriggers);
    setAlternatingRowColors(true);
    setShowGrid(true);
    setSelectionBehavior(QTableView::SelectionBehavior::SelectItems);
    horizontalHeader()->setStretchLastSection(true);
    verticalHeader()->setDefaultSectionSize(28);
    setSizePolicy(QSizePolicy::Policy::Expanding,
                  QSizePolicy::Policy::Expanding);
}

void TablePreview::load_table(
    const std::vector<std::string>& headers,
    const std::vector<std::vector<std::string>>& rows) {
    truncated_ = false;
    truncation_message_.clear();
    const long long n_cols = static_cast<long long>(headers.size());
    const std::size_t keep =
        (n_cols > 0 &&
         static_cast<long long>(rows.size()) * n_cols > kMaxPreviewCells)
            ? static_cast<std::size_t>(
                  std::max<long long>(1, kMaxPreviewCells / n_cols))
            : rows.size();
    if (keep < rows.size()) {
        truncated_ = true;
        truncation_message_ = QStringLiteral(
                                  "表格预览已截断：显示 %1/%2 行"
                                  "（上限 %3 单元格）")
                                  .arg(keep)
                                  .arg(rows.size())
                                  .arg(kMaxPreviewCells);
    }
    setToolTip(truncated_ ? truncation_message_ : QString());
    setStatusTip(truncated_ ? truncation_message_ : QString());

    model_->clear();
    model_->setRowCount(static_cast<int>(keep));
    model_->setColumnCount(static_cast<int>(headers.size()));
    for (int c = 0; c < static_cast<int>(headers.size()); ++c) {
        model_->setHeaderData(c, Qt::Orientation::Horizontal,
                              QString::fromStdString(headers[c]));
    }
    for (std::size_t r = 0; r < keep; ++r) {
        for (std::size_t c = 0; c < headers.size(); ++c) {
            if (c < rows[r].size()) {
                model_->setItem(static_cast<int>(r), static_cast<int>(c),
                                new QStandardItem(
                                    QString::fromStdString(rows[r][c])));
            }
        }
    }

    if (auto_fit_) {
        auto* hdr = horizontalHeader();
        hdr->setSectionResizeMode(QHeaderView::ResizeMode::Interactive);
        hdr->setStretchLastSection(false);
        const auto metrics = fontMetrics();
        const int sample =
            std::min<int>(model_->rowCount(), kAutoFitSampleRows);
        for (int col = 0; col < model_->columnCount(); ++col) {
            int width = metrics.horizontalAdvance(
                            model_->headerData(col,
                                               Qt::Orientation::Horizontal)
                                .toString()) +
                        24;
            for (int r = 0; r < sample; ++r) {
                const auto* item = model_->item(r, col);
                if (item != nullptr) {
                    width = std::max(
                        width, metrics.horizontalAdvance(item->text()) + 24);
                }
            }
            hdr->resizeSection(col, std::max(width + 16, 75));
        }
        hdr->setStretchLastSection(true);
    }
}

std::string TablePreview::copy_all() const {
    const int n_cols = model_->columnCount();
    if (n_cols == 0) return {};
    std::string out;
    for (int c = 0; c < n_cols; ++c) {
        if (c) out += '\t';
        out += model_->headerData(c, Qt::Orientation::Horizontal)
                   .toString()
                   .toStdString();
    }
    out += '\n';
    for (int r = 0; r < model_->rowCount(); ++r) {
        for (int c = 0; c < n_cols; ++c) {
            if (c) out += '\t';
            const auto* item = model_->item(r, c);
            if (item != nullptr) out += item->text().toStdString();
        }
        out += '\n';
    }
    return out;
}

void TablePreview::apply_settings(bool auto_fit) {
    auto_fit_ = auto_fit;
    horizontalHeader()->setSectionResizeMode(
        auto_fit_ ? QHeaderView::ResizeMode::ResizeToContents
                  : QHeaderView::ResizeMode::Interactive);
}

// --- ImagePreview -------------------------------------------------------------

ImagePreview::ImagePreview(QWidget* parent) : QLabel(parent) {
    setObjectName(QStringLiteral("ImagePreview"));
    setAlignment(Qt::AlignmentFlag::AlignCenter);
    setMinimumSize(240, 180);
}

void ImagePreview::load(const QString& path, const QString& revision,
                        const QByteArray& bytes) {
    if (path != path_ || revision != revision_ || pixmap_.isNull()) {
        path_ = path;
        revision_ = revision;
        QImageReader reader;
        if (!bytes.isEmpty()) {
            reader.setDevice(nullptr);
            QBuffer buffer;
            buffer.setData(bytes);
            buffer.open(QIODevice::OpenModeFlag::ReadOnly);
            reader.setDevice(&buffer);
            reader.setAutoTransform(true);
            const QSize size = reader.size();
            if (size.isValid() &&
                std::max(size.width(), size.height()) >
                    kPreviewMaxLongSide) {
                reader.setScaledSize(size.scaled(
                    kPreviewMaxLongSide, kPreviewMaxLongSide,
                    Qt::AspectRatioMode::KeepAspectRatio));
            }
            pixmap_ = QPixmap::fromImage(reader.read());
        } else {
            reader.setFileName(path);
            reader.setAutoTransform(true);
            const QSize size = reader.size();
            if (size.isValid() &&
                std::max(size.width(), size.height()) >
                    kPreviewMaxLongSide) {
                reader.setScaledSize(size.scaled(
                    kPreviewMaxLongSide, kPreviewMaxLongSide,
                    Qt::AspectRatioMode::KeepAspectRatio));
            }
            pixmap_ = QPixmap::fromImage(reader.read());
        }
        zoom_factor_ = 1.0;
        fit_mode_ = true;
    }
    render_current();
}

void ImagePreview::render_current() {
    if (pixmap_.isNull()) {
        clear();
        setText(QStringLiteral("图片预览加载失败"));
        return;
    }
    if (fit_mode_) {
        const QSize target(std::max(width(), 240), std::max(height(), 180));
        setPixmap(pixmap_.scaled(
            target, Qt::AspectRatioMode::KeepAspectRatio,
            Qt::TransformationMode::SmoothTransformation));
    } else {
        const QSize target = pixmap_.size() * zoom_factor_;
        setPixmap(pixmap_.scaled(
            target, Qt::AspectRatioMode::KeepAspectRatio,
            Qt::TransformationMode::SmoothTransformation));
    }
}

void ImagePreview::zoom_in() { set_zoom_factor(zoom_factor_ * kZoomStep); }
void ImagePreview::zoom_out() { set_zoom_factor(zoom_factor_ / kZoomStep); }

void ImagePreview::set_zoom_factor(double factor) {
    const double clamped =
        std::max(kZoomMin, std::min(kZoomMax, factor));
    if (std::abs(clamped - zoom_factor_) < 1e-9 && !fit_mode_) return;
    zoom_factor_ = clamped;
    fit_mode_ = false;
    render_current();
    Q_EMIT zoom_changed(zoom_factor_);
}

void ImagePreview::set_fit_mode(bool enabled) {
    if (enabled == fit_mode_) return;
    fit_mode_ = enabled;
    render_current();
    Q_EMIT zoom_changed(zoom_factor_);
}

void ImagePreview::resizeEvent(QResizeEvent* event) {
    QLabel::resizeEvent(event);
    if (fit_mode_ && !pixmap_.isNull()) render_current();
}

// --- PdfPreview ---------------------------------------------------------------

PdfPreview::PdfPreview(QWidget* parent) : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    auto* nav = new QHBoxLayout();
    nav->addStretch();
    prev_btn_ = new QPushButton(QStringLiteral("上一页"), this);
    prev_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(prev_btn_, &QPushButton::clicked, this,
            &PdfPreview::previous_page);
    nav->addWidget(prev_btn_);
    page_label_ = new QLabel(QStringLiteral("1 / 0"), this);
    page_label_->setAlignment(Qt::AlignmentFlag::AlignCenter);
    page_label_->setMinimumWidth(72);
    nav->addWidget(page_label_);
    next_btn_ = new QPushButton(QStringLiteral("下一页"), this);
    next_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(next_btn_, &QPushButton::clicked, this, &PdfPreview::next_page);
    nav->addWidget(next_btn_);
    layout->addLayout(nav);
    fallback_image_ = new QLabel(this);
    fallback_image_->setAlignment(Qt::AlignmentFlag::AlignCenter);
    fallback_image_->setText(QStringLiteral("PDF 预览不可用"));
    layout->addWidget(fallback_image_, 1);
    sync_nav();
}

void PdfPreview::load(const QString& path, const QString& /*revision*/,
                      const QByteArray& pdf_bytes) {
    path_ = path;
    // The document seam: without Qt6::Pdf we count neither pages nor
    // render — a .pdf on disk still shows the fallback with path text.
    page_count_ = 0;
    if (!pdf_bytes.isEmpty() || !path.isEmpty()) {
        fallback_image_->setText(
            QStringLiteral("PDF: %1").arg(path.isEmpty() ? "bytes" : path));
    }
    sync_nav();
}

void PdfPreview::next_page() {
    if (zoom_.next_page(page_count_)) sync_nav();
}

void PdfPreview::previous_page() {
    if (zoom_.previous_page()) sync_nav();
}

void PdfPreview::sync_nav() {
    page_label_->setText(
        QString::fromStdString(zoom_.page_label(page_count_)));
    prev_btn_->setEnabled(zoom_.page_index() > 0);
    next_btn_->setEnabled(zoom_.page_index() + 1 < page_count_);
}

// --- DataReaderPanel ----------------------------------------------------------

DataReaderPanel::DataReaderPanel(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("DataReaderPanel"));
    setMinimumWidth(320);
    ui_shell::style_bind(this, [] {
        const auto p = ui_shell::style_palette();
        auto at = [&](const char* k) {
            const auto it = p.find(k);
            return it != p.end() ? QString::fromStdString(it->second)
                                 : QString();
        };
        return QStringLiteral(
                   "QFrame#DataReaderPanel { background: %1;"
                   " border: 1px solid %2; border-radius: 6px; }")
            .arg(at("BG_SIDEBAR"), at("BORDER"));
    });
    current_.title = "请选择数据项";

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);
    layout->setSpacing(8);

    title_ = new QLabel(QStringLiteral("请选择数据项"), this);
    title_->setObjectName(QStringLiteral("DataReaderTitle"));
    title_->setWordWrap(true);
    ui_shell::style_bind(title_, [] {
        const auto p = ui_shell::style_palette();
        const auto it = p.find("TEXT_PRIMARY");
        return QStringLiteral("color: %1; font-weight: 600;")
            .arg(it != p.end() ? QString::fromStdString(it->second)
                               : QString());
    });
    layout->addWidget(title_);

    meta_ = new QLabel(QString(), this);
    meta_->setObjectName(QStringLiteral("DataReaderMeta"));
    meta_->setWordWrap(true);
    layout->addWidget(meta_);

    table_toolbar_ = new QWidget(this);
    auto* tb = new QHBoxLayout(table_toolbar_);
    tb->setContentsMargins(0, 0, 0, 0);
    tb->addStretch();
    table_copy_btn_ = new QPushButton(QStringLiteral("复制全部"),
                                      table_toolbar_);
    table_copy_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    table_copy_btn_->setToolTip(
        QStringLiteral("将当前表格以 TSV 复制到剪贴板"));
    connect(table_copy_btn_, &QPushButton::clicked, this,
            &DataReaderPanel::on_copy_table_all);
    tb->addWidget(table_copy_btn_);
    table_toolbar_->setVisible(false);
    layout->addWidget(table_toolbar_);

    image_toolbar_ = new QWidget(this);
    auto* itb = new QHBoxLayout(image_toolbar_);
    itb->setContentsMargins(0, 0, 0, 0);
    itb->addStretch();
    image_fit_btn_ = new QPushButton(QStringLiteral("适应窗口"),
                                     image_toolbar_);
    image_fit_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    image_fit_btn_->setCheckable(true);
    image_fit_btn_->setChecked(true);
    image_fit_btn_->setToolTip(QStringLiteral("适应窗口大小"));
    connect(image_fit_btn_, &QPushButton::clicked, this,
            [this](bool checked) {
                image_->set_fit_mode(checked);
                sync_image_zoom_ui();
            });
    itb->addWidget(image_fit_btn_);
    image_zoom_out_btn_ = new QPushButton(QStringLiteral("−"),
                                          image_toolbar_);
    image_zoom_out_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(image_zoom_out_btn_, &QPushButton::clicked, this, [this] {
        image_->zoom_out();
        sync_image_zoom_ui();
    });
    itb->addWidget(image_zoom_out_btn_);
    image_zoom_label_ = new QLabel(QStringLiteral("100%"), image_toolbar_);
    image_zoom_label_->setAlignment(Qt::AlignmentFlag::AlignCenter);
    image_zoom_label_->setMinimumWidth(48);
    itb->addWidget(image_zoom_label_);
    image_zoom_in_btn_ = new QPushButton(QStringLiteral("+"),
                                         image_toolbar_);
    image_zoom_in_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(image_zoom_in_btn_, &QPushButton::clicked, this, [this] {
        image_->zoom_in();
        sync_image_zoom_ui();
    });
    itb->addWidget(image_zoom_in_btn_);
    image_toolbar_->setVisible(false);
    layout->addWidget(image_toolbar_);

    stack_ = new QStackedWidget(this);
    layout->addWidget(stack_, 1);

    // Registration order mirrors Python's addWidget order (indices matter
    // only for stack bookkeeping). Native targets register under their
    // preview_dispatch target names — target_for resolves mode→name and a
    // name mismatch would silently route real previews to the message
    // widget (main-line latent defect surfaced by task 04's
    // "keep image/table/JSON/PDF capabilities" acceptance).
    empty_ = new MessagePreview(this);
    empty_->set_message(
        QStringLiteral("从列表中选择一个数据、成果或文件"));
    register_target(QStringLiteral("empty_label"), empty_);
    message_ = new MessagePreview(this);
    register_target(QStringLiteral("message_label"), message_);
    text_ = new TextPreview(this);
    register_target(QStringLiteral("text_preview"), text_);
    table_ = new TablePreview(this);
    register_target(QStringLiteral("table_preview"), table_);
    image_ = new ImagePreview(this);
    register_target(QStringLiteral("image_preview_widget"), image_);
    pdf_ = new PdfPreview(this);
    register_target(QStringLiteral("pdf_preview_widget"), pdf_);

    warning_ = new QLabel(QString(), this);
    warning_->setWordWrap(true);
    ui_shell::style_bind(warning_, [] {
        const auto p = ui_shell::style_palette();
        const auto it = p.find("WARNING");
        return QStringLiteral("color: %1; font-size: 12px;")
            .arg(it != p.end() ? QString::fromStdString(it->second)
                               : QString());
    });
    layout->addWidget(warning_);

    // CLOSURE-PREVIEW (task 04): dedicated loading page — the Python
    // "正在生成预览…" message plus a 取消 affordance (visible only while a
    // cancel hook is armed).
    loading_page_ = new QWidget(this);
    auto* loading_layout = new QVBoxLayout(loading_page_);
    loading_layout->setContentsMargins(0, 0, 0, 0);
    auto* loading_label = new MessagePreview(loading_page_);
    loading_label->set_message(QStringLiteral("正在生成预览…"));
    loading_label->setObjectName("LoadingLabel");
    loading_layout->addWidget(loading_label, 1);

    stack_->setCurrentWidget(empty_);
    connect(image_, &ImagePreview::zoom_changed, this,
            [this](double) { sync_image_zoom_ui(); });
}

void DataReaderPanel::register_target(const QString& name, QWidget* w) {
    // CLOSURE-PREVIEW (task 04): re-registering a target replaces the old
    // widget (external presenters rebuild their page per preview) — the
    // stale widget leaves the stack instead of accumulating in it.
    const auto it = targets_.find(name);
    if (it != targets_.end() && it->second != w) {
        QWidget* old = it->second;
        stack_->removeWidget(old);
        old->deleteLater();
    }
    targets_[name] = w;
    stack_->addWidget(w);
}

void DataReaderPanel::register_render_hook(const QString& name,
                                           PreviewRenderHook hook) {
    hooks_[name] = std::move(hook);
}

void DataReaderPanel::set_visualization_hooks(
    QWidget* tabs,
    std::function<void(const PreviewResultView&)> load_summary,
    std::function<void()> reset_tabs,
    std::function<void()> show_loading,
    std::function<void(const QString&, bool)> show_error) {
    viz_tabs_ = tabs;
    if (tabs != nullptr) register_target(QStringLiteral("geoviz"), tabs);
    viz_load_summary_ = std::move(load_summary);
    viz_reset_ = std::move(reset_tabs);
    viz_show_loading_ = std::move(show_loading);
    viz_show_error_ = std::move(show_error);
}

void DataReaderPanel::set_geoviz_show_fn(
    std::function<bool(const PreviewResultView&)> fn) {
    geoviz_show_ = std::move(fn);
}

void DataReaderPanel::show_loading(const std::string& resolved_name) {
    if (viz_reset_) viz_reset_();
    title_->setText(
        QString::fromStdString(loading_title(resolved_name)));
    meta_->setText(QString());
    warning_->setText(QString::fromStdString(safe_clear_geoviz()));
    message_->set_message(QStringLiteral("正在生成预览…"));
    stack_->setCurrentWidget(loading_page_);
    current_mode_ = "loading";
    table_toolbar_->setVisible(false);
    image_toolbar_->setVisible(false);
    Q_EMIT reader_mode_changed(QStringLiteral("loading"));
}

void DataReaderPanel::set_cancel_hook(std::function<bool()> hook) {
    cancel_hook_ = std::move(hook);
    // (Re)build the cancel affordance for the armed state.
    if (auto* btn = loading_page_->findChild<QPushButton*>(
            QStringLiteral("LoadingCancelButton"));
        btn != nullptr) {
        btn->deleteLater();
    }
    if (cancel_hook_ == nullptr) return;
    auto* btn = new QPushButton(QStringLiteral("取消"), loading_page_);
    btn->setObjectName(QStringLiteral("LoadingCancelButton"));
    auto* box = qobject_cast<QVBoxLayout*>(loading_page_->layout());
    if (box != nullptr) {
        auto* row = new QHBoxLayout();
        row->addStretch(1);
        row->addWidget(btn);
        row->addStretch(1);
        box->addLayout(row);
    }
    connect(btn, &QPushButton::clicked, this, [this]() {
        if (cancel_hook_ != nullptr) cancel_hook_();
    });
}

void DataReaderPanel::render(const PreviewResultView& result) {
    PreviewResultView r = result;
    // viz entry: available AND mode ∉ {geoviz, seismic}
    if (viz_entry_shown(r.visualization_available, r.mode) &&
        viz_tabs_ != nullptr) {
        const std::string clear_warning = safe_clear_geoviz();
        if (!clear_warning.empty()) {
            r.warning = merge_warning(r.warning, clear_warning);
        }
        if (viz_load_summary_) viz_load_summary_(r);
        commit(r, viz_tabs_);
        return;
    }
    // geoviz + PreparedPreview → engine path.
    if (r.mode == "geoviz" && r.engine_preview_prepared &&
        geoviz_show_ && viz_tabs_ != nullptr) {
        if (viz_load_summary_) viz_load_summary_(r);
        geoviz_host_created_ = true;
        if (geoviz_show_(r)) {
            commit(r, viz_tabs_);
            return;
        }
        // failure → message result (geoviz_failure_result parity)
        r.mode = "message";
        r.message = r.message.empty() ? "预览不可用" : r.message;
        r.warning = merge_warning(r.warning, "geoviz render failed");
        commit(r, message_);
        return;
    }
    const std::string clear_warning = safe_clear_geoviz();
    if (viz_reset_) viz_reset_();
    if (r.mode == "geoviz") {
        r.mode = "message";
        if (r.message.empty()) r.message = "预览不可用";
    }
    if (!clear_warning.empty()) {
        r.warning = merge_warning(r.warning, clear_warning);
    }
    commit(r, target_for(r.mode, r));
}

void DataReaderPanel::render_visualization(
    const PreviewResultView& result) {
    if (result.mode != "geoviz" || !result.engine_preview_prepared) {
        show_visualization_error(
            result.message.empty()
                ? QStringLiteral("可视化预览不可用")
                : QString::fromStdString(result.message),
            result.retryable);
        if (!result.warning.empty()) {
            warning_->setText(QString::fromStdString(merge_warning(
                warning_->text().toStdString(), result.warning)));
        }
        return;
    }
    geoviz_host_created_ = true;
    if (!geoviz_show_ || !geoviz_show_(result)) {
        show_visualization_error(QStringLiteral("geoviz render failed"));
        return;
    }
    if (!result.warning.empty()) {
        warning_->setText(QString::fromStdString(merge_warning(
            warning_->text().toStdString(), result.warning)));
    }
}

void DataReaderPanel::show_visualization_loading() {
    if (viz_show_loading_) viz_show_loading_();
}

void DataReaderPanel::show_visualization_error(const QString& message,
                                               bool retryable) {
    if (viz_show_error_) viz_show_error_(message, retryable);
}

void DataReaderPanel::next_pdf_page() { pdf_->next_page(); }
void DataReaderPanel::previous_pdf_page() { pdf_->previous_page(); }

void DataReaderPanel::apply_preview_settings(bool show_metadata,
                                             int font_size_pt,
                                             bool auto_fit_columns) {
    meta_->setVisible(show_metadata);
    text_->apply_settings(font_size_pt);
    table_->apply_settings(auto_fit_columns);
    Q_EMIT preview_settings_changed();
}

QWidget* DataReaderPanel::target_for(const std::string& mode,
                                     const PreviewResultView& result) {
    const auto name = QString::fromStdString(std::string(
        ui_pages_data::preview_target(mode)));
    auto it = targets_.find(name);
    QWidget* target = it != targets_.end() ? it->second : message_;
    auto hook = hooks_.find(name);
    if (hook != hooks_.end() && hook->second) {
        hook->second(target, result);
    } else if (mode == "text") {
        text_->load_text(QString::fromStdString(result.text));
    } else if (mode == "table") {
        table_->load_table(result.table_headers, result.table_rows);
    } else if (mode == "image") {
        image_->load(QString::fromStdString(result.path),
                     QString::fromStdString(result.revision));
    } else if (mode == "pdf") {
        pdf_->load(QString::fromStdString(result.path),
                   QString::fromStdString(result.revision));
    } else if (mode == "message") {
        message_->set_message(QString::fromStdString(
            result.message.empty() ? "预览不可用" : result.message));
    } else if (target == message_) {
        // Unknown mode → the dict-.get default: render the result's own
        // message (or 预览不可用) instead of a stale previous payload.
        message_->set_message(QString::fromStdString(
            result.message.empty() ? "预览不可用" : result.message));
    }
    return target;
}

void DataReaderPanel::commit(const PreviewResultView& result,
                             QWidget* target) {
    current_ = result;
    title_->setText(QString::fromStdString(result.title));
    meta_->setText(QString::fromStdString(preview_meta_text(
        result.type_label, result.format, result.status, result.path)));
    std::string warning = result.warning;
    if (target == table_ && table_->truncated()) {
        warning = merge_warning(
            warning, table_->truncation_message().toStdString());
    }
    warning_->setText(QString::fromStdString(warning));
    stack_->setCurrentWidget(target);
    current_mode_ = result.mode;
    const bool is_table = target == table_;
    table_toolbar_->setVisible(is_table);
    if (is_table && table_->truncated()) {
        table_copy_btn_->setToolTip(table_->truncation_message());
    } else {
        table_copy_btn_->setToolTip(
            QStringLiteral("将当前表格以 TSV 复制到剪贴板"));
    }
    const bool is_image = target == image_;
    image_toolbar_->setVisible(is_image);
    if (is_image) sync_image_zoom_ui();
    Q_EMIT reader_mode_changed(QString::fromStdString(result.mode));
}

void DataReaderPanel::sync_image_zoom_ui() {
    image_zoom_label_->setText(QStringLiteral("%1%").arg(
        static_cast<int>(std::lround(image_->zoom_factor() * 100))));
    image_fit_btn_->blockSignals(true);
    image_fit_btn_->setChecked(image_->fit_mode());
    image_fit_btn_->blockSignals(false);
}

void DataReaderPanel::on_copy_table_all() {
    std::string text = table_->copy_all();
    if (table_->truncated() && !table_->truncation_message().isEmpty()) {
        text += "\n" + table_->truncation_message().toStdString();
        table_copy_btn_->setToolTip(table_->truncation_message());
    }
    if (QClipboard* clipboard = QApplication::clipboard()) {
        clipboard->setText(QString::fromStdString(text));
    }
    table_copy_btn_->setText(QStringLiteral("已复制"));
    // Parented single-shot restore (1200 ms — Python parity).
    auto* timer = new QTimer(this);
    timer->setSingleShot(true);
    connect(timer, &QTimer::timeout, this, [this, timer] {
        if (table_copy_btn_->text() == QStringLiteral("已复制")) {
            table_copy_btn_->setText(QStringLiteral("复制全部"));
        }
        timer->deleteLater();
    });
    timer->start(1200);
}

std::string DataReaderPanel::safe_clear_geoviz() {
    // Host stays uncreated until a prepared preview lands; clearing an
    // uncreated host is a no-op that cannot throw.
    return {};
}

void DataReaderPanel::contextMenuEvent(QContextMenuEvent* event) {
    QMenu menu(this);
    QAction* action =
        menu.addAction(QStringLiteral("用系统应用打开"));
    action->setEnabled(!current_.path.empty());
    connect(action, &QAction::triggered, this, [this] {
        if (!current_.path.empty()) {
            QDesktopServices::openUrl(QUrl::fromLocalFile(
                QString::fromStdString(current_.path)));
        }
    });
    menu.exec(event->globalPos());
}

}  // namespace pwb::ui_pages_data::qt
