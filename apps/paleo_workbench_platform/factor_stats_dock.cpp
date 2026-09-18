#include "factor_stats_dock.hpp"

#include <QFormLayout>
#include <QLabel>
#include <QWidget>

#include <cmath>

namespace pwb::app {
namespace {

// Python ":g" (%g, precision 6): the workstation inspector formats the
// factor grid rows with f"{v:g}" (tests/test_inspector_v7.py pins
// "10 ~ 220.5" / "0.5 ~ 3.25"), so the dock speaks the same vocabulary.
QString format_g(double value) {
    return QString::number(value, 'g', 6);
}

QString dash_if_nan(double value) {
    return std::isfinite(value) ? format_g(value) : QStringLiteral("—");
}

}  // namespace

FactorStatsDock::FactorStatsDock(QWidget* parent)
    : QDockWidget(QStringLiteral("单因素统计"), parent) {
    setObjectName(QStringLiteral("factor-stats-dock"));
    // Read-only HUD: no closable chrome fighting the layout, no floating
    // features beyond the dock default; the user inspects, never edits.
    setFeatures(QDockWidget::DockWidgetMovable | QDockWidget::DockWidgetFloatable);

    auto* body = new QWidget(this);
    auto* form = new QFormLayout(body);
    form->setContentsMargins(8, 8, 8, 8);
    form->setSpacing(4);

    auto add_row = [&](const QString& key, QLabel** slot) {
        auto* label = new QLabel(QStringLiteral("—"), body);
        label->setTextInteractionFlags(Qt::TextSelectableByMouse);
        form->addRow(key, label);
        *slot = label;
        rows_[key] = label;
    };
    add_row(QStringLiteral("因素"), &factor_label_);
    add_row(QStringLiteral("取值范围"), &range_label_);
    add_row(QStringLiteral("均值"), &mean_label_);
    add_row(QStringLiteral("标准差"), &std_label_);
    add_row(QStringLiteral("有效格元"), &valid_label_);

    setWidget(body);
}

void FactorStatsDock::setStatistics(const QString& factor_name,
                                    const pwb::mapping::GridStatistics& stats) {
    factor_label_->setText(factor_name.isEmpty() ? QStringLiteral("—")
                                                 : factor_name);
    const bool has_range = std::isfinite(stats.min) && std::isfinite(stats.max) &&
                           stats.valid_count > 0;
    range_label_->setText(has_range ? QStringLiteral("%1 ~ %2")
                                          .arg(format_g(stats.min),
                                               format_g(stats.max))
                                    : QStringLiteral("—"));
    mean_label_->setText(dash_if_nan(stats.mean));
    std_label_->setText(dash_if_nan(stats.std));
    valid_label_->setText(QStringLiteral("%1 / %2")
                              .arg(stats.valid_count)
                              .arg(stats.total_count));
}

QString FactorStatsDock::rowValue(const QString& key) const {
    const auto it = rows_.find(key);
    return it == rows_.end() ? QString() : it->second->text();
}

}  // namespace pwb::app
