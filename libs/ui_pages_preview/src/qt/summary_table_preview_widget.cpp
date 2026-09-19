#include <pwb/ui_pages_preview/qt/summary_table_preview_widget.hpp>

#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QSplitter>
#include <QTabWidget>
#include <QVBoxLayout>

#include <algorithm>

#include <pwb/ui_pages_preview/preview_settings.hpp>
#include <pwb/ui_pages_preview/summary_chips.hpp>

#include "../qt/style_util.hpp"

namespace pwb::ui_pages_preview {

namespace {

QString message_qss() {
    return QStringLiteral("color: %1; font-size: 11.5px;")
        .arg(qt_internal::token("TEXT_SECONDARY"));
}

}  // namespace

SummaryTablePreviewWidget::SummaryTablePreviewWidget(QWidget* parent)
    : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(qt_internal::SPACE_2);

    message_label_ = new QLabel(QString());
    message_label_->setWordWrap(true);
    message_label_->setStyleSheet(message_qss());
    layout->addWidget(message_label_);

    // Tabs inherit their styling from the global QSS (tokens.build_qss).
    tabs_ = new QTabWidget(this);

    // Tab 1: Curve definitions and metadata summary
    info_tab_ = new QWidget();
    auto* info_layout = new QVBoxLayout(info_tab_);
    info_layout->setContentsMargins(qt_internal::SPACE_2, qt_internal::SPACE_2,
                                    qt_internal::SPACE_2, qt_internal::SPACE_2);
    info_layout->setSpacing(qt_internal::SPACE_2);

    // Stat cards bar
    stat_bar_ = new QWidget();
    auto* stat_layout = new QHBoxLayout(stat_bar_);
    stat_layout->setContentsMargins(2, 2, 2, 4);
    stat_layout->setSpacing(8);

    chip_well_ = create_stat_chip(QStringLiteral("◆ 井名"),
                                  QStringLiteral("—"), "PRIMARY",
                                  "BG_SELECTION");
    chip_curves_ = create_stat_chip(QStringLiteral("▤ 曲线数"),
                                    QStringLiteral("0 条"), "TEAL",
                                    "BG_SEARCH");
    chip_samples_ = create_stat_chip(QStringLiteral("◌ 采样点"),
                                     QStringLiteral("0 点"), "SUCCESS",
                                     "BG_SEARCH");

    stat_layout->addWidget(chip_well_);
    stat_layout->addWidget(chip_curves_);
    stat_layout->addWidget(chip_samples_);
    stat_layout->addStretch();

    info_layout->addWidget(stat_bar_);

    summary_table_ = new TablePreviewWidget();
    detail_table_ = new TablePreviewWidget();

    // 元数据表与曲线定义表之间用可拖动分隔条：默认元数据表贴合内容高度，
    // 剩余空间给曲线表；用户可上下拉动调整。
    info_splitter_ = new QSplitter(Qt::Vertical);
    info_splitter_->setChildrenCollapsible(false);
    info_splitter_->addWidget(summary_table_);
    info_splitter_->addWidget(detail_table_);
    info_splitter_->setStretchFactor(0, 0);
    info_splitter_->setStretchFactor(1, 1);

    info_layout->addWidget(info_splitter_, 1);

    tabs_->addTab(info_tab_, QStringLiteral("曲线定义与元数据"));

    // Tab 2: Curve data rows preview
    data_tab_ = new QWidget();
    auto* data_layout = new QVBoxLayout(data_tab_);
    data_layout->setContentsMargins(qt_internal::SPACE_2, qt_internal::SPACE_2,
                                    qt_internal::SPACE_2, qt_internal::SPACE_2);
    data_layout->setSpacing(qt_internal::SPACE_2);

    data_table_ = new TablePreviewWidget();
    data_layout->addWidget(data_table_, 1);

    tabs_->addTab(data_tab_, QStringLiteral("数据内容"));

    layout->addWidget(tabs_, 1);
}

