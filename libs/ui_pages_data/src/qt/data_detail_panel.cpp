// UI-06 — DataDetailPanel shell (see qt/data_detail_panel.hpp).
#include <pwb/ui_pages_data/qt/data_detail_panel.hpp>

#include <QLabel>
#include <QPixmap>
#include <QVBoxLayout>

#include <pwb/ui_pages_data/vocab.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {

namespace {

QString pal(const char* key) {
    const auto p = ui_shell::style_palette();
    const auto it = p.find(key);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

}  // namespace

DataDetailPanel::DataDetailPanel(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("DataDetailPanel"));
    setMinimumWidth(240);
    ui_shell::style_bind(this, [] {
        return QStringLiteral(
                   "QFrame#DataDetailPanel { background: %1;"
                   " border: 1px solid %2; border-radius: 6px; }")
            .arg(pal("BG_SIDEBAR"), pal("BORDER"));
    });

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);
    layout->setSpacing(12);

    title_ = new QLabel(QStringLiteral("请选择数据项"), this);
    ui_shell::style_bind(title_, [] {
        return QStringLiteral("color: %1; font-weight: 600;")
            .arg(pal("TEXT_PRIMARY"));
    });
    layout->addWidget(title_);

    metadata_layout_ = new QVBoxLayout();
    metadata_layout_->setSpacing(4);
    layout->addLayout(metadata_layout_);

    preview_title_ = new QLabel(QStringLiteral("预览"), this);
    ui_shell::style_bind(preview_title_, [] {
        return QStringLiteral("color: %1; font-weight: 600;")
            .arg(pal("TEXT_PRIMARY"));
    });
    layout->addWidget(preview_title_);

    preview_layout_ = new QVBoxLayout();
    preview_layout_->setSpacing(4);
    layout->addLayout(preview_layout_);
    layout->addStretch();

    update_asset(std::nullopt);
}

void DataDetailPanel::update_asset(
    const std::optional<AssetRow>& asset) {
    clear_layout(metadata_layout_);
    clear_layout(preview_layout_);

    if (!asset.has_value()) {
        title_->setText(QStringLiteral("请选择数据项"));
        add_muted(metadata_layout_,
                  QStringLiteral("从列表中选择一个数据、成果或文件"));
        preview_title_->setText(QStringLiteral("预览"));
        add_muted(preview_layout_, QStringLiteral("暂无预览"));
        return;
    }

    const AssetRow& row = *asset;
    const std::string dir = base_dir();

    if (row.kind == AssetKind::Artifact) {
        // _update_artifact parity.
        const QString path =
            QString::fromStdString(row.view.path);
        const QString name =
            path.section('/', -1).isEmpty() ? path : path.section('/', -1);
        title_->setText(name);
        add_row(QStringLiteral("类型"), QStringLiteral("成果"));
        add_row(QStringLiteral("格式"),
                QString::fromStdString(row.view.format));
        add_row(QStringLiteral("路径"), path);
        add_row(QStringLiteral("关联"),
                QString::fromStdString(row.view.linked_id));
        const auto state =
            preview_fn_ ? preview_fn_(row, dir) : DetailPreviewState{};
        preview_title_->setText(QString::fromStdString(state.title));
        for (const auto& line : state.lines) {
            add_muted(preview_layout_, QString::fromStdString(line));
        }
        return;
    }

    // _update_resource parity.
    title_->setText(QString::fromStdString(row.view.name));
    add_row(QStringLiteral("类型"),
            QString::fromStdString(std::string(
                resource_type_label(row.view.type))));
    add_row(QStringLiteral("格式"),
            QString::fromStdString(row.view.format));
    add_row(QStringLiteral("状态"),
            QString::fromStdString(row.view.status));
    add_row(QStringLiteral("路径"),
            QString::fromStdString(row.view.path));
    add_row(QStringLiteral("校验"),
            row.view.checksum.empty()
                ? QStringLiteral("—")
                : QString::fromStdString(row.view.checksum));

    const auto state =
        preview_fn_ ? preview_fn_(row, dir) : DetailPreviewState{};
    preview_title_->setText(QString::fromStdString(state.title));
    if (state.mode == "image" && !state.image_path.empty()) {
        if (!add_image_preview(QString::fromStdString(state.image_path))) {
            add_warning(QStringLiteral("图片预览加载失败"));
        }
        add_muted(preview_layout_,
                  QStringLiteral("图片: %1").arg(
                      QString::fromStdString(state.image_path)));
    } else if (state.mode == "pdf" && !state.document_path.empty()) {
        if (!add_pdf_preview(QString::fromStdString(state.document_path))) {
            add_warning(QStringLiteral("PDF预览加载失败"));
        }
        add_muted(preview_layout_,
                  QStringLiteral("PDF: %1").arg(
                      QString::fromStdString(state.document_path)));
    } else if (state.mode == "text" || state.mode == "table") {
        for (const auto& line : state.lines) {
            add_preview_line(QString::fromStdString(line));
        }
    } else {
        for (const auto& line : state.lines) {
            add_muted(preview_layout_, QString::fromStdString(line));
        }
    }
    if (!state.warning.empty()) {
        add_warning(QString::fromStdString(state.warning));
    }
}

