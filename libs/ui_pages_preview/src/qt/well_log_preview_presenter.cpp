// 05 线 — well_log 预览页实现（见头注释的合同与降级口径）。
//
// QGIS-PLOT migration: the hand-painted per-column min-max compression moves
// onto PwbPlotCanvas — one PwbRangeBandPlot item per curve (shared bucket
// X axis, independent value Y axis per track). Axes/grid/pan/zoom come from
// QGIS Plot; this page only supplies the min-max bucket glue (unchanged
// 480-column budget) and domain binding.

#include "pwb/ui_pages_preview/qt/well_log_preview_presenter.hpp"

#include <QLabel>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

#include <qgsplot.h>

#include <pwb/qgis_plot/domain_plots.hpp>
#include <pwb/qgis_plot/plot_canvas.hpp>
#include <pwb/qgis_plot/plot_item.hpp>
#include <pwb/qgis_plot/series_binding.hpp>

namespace pwb::ui_pages_preview::qt {

namespace {

constexpr int kMaxDrawnCurves = 8;
constexpr int kDownsampleColumns = 480;  // 绘制列预算（与画布宽度解耦）

bool finite(double v) { return std::isfinite(v); }

// 数值域（有限值；无 → nullopt）。
std::optional<std::pair<double, double>> finite_range(
    const std::vector<double>& v) {
    double lo = std::numeric_limits<double>::infinity();
    double hi = -std::numeric_limits<double>::infinity();
    for (double x : v) {
        if (!finite(x)) continue;
        lo = std::min(lo, x);
        hi = std::max(hi, x);
    }
    if (lo > hi) return std::nullopt;
    return std::pair{lo, hi};
}

const QColor kColors[kMaxDrawnCurves] = {
    QColor(0x1d, 0x4e, 0xd8), QColor(0x15, 0x80, 0x3d),
    QColor(0x7c, 0x3a, 0xed), QColor(0xc2, 0x41, 0x0c),
    QColor(0x02, 0x84, 0xc7), QColor(0xb9, 0x1c, 0x1c),
    QColor(0x4d, 0x7c, 0x0f), QColor(0x6d, 0x28, 0xd9),
};

}  // namespace

WellLogPreviewPage::WellLogPreviewPage(WellLogPreviewData data,
                                       QWidget* parent)
    : QWidget(parent), data_(std::move(data)) {
    setMinimumSize(320, 240);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    canvas_ = new pwb::qgis_plot::PwbPlotCanvas(this);
    canvas_->setColumnGutter(2);
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

void WellLogPreviewPage::set_data(WellLogPreviewData data) {
    data_ = std::move(data);
    rebuild();
}

QString WellLogPreviewPage::summary_line() const {
    if (!data_.diagnostic.empty()) {
        return QString::fromStdString(data_.diagnostic);
    }
    const QString unit = data_.depth_unit.empty()
                             ? QStringLiteral("未声明")
                             : QString::fromStdString(data_.depth_unit);
    return QStringLiteral("%1 ｜ %2 条曲线 ｜ %3 采样 ｜ 深度 %4–%5 %6 ｜ 来源: %7")
        .arg(QString::fromStdString(data_.well_name))
        .arg(static_cast<int>(data_.curves.size()))
        .arg(static_cast<qulonglong>(data_.sample_count))
        .arg(data_.top_depth)
        .arg(data_.bottom_depth)
        .arg(unit)
        .arg(QString::fromStdString(data_.source));
}

void WellLogPreviewPage::rebuild() {
    QString summary = summary_line();
    if (data_.curves.size() > static_cast<std::size_t>(kMaxDrawnCurves)) {
        summary += QStringLiteral(" ｜ +%1 条未渲染")
                       .arg(static_cast<int>(data_.curves.size()) -
                            kMaxDrawnCurves);
    }
    summary_label_->setText(summary);

    canvas_->clearPlots();

    // 诚实降级：诊断状态（解析失败/引擎不可用）优先呈现。
    if (!data_.diagnostic.empty()) {
        message_label_->setText(QStringLiteral("测井预览不可用\n%1")
                                    .arg(QString::fromStdString(
                                        data_.diagnostic)));
        message_label_->setStyleSheet(QStringLiteral("color: #8A1C1C;"));
        message_label_->show();
        canvas_->hide();
        return;
    }
    if (data_.curves.empty() || data_.sample_count < 2) {
        message_label_->setText(
            QStringLiteral("测井预览无数据（%1）").arg(summary_line()));
        message_label_->setStyleSheet(QStringLiteral("color: #333;"));
        message_label_->show();
        canvas_->hide();
        return;
    }
    message_label_->hide();
    canvas_->show();

    // 纵轴是每列自己的值轴（P2-12：曲线 Y 编码曲线值，不是共享深度），
    // 深度包络只在摘要行陈述。共享 X 是 bucket 序号（渲染 glue 的内部
    // 轴）——隐藏其标签，只留每列值轴刻度。
    const int drawn = static_cast<int>(
        std::min<std::size_t>(data_.curves.size(), kMaxDrawnCurves));

    // 列值轴范围：优先 display_range，否则数据有限值范围。
    auto y_range_of = [](const WellLogPreviewCurve& curve) {
        std::optional<std::pair<double, double>> range =
            curve.display_range.has_value()
                ? curve.display_range
                : (curve.values != nullptr ? finite_range(*curve.values)
                                           : std::nullopt);
        if (!range.has_value()) range = std::pair{0.0, 1.0};
        double lo = std::min(range->first, range->second);
        double hi = std::max(range->first, range->second);
        if (!(hi > lo)) hi = lo + 1.0;
        return std::pair{lo, hi};
    };

    for (int c = 0; c < drawn; ++c) {
        const WellLogPreviewCurve& curve =
            data_.curves[static_cast<std::size_t>(c)];
        const auto [v_lo, v_hi] = y_range_of(curve);

        // 逐列 min-max 压缩（与旧绘制的桶数一致：kDownsampleColumns）。
        // NaN 桶段在两条边界序列里都留空 → PwbRangeBandPlot 断带。
        const std::size_t n =
            curve.depth != nullptr && curve.values != nullptr
                ? std::min(curve.depth->size(), curve.values->size())
                : 0;
        QList<std::pair<double, double>> lo_pts;
        QList<std::pair<double, double>> hi_pts;
        lo_pts.reserve(kDownsampleColumns);
        hi_pts.reserve(kDownsampleColumns);
        for (int px = 0; px < kDownsampleColumns; ++px) {
            const std::size_t begin = n * static_cast<std::size_t>(px) /
                                      kDownsampleColumns;
            const std::size_t end = n * (static_cast<std::size_t>(px) + 1) /
                                    kDownsampleColumns;
            double v_min = std::numeric_limits<double>::infinity();
            double v_max = -std::numeric_limits<double>::infinity();
            std::size_t seen = 0;
            for (std::size_t i = begin; i < end && i < n; ++i) {
                const double v = (*curve.values)[i];
                if (!finite(v)) continue;
                v_min = std::min(v_min, v);
                v_max = std::max(v_max, v);
                ++seen;
            }
            if (seen == 0) {
                lo_pts.append({static_cast<double>(px),
                               std::numeric_limits<double>::quiet_NaN()});
                hi_pts.append({static_cast<double>(px),
                               std::numeric_limits<double>::quiet_NaN()});
                continue;
            }
            lo_pts.append({static_cast<double>(px), v_min});
            hi_pts.append({static_cast<double>(px), v_max});
        }

        auto band = std::make_unique<pwb::qgis_plot::PwbRangeBandPlot>();
        band->setBandColor(kColors[c]);
        // Hide the internal bucket axis (categorical with no categories
        // renders neither labels nor grid); keep the value axis ticks.
        band->xAxis().setType(Qgis::PlotAxisType::Categorical);
        auto* item = canvas_->addPlot(std::move(band));
        item->setShareY(false);  // value axis is per-track

        QgsPlotData plot_data;
        auto* lo = new QgsXyPlotSeries();
        lo->setName(QStringLiteral("min"));
        lo->setData(lo_pts);
        auto* hi = new QgsXyPlotSeries();
        hi->setName(QStringLiteral("max"));
        hi->setData(hi_pts);
        plot_data.addSeries(lo);
        plot_data.addSeries(hi);
        item->setPlotData(std::move(plot_data));

        const QString header =
            QString::fromStdString(curve.name) +
            (curve.unit.empty()
                 ? QString()
                 : QStringLiteral("\n%1").arg(
                       QString::fromStdString(curve.unit)));
        item->setTopTitle(header);

        pwb::qgis_plot::SeriesBinding binding;
        binding.series_id = QStringLiteral("well_log_curve_%1").arg(c);
        binding.name = QString::fromStdString(curve.name);
        binding.well_id = QString::fromStdString(data_.well_name);
        binding.curve_id = QString::fromStdString(curve.name);
        binding.unit = QString::fromStdString(curve.unit);
        binding.axis_role = QStringLiteral("value");
        binding.style_role = QStringLiteral("band");
        canvas_->setSeriesBindings(c, {binding, binding});
    }

    canvas_->zoomFull();
    // zoomFull pads the shared bucket axis; restore the exact value ranges.
    for (int c = 0; c < drawn; ++c) {
        const auto [v_lo, v_hi] =
            y_range_of(data_.curves[static_cast<std::size_t>(c)]);
        canvas_->plotItems()[c]->setYRange(v_lo, v_hi);
    }
}

}  // namespace pwb::ui_pages_preview::qt
