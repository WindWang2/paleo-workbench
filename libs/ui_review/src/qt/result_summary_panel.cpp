#include "pwb/ui_review/qt/result_summary_panel.hpp"

#include "pwb/ui_pages_data/qc_summary.hpp"
#include "pwb/ui_review/tokens.hpp"

#include <QFrame>
#include <QLabel>
#include <QVBoxLayout>

namespace pwb::ui_review::qt {

namespace {

// token name ("SUCCESS"/"ERROR_RED"/...) → palette hex literal.
const char* token_hex(const std::string& token) {
    if (token == "SUCCESS") {
        return tokens::kSuccess.data();
    }
    if (token == "ERROR_RED") {
        return tokens::kErrorRed.data();
    }
    if (token == "WARNING") {
        return tokens::kWarning.data();
    }
    if (token == "TEXT_PRIMARY") {
        return tokens::kTextPrimary.data();
    }
    return tokens::kTextSecondary.data();
}

void color_label(QLabel* label, const std::string& token) {
    label->setStyleSheet(
        QStringLiteral(
            "color: %1; font-size: 13px; border: none;"
            " background: transparent;")
            .arg(QString::fromLatin1(token_hex(token))));
}

}  // namespace

ResultSummaryPanel::ResultSummaryPanel(QWidget* parent)
    : QFrame(parent) {
    setObjectName(QStringLiteral("PanelCard"));
    // 侧栏宽度：保底 240，窄屏下可收缩、宽屏最多 1.6 倍有界弹性
    setMinimumWidth(240);
    setMaximumWidth(int(240 * 1.6));

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(tokens::kPanelPadding,
                               tokens::kPanelPadding,
                               tokens::kPanelPadding,
                               tokens::kPanelPadding);
    layout->setSpacing(tokens::kSpace2);

    auto* title_label =
        new QLabel(QStringLiteral("检查结果输出"), this);
    title_label->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title_label);

    pass_label_ = new QLabel(QStringLiteral("通过项: 0"), this);
    color_label(pass_label_, "SUCCESS");
    layout->addWidget(pass_label_);
    warning_label_ = new QLabel(QStringLiteral("警告项: 0"), this);
    color_label(warning_label_, "WARNING");
    layout->addWidget(warning_label_);
    error_label_ = new QLabel(QStringLiteral("待处理项: 0"), this);
    color_label(error_label_, "ERROR_RED");
    layout->addWidget(error_label_);
    advisory_label_ =
        new QLabel(QStringLiteral("全部通过，可输出成果"), this);
    color_label(advisory_label_, "SUCCESS");
    layout->addWidget(advisory_label_);

    auto* divider = new QFrame(this);
    divider->setFrameShape(QFrame::HLine);
    divider->setStyleSheet(QStringLiteral(
        "background: %1; border: none; max-height: 1px;")
            .arg(QString::fromUtf8(tokens::kBorder.data(),
                                   int(tokens::kBorder.size()))));
    layout->addWidget(divider);

    auto* export_title = new QLabel(QStringLiteral("导出图件"), this);
    export_title->setStyleSheet(QStringLiteral(
        "color: %1; font-size: 14px; font-weight: 600; border: none;"
        " background: transparent;")
            .arg(QString::fromUtf8(tokens::kTextPrimary.data(),
                                   int(tokens::kTextPrimary.size()))));
    layout->addWidget(export_title);

    export_container_ = new QWidget(this);
    export_layout_ = new QVBoxLayout(export_container_);
    export_layout_->setContentsMargins(0, 0, 0, 0);
    export_layout_->setSpacing(tokens::kSpace1);
    layout->addWidget(export_container_);
    layout->addStretch();

    update_state(domain::Json::array(), domain::Json::array());
}

void ResultSummaryPanel::clear_export() {
    while (export_layout_->count()) {
        QLayoutItem* item = export_layout_->takeAt(0);
        if (QWidget* w = item->widget()) {
            w->hide();
            w->setParent(nullptr);
            w->deleteLater();
        }
        delete item;
    }
    export_rows_.clear();
}

void ResultSummaryPanel::update_state(const domain::Json& reports,
                                      const domain::Json& artifacts) {
    const ui_pages_data::QcSummary summary =
        ui_pages_data::summarize_qc(reports, artifacts);

    pass_label_->setText(
        QStringLiteral("通过项: %1").arg(summary.pass_count));
    warning_label_->setText(
        QStringLiteral("警告项: %1").arg(summary.warning_count));
    error_label_->setText(
        QStringLiteral("待处理项: %1").arg(summary.error_count));
    advisory_label_->setText(QString::fromStdString(summary.advisory));
    color_label(advisory_label_, summary.advisory_token);

    clear_export();
    if (summary.export_rows.empty()) {
        auto* empty = new QLabel(QStringLiteral("暂无导出图件"),
                                 export_container_);
        empty->setObjectName(QStringLiteral("EmptyStateLabel"));
        export_layout_->addWidget(empty);
        export_rows_.push_back(empty);
    } else {
        for (const std::string& row_text : summary.export_rows) {
            auto* row = new QLabel(QString::fromStdString(row_text),
                                   export_container_);
            color_label(row, "TEXT_PRIMARY");
            export_layout_->addWidget(row);
            export_rows_.push_back(row);
        }
    }
}

}  // namespace pwb::ui_review::qt
