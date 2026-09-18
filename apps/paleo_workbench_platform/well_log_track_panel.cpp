#include "well_log_track_panel.hpp"

#include <pwb/viz/well_log_host_widget.hpp>
#include <pwb/viz/well_log_track_layout.hpp>

#include <QComboBox>
#include <QFile>
#include <QFileDialog>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QListWidgetItem>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>

#include <algorithm>
#include <optional>
#include <string>

namespace {

std::string mnemonic_of(const std::string& curve_key) {
    // "curve:{index}:{mnemonic}" → mnemonic part (may contain ':').
    const auto separator = curve_key.find(':');
    const auto second = curve_key.find(':', separator + 1);
    if (second == std::string::npos) {
        return curve_key;
    }
    return curve_key.substr(second + 1);
}

} // namespace

WellLogTrackPanel::WellLogTrackPanel(QWidget* parent) : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(4, 4, 4, 4);

    hint_ = new QLabel(tr("加载井数据后可配置轨道"), this);
    layout->addWidget(hint_);

    curves_ = new QListWidget(this);
    curves_->setSelectionMode(QAbstractItemView::SingleSelection);
    layout->addWidget(curves_, 1);

    auto* scale_row = new QHBoxLayout;
    scale_row->addWidget(new QLabel(tr("比例:"), this));
    scale_mode_ = new QComboBox(this);
    scale_mode_->addItem(tr("自动"));
    scale_mode_->addItem(tr("线性"));
    scale_mode_->addItem(tr("对数"));
    scale_row->addWidget(scale_mode_, 1);
    layout->addLayout(scale_row);

    auto* row_buttons = new QHBoxLayout;
    auto* merge_button = new QPushButton(tr("合并到上一轨"), this);
    auto* unmerge_button = new QPushButton(tr("拆分"), this);
    row_buttons->addWidget(merge_button);
    row_buttons->addWidget(unmerge_button);
    layout->addLayout(row_buttons);

    auto* order_buttons = new QHBoxLayout;
    auto* up_button = new QPushButton(tr("上移"), this);
    auto* down_button = new QPushButton(tr("下移"), this);
    order_buttons->addWidget(up_button);
    order_buttons->addWidget(down_button);
    layout->addLayout(order_buttons);

    auto* template_buttons = new QHBoxLayout;
    auto* save_button = new QPushButton(tr("模板保存"), this);
    auto* load_button = new QPushButton(tr("模板加载"), this);
    template_buttons->addWidget(save_button);
    template_buttons->addWidget(load_button);
    layout->addLayout(template_buttons);

    auto* export_buttons = new QHBoxLayout;
    auto* png_button = new QPushButton(tr("PNG"), this);
    auto* svg_button = new QPushButton(tr("SVG"), this);
    auto* pdf_button = new QPushButton(tr("PDF"), this);
    export_buttons->addWidget(png_button);
    export_buttons->addWidget(svg_button);
    export_buttons->addWidget(pdf_button);
    layout->addLayout(export_buttons);

    connect(curves_, &QListWidget::itemChanged, this,
            &WellLogTrackPanel::on_item_changed);
    connect(merge_button, &QPushButton::clicked, this,
            &WellLogTrackPanel::on_merge_selected);
    connect(unmerge_button, &QPushButton::clicked, this,
            &WellLogTrackPanel::on_unmerge_selected);
    connect(up_button, &QPushButton::clicked, this,
            [this] { on_move_group(-1); });
    connect(down_button, &QPushButton::clicked, this,
            [this] { on_move_group(1); });
    connect(scale_mode_, &QComboBox::activated, this,
            &WellLogTrackPanel::on_scale_mode_changed);
    connect(save_button, &QPushButton::clicked, this,
            &WellLogTrackPanel::on_save_template);
    connect(load_button, &QPushButton::clicked, this,
            &WellLogTrackPanel::on_load_template);
    connect(png_button, &QPushButton::clicked, this,
            [this] { on_export(QStringLiteral("png"),
                               tr("PNG 图像 (*.png)")); });
    connect(svg_button, &QPushButton::clicked, this,
            [this] { on_export(QStringLiteral("svg"),
                               tr("SVG 矢量 (*.svg)")); });
    connect(pdf_button, &QPushButton::clicked, this,
            [this] { on_export(QStringLiteral("pdf"),
                               tr("PDF 文档 (*.pdf)")); });
}

WellLogTrackPanel::~WellLogTrackPanel() = default;

void WellLogTrackPanel::bind(pwb::viz::WellLogHostWidget* host) {
    host_ = host;
    refresh();
}

void WellLogTrackPanel::refresh() {
    rebuilding_ = true;
    curves_->clear();
    if (host_ == nullptr || !host_->has_document()) {
        hint_->setText(tr("加载井数据后可配置轨道"));
        scale_mode_->setEnabled(false);
        rebuilding_ = false;
        return;
    }
    const auto layout = host_->track_layout();
    for (std::size_t i = 0; i < layout.curve_keys.size(); ++i) {
        auto* item = new QListWidgetItem(QString::fromStdString(mnemonic_of(layout.curve_keys[i])),
                                         curves_);
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(layout.visible[i] ? Qt::Checked : Qt::Unchecked);
        item->setData(Qt::UserRole, QString::fromStdString(layout.curve_keys[i]));
        // Group label: which track number holds this curve.
        for (std::size_t g = 0; g < layout.groups.size(); ++g) {
            const auto& group = layout.groups[g];
            if (std::find(group.begin(), group.end(), layout.curve_keys[i]) !=
                group.end()) {
                item->setText(tr("%1  (轨道 %2)")
                                  .arg(QString::fromStdString(mnemonic_of(layout.curve_keys[i])))
                                  .arg(g + 1));
                break;
            }
        }
    }
    scale_mode_->setEnabled(true);
    hint_->setText(tr("井 %1").arg(host_->document_id_text().left(8)));
    rebuilding_ = false;
}

