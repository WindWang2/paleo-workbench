// 05 线 — time_depth 预览页实现（见头注释的合同与探针口径）。
//
// QGIS-PLOT migration: the hand-painted QPainter chart is replaced by a
// PwbPlotCanvas + PwbScatterPlot (line for the calibration curve, markers +
// value labels for the probe). Navigation/export/axes come from QGIS Plot;
// this page only binds domain data (MD/TWT pairs + injected probe).

#include "pwb/ui_pages_preview/qt/time_depth_preview_presenter.hpp"

#include <QLabel>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>
#include <limits>

#include <qgsplot.h>

#include <pwb/qgis_plot/domain_plots.hpp>
#include <pwb/qgis_plot/plot_canvas.hpp>
#include <pwb/qgis_plot/plot_item.hpp>
#include <pwb/qgis_plot/series_binding.hpp>

namespace pwb::ui_pages_preview::qt {

namespace {

bool finite(double v) { return std::isfinite(v); }

}  // namespace

TimeDepthPreviewPage::TimeDepthPreviewPage(TimeDepthPreviewData data,
                                           QWidget* parent)
    : QWidget(parent), data_(std::move(data)) {
    setMinimumSize(320, 240);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    canvas_ = new pwb::qgis_plot::PwbPlotCanvas(this);
    auto scatter = std::make_unique<pwb::qgis_plot::PwbScatterPlot>();
    plot_ = scatter.get();
    canvas_->addPlot(std::move(scatter));
    layout->addWidget(canvas_, 1);

    summary_label_ = new QLabel(this);
    summary_label_->setStyleSheet(QStringLiteral("color: #333;"));
    layout->addWidget(summary_label_);

    message_label_ = new QLabel(this);
    message_label_->setAlignment(Qt::AlignCenter);
    message_label_->setWordWrap(true);
    message_label_->hide();
    layout->addWidget(message_label_, 1);

    rebuild();
}

void TimeDepthPreviewPage::set_data(TimeDepthPreviewData data) {
    data_ = std::move(data);
    rebuild();
}

void TimeDepthPreviewPage::set_probe(
    std::function<double(double)> md_to_twt) {
    probe_ = std::move(md_to_twt);
    rebuild();
}

QString TimeDepthPreviewPage::summary_line() const {
    if (!data_.diagnostic.empty()) {
        return QString::fromStdString(data_.diagnostic);
    }
    return QStringLiteral("%1 ｜ %2 对（MD/TWT） ｜ 来源: %3")
        .arg(data_.well_name.empty()
                 ? QStringLiteral("（多井表）")
                 : QString::fromStdString(data_.well_name))
        .arg(static_cast<int>(data_.pairs.size()))
        .arg(QString::fromStdString(data_.source));
}

void TimeDepthPreviewPage::rebuild() {
    summary_label_->setText(summary_line());

    // Honest degradation: diagnostic / too-few-pairs states show the reason.
    if (!data_.diagnostic.empty()) {
        message_label_->setText(QStringLiteral("时深预览不可用\n%1")
                                    .arg(QString::fromStdString(
                                        data_.diagnostic)));
        message_label_->setStyleSheet(QStringLiteral("color: #8A1C1C;"));
        message_label_->show();
        canvas_->hide();
        return;
    }
    if (data_.pairs.size() < 2) {
        message_label_->setText(QStringLiteral("时深表无数据（至少需要 2 对）\n%1")
                                    .arg(summary_line()));
        message_label_->setStyleSheet(QStringLiteral("color: #333;"));
        message_label_->show();
        canvas_->hide();
        return;
    }
    message_label_->hide();
    canvas_->show();

    double md_lo = std::numeric_limits<double>::infinity();
    double md_hi = -std::numeric_limits<double>::infinity();
    QList<std::pair<double, double>> line_pts;
    for (const auto& [md, twt] : data_.pairs) {
        if (!finite(md) || !finite(twt)) continue;  // NaN pair -> line break
        line_pts.append({md, twt});
        md_lo = std::min(md_lo, md);
        md_hi = std::max(md_hi, md);
    }
    if (!(md_hi > md_lo)) md_hi = md_lo + 1.0;

    QgsPlotData plot_data;
    auto* line = new QgsXyPlotSeries();
    line->setName(QStringLiteral("calibration"));
    line->setData(line_pts);
    plot_data.addSeries(line);

    // Calibration probe: 5 equidistant MD samples through the authoritative
    // injected kernel; absent probe -> no marker series (honest absence).
    QStringList probe_labels;
    if (probe_ != nullptr) {
        auto* probe = new QgsXyPlotSeries();
        probe->setName(QStringLiteral("probe"));
        QList<std::pair<double, double>> probe_pts;
        for (int i = 0; i <= 4; ++i) {
            const double md = md_lo + (md_hi - md_lo) * i / 4.0;
            const double twt = probe_(md);
            if (!finite(twt)) continue;
            probe_pts.append({md, twt});
            probe_labels.append(
                QStringLiteral("%1 ms").arg(twt, 0, 'f', 1));
        }
        probe->setData(probe_pts);
        plot_data.addSeries(probe);
    }

    auto* item = canvas_->plotItems().value(0);
    item->setPlotData(std::move(plot_data));
    item->setAxisTitles(QStringLiteral("MD / m"), QStringLiteral("TWT / ms"));
    plot_->setSeriesColors({QColor(0x1d, 0x4e, 0xd8), QColor(0xc2, 0x41, 0x0c)});
    plot_->setSeriesLine(0, true, 1.6);
    plot_->setSeriesMarkers(0, false);
    plot_->setPointLabels(0, {});
    if (item->plotData().series().size() > 1)
        plot_->setPointLabels(1, probe_labels);
    else
        plot_->setPointLabels(1, {});

    pwb::qgis_plot::SeriesBinding binding;
    binding.series_id = QStringLiteral("time_depth_calibration");
    binding.well_id = QString::fromStdString(data_.well_name);
    binding.axis_role = QStringLiteral("time-depth");
    binding.style_role = QStringLiteral("line");
    binding.unit = QStringLiteral("ms");
    canvas_->setSeriesBindings(0, {binding});

    canvas_->zoomFull();
}

}  // namespace pwb::ui_pages_preview::qt