void DataDetailPanel::show_downstream_impact(
    const std::vector<std::tuple<std::string, std::string, std::string>>&
        rows) {
    if (rows.empty()) return;
    auto* title = new QLabel(QStringLiteral("下游影响"), this);
    ui_shell::style_bind(title, [] {
        return QStringLiteral("color: %1; font-weight: 600;")
            .arg(pal("TEXT_PRIMARY"));
    });
    metadata_layout_->addWidget(title);
    for (std::size_t i = 0; i < rows.size() && i < 20; ++i) {
        const auto& [label, state, state_label] = rows[i];
        auto* line = new QLabel(
            QStringLiteral("· %1 — %2")
                .arg(QString::fromStdString(label.empty() ? "?" : label),
                     QString::fromStdString(state_label)),
            this);
        line->setWordWrap(true);
        const bool stale = state == "STALE";
        ui_shell::style_bind(line, [stale] {
            return QStringLiteral("color: %1;")
                .arg(pal(stale ? "WARNING" : "TEXT_SECONDARY"));
        });
        metadata_layout_->addWidget(line);
    }
}

void DataDetailPanel::add_row(const QString& label, const QString& value) {
    auto* item = new QLabel(QStringLiteral("%1: %2").arg(label, value), this);
    item->setWordWrap(true);
    ui_shell::style_bind(item, [] {
        return QStringLiteral("color: %1;").arg(pal("TEXT_PRIMARY"));
    });
    metadata_layout_->addWidget(item);
}

void DataDetailPanel::add_muted(QVBoxLayout* layout, const QString& text) {
    auto* item = new QLabel(text, this);
    item->setWordWrap(true);
    ui_shell::style_bind(item, [] {
        return QStringLiteral("color: %1;").arg(pal("TEXT_SECONDARY"));
    });
    layout->addWidget(item);
}

void DataDetailPanel::add_preview_line(const QString& text) {
    auto* item = new QLabel(text, this);
    item->setWordWrap(true);
    item->setTextInteractionFlags(
        Qt::TextInteractionFlag::TextSelectableByMouse);
    ui_shell::style_bind(item, [] {
        return QStringLiteral("color: %1; font-family: monospace;")
            .arg(pal("TEXT_SECONDARY"));
    });
    preview_layout_->addWidget(item);
}

bool DataDetailPanel::add_image_preview(const QString& path) {
    const QPixmap pixmap(path);
    if (pixmap.isNull()) return false;
    auto* label = new QLabel(this);
    label->setObjectName(QStringLiteral("DataPreviewImage"));
    label->setAlignment(Qt::AlignmentFlag::AlignCenter);
    label->setPixmap(pixmap.scaled(
        220, 160, Qt::AspectRatioMode::KeepAspectRatio,
        Qt::TransformationMode::SmoothTransformation));
    preview_layout_->addWidget(label);
    return true;
}

bool DataDetailPanel::add_pdf_preview(const QString& path) {
    if (!pdf_factory_) return false;
    auto document = pdf_factory_(path);
    if (document == nullptr || document->page_count() <= 0) return false;
    preview_layout_->addWidget(
        new PdfPreviewPanel(std::move(document), this));
    return true;
}

void DataDetailPanel::add_warning(const QString& text) {
    auto* item = new QLabel(text, this);
    item->setWordWrap(true);
    ui_shell::style_bind(item, [] {
        return QStringLiteral("color: %1;").arg(pal("WARNING"));
    });
    preview_layout_->addWidget(item);
}

void DataDetailPanel::clear_layout(QVBoxLayout* layout) {
    while (layout->count()) {
        QLayoutItem* child = layout->takeAt(0);
        if (QWidget* widget = child->widget()) {
            widget->hide();
            widget->setParent(nullptr);
            widget->deleteLater();
        }
        delete child;
    }
}

std::string DataDetailPanel::base_dir() const {
    // Python: base_path.parent — the project FILE's directory.
    const auto pos = project_path_.find_last_of('/');
    return pos == std::string::npos ? std::string()
                                    : project_path_.substr(0, pos);
}

}  // namespace pwb::ui_pages_data::qt