pwb::viz::WellLogHostWidget* WellLogTrackPanel::host() const { return host_; }

void WellLogTrackPanel::on_item_changed(QListWidgetItem* item) {
    if (rebuilding_ || host() == nullptr || item == nullptr) {
        return;
    }
    const auto key = item->data(Qt::UserRole).toString().toStdString();
    try {
        (void)host()->apply_track_layout(
            host()->track_layout().with_visible(key, item->checkState() == Qt::Checked));
    } catch (const std::exception&) {
        // Unknown key after a reload: refresh will re-sync the list.
    }
    refresh();
}

void WellLogTrackPanel::on_move_group(int offset) {
    if (host() == nullptr) return;
    auto* item = curves_->currentItem();
    if (item == nullptr) return;
    const auto key = item->data(Qt::UserRole).toString().toStdString();
    const auto layout = host()->track_layout();
    std::size_t position = 0;
    for (std::size_t g = 0; g < layout.groups.size(); ++g) {
        if (std::find(layout.groups[g].begin(), layout.groups[g].end(), key) !=
            layout.groups[g].end()) {
            position = g;
            break;
        }
    }
    const auto target = static_cast<long long>(position) + offset;
    if (target < 0 || target >= static_cast<long long>(layout.groups.size())) {
        return;
    }
    (void)host()->apply_track_layout(layout.move_group(key, static_cast<std::size_t>(target)));
    refresh();
}

void WellLogTrackPanel::on_merge_selected() {
    if (host() == nullptr) return;
    auto* item = curves_->currentItem();
    if (item == nullptr) return;
    const auto key = item->data(Qt::UserRole).toString().toStdString();
    const auto layout = host()->track_layout();
    // Merge onto the previous group's first curve (the panel-level gesture
    // counterpart of the settings dialog's drag-onto action).
    std::size_t group_index = 0;
    for (std::size_t g = 0; g < layout.groups.size(); ++g) {
        if (std::find(layout.groups[g].begin(), layout.groups[g].end(), key) !=
            layout.groups[g].end()) {
            group_index = g;
            break;
        }
    }
    if (group_index == 0) return;
    const auto& onto_group = layout.groups[group_index - 1];
    try {
        (void)host()->apply_track_layout(layout.merge(key, onto_group.front()));
    } catch (const pwb::viz::curve_group_limit_error& e) {
        QMessageBox::information(this, tr("合并受限"),
                                 QString::fromLocal8Bit(e.what()));
        return;
    }
    refresh();
}

void WellLogTrackPanel::on_unmerge_selected() {
    if (host() == nullptr) return;
    auto* item = curves_->currentItem();
    if (item == nullptr) return;
    const auto key = item->data(Qt::UserRole).toString().toStdString();
    (void)host()->apply_track_layout(host()->track_layout().unmerge(key));
    refresh();
}

void WellLogTrackPanel::on_scale_mode_changed(int index) {
    if (rebuilding_ || host() == nullptr) return;
    auto* item = curves_->currentItem();
    if (item == nullptr) return;
    const auto key = item->data(Qt::UserRole).toString().toStdString();
    std::optional<pwb::viz::TrackScaleMode> mode;
    if (index == 1) mode = pwb::viz::TrackScaleMode::linear;
    if (index == 2) mode = pwb::viz::TrackScaleMode::logarithmic;
    (void)host()->apply_track_layout(host()->track_layout().with_scale_mode(key, mode));
    refresh();
}

void WellLogTrackPanel::on_save_template() {
    if (host() == nullptr || !host()->has_document()) return;
    const QString path = QFileDialog::getSaveFileName(
        this, tr("保存轨道模板"), QStringLiteral("well_log_template.json"),
        tr("JSON 模板 (*.json)"));
    if (path.isEmpty()) return;
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        QMessageBox::warning(this, tr("保存失败"), tr("无法写入文件"));
        return;
    }
    const auto json_text = host()->track_layout().to_template_json();
    file.write(json_text.data(), static_cast<qint64>(json_text.size()));
}

void WellLogTrackPanel::on_load_template() {
    if (host() == nullptr || !host()->has_document()) return;
    const QString path = QFileDialog::getOpenFileName(
        this, tr("加载轨道模板"), QString(), tr("JSON 模板 (*.json)"));
    if (path.isEmpty()) return;
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        QMessageBox::warning(this, tr("加载失败"), tr("无法读取文件"));
        return;
    }
    const auto raw = file.readAll();
    pwb::viz::WellLogTrackLayout restored;
    std::string error;
    if (!pwb::viz::WellLogTrackLayout::from_template_json(
            raw.toStdString(), restored, &error)) {
        QMessageBox::warning(this, tr("加载失败"),
                             QString::fromStdString(error));
        return;
    }
    (void)host()->apply_track_layout(restored);
    refresh();
}

void WellLogTrackPanel::on_export(const QString& suffix, const QString& filter) {
    if (host() == nullptr || !host_->has_document()) return;
    const QString path = QFileDialog::getSaveFileName(
        this, tr("导出测井图"), QStringLiteral("well_log.") + suffix, filter);
    if (path.isEmpty()) return;
    QString error;
    bool ok = false;
    if (suffix == QStringLiteral("png")) {
        ok = host()->export_png(path, &error);
    } else if (suffix == QStringLiteral("svg")) {
        ok = host()->export_svg(path, &error);
    } else {
        ok = host()->export_pdf(path, &error);
    }
    if (!ok) {
        QMessageBox::warning(this, tr("导出失败"), error);
    }
}