QWidget* SummaryTablePreviewWidget::create_stat_chip(
    const QString& title, const QString& default_val,
    const QString& fg_token, const QString& bg_token) {
    const QString fg = qt_internal::token(fg_token.toStdString());
    const QString bg = qt_internal::token(bg_token.toStdString());
    auto* box = new QWidget();
    box->setStyleSheet(QStringLiteral(
        "QWidget { background-color: %1; border: 1px solid %2;"
        " border-radius: %3px; }")
                           .arg(bg, fg + QStringLiteral("33"))
                           .arg(qt_internal::RADIUS_BUTTON));
    auto* lay = new QHBoxLayout(box);
    lay->setContentsMargins(8, 4, 10, 4);
    lay->setSpacing(6);

    auto* t_lbl = new QLabel(title);
    t_lbl->setStyleSheet(QStringLiteral(
        "color: %1; font-size: 11px; font-weight: 500;").arg(fg));
    auto* val_lbl = new QLabel(default_val);
    val_lbl->setObjectName(QStringLiteral("chip_val"));
    val_lbl->setStyleSheet(QStringLiteral(
        "color: %1; font-size: 12px; font-weight: 700;").arg(fg));

    lay->addWidget(t_lbl);
    lay->addWidget(val_lbl);
    return box;
}

void SummaryTablePreviewWidget::update_chip_val(QWidget* chip,
                                                const QString& text) {
    if (QLabel* lbl = chip->findChild<QLabel*>(QStringLiteral("chip_val"))) {
        lbl->setText(text);
    }
}

void SummaryTablePreviewWidget::adjust_summary_height() {
    int total = summary_table_->horizontalHeader()->height();
    if (total == 0) {
        total = 28;
    }
    for (int row = 0; row < summary_table_->rowCount(); ++row) {
        total += summary_table_->rowHeight(row);
    }
    total += 6;
    // 仅约束下限并让分隔条接管初始分配：内容少时表贴合内容，
    // 内容多时可被用户拉大查看全部属性行。
    summary_table_->setMinimumHeight(std::min(std::max(total, 60), 120));
    info_splitter_->setSizes({summary_table_->minimumHeight(), 10000});
}

void SummaryTablePreviewWidget::load_summary(
    const std::vector<std::pair<std::string, std::string>>& summary_rows,
    const std::vector<std::string>& detail_headers,
    const std::vector<std::vector<std::string>>& detail_rows,
    const QString& message,
    const std::vector<std::string>& data_headers,
    const std::vector<std::vector<std::string>>& data_rows) {
    message_label_->setText(message);
    std::vector<std::vector<std::string>> summary_table_rows;
    summary_table_rows.reserve(summary_rows.size());
    for (const auto& [k, v] : summary_rows) {
        summary_table_rows.push_back({k, v});
    }
    summary_table_->load_table(std::vector<std::string>{"属性", "值"},
                               summary_table_rows);
    adjust_summary_height();

    // Update stat chips from summary rows — sticky: absent keys leave the
    // previous chip text (Python writes a chip only when its key is seen).
    const SummaryChipValues chips = summary_chip_values(summary_rows);
    if (chips.well) {
        update_chip_val(chip_well_, QString::fromStdString(*chips.well));
    }
    if (chips.curves) {
        update_chip_val(chip_curves_, QString::fromStdString(*chips.curves));
    }
    if (chips.samples) {
        update_chip_val(chip_samples_, QString::fromStdString(*chips.samples));
    }

    detail_table_->load_table(detail_headers, detail_rows);

    if (!data_headers.empty() && !data_rows.empty()) {
        data_table_->load_table(data_headers, data_rows);
        tabs_->setTabEnabled(1, true);
        tabs_->setCurrentIndex(0);
    } else {
        data_table_->load_table(std::vector<std::string>{""}, {});
        tabs_->setTabEnabled(1, false);
        tabs_->setCurrentIndex(0);
    }
}

void SummaryTablePreviewWidget::apply_settings(const PreviewSettings& settings) {
    QFont font = this->font();
    font.setPointSize(settings.font_size);
    setFont(font);
    summary_table_->apply_settings(settings);
    detail_table_->apply_settings(settings);
    data_table_->apply_settings(settings);
}

}  // namespace pwb::ui_pages_preview
