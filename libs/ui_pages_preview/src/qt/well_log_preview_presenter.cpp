// 05 线 — well_log 预览页实现（见头注释的合同与降级口径）。

#include "pwb/ui_pages_preview/qt/well_log_preview_presenter.hpp"

#include <QPainter>
#include <QPainterPath>

#include <algorithm>
#include <cmath>
#include <limits>

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

}  // namespace

WellLogPreviewPage::WellLogPreviewPage(WellLogPreviewData data,
                                       QWidget* parent)
    : QWidget(parent), data_(std::move(data)) {
    setMinimumSize(320, 240);
}

void WellLogPreviewPage::set_data(WellLogPreviewData data) {
    data_ = std::move(data);
    update();
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

void WellLogPreviewPage::paintEvent(QPaintEvent* /*event*/) {
    QPainter painter(this);
    painter.fillRect(rect(), QColor(0xFA, 0xFA, 0xF7));

    // 诚实降级：诊断状态（解析失败/引擎不可用）优先呈现。
    if (!data_.diagnostic.empty()) {
        painter.setPen(QColor(0x8A, 0x1C, 0x1C));
        painter.drawText(rect(), Qt::AlignCenter,
                         QStringLiteral("测井预览不可用\n%1")
                             .arg(QString::fromStdString(data_.diagnostic)));
        return;
    }
    if (data_.curves.empty() || data_.sample_count < 2) {
        painter.setPen(QColor(0x33, 0x33, 0x33));
        painter.drawText(rect(), Qt::AlignCenter,
                         QStringLiteral("测井预览无数据（%1）")
                             .arg(summary_line()));
        return;
    }

    const int margin_left = 56;
    const int margin_top = 28;
    const int margin_bottom = 34;
    const int margin_right = 10;
    const QRect plot = rect().adjusted(margin_left, margin_top, -margin_right,
                                       -margin_bottom);
    if (plot.width() < 40 || plot.height() < 40) return;

    double depth_lo = data_.top_depth;
    double depth_hi = data_.bottom_depth;
    if (!finite(depth_lo) || !finite(depth_hi) || depth_lo > depth_hi) {
        depth_lo = depth_hi = 0.0;
    }
    const double depth_span = depth_hi - depth_lo;

    const int drawn = static_cast<int>(
        std::min<std::size_t>(data_.curves.size(), kMaxDrawnCurves));
    const double column_w =
        static_cast<double>(plot.width()) / static_cast<double>(drawn);

    // 深度标尺（左侧，5 刻度）。
    painter.setPen(QColor(0x44, 0x44, 0x44));
    for (int i = 0; i <= 4; ++i) {
        const double depth = depth_lo + depth_span * i / 4.0;
        const int y = plot.top() +
                      static_cast<int>(static_cast<double>(plot.height()) *
                                       static_cast<double>(i) / 4.0);
        painter.drawLine(plot.left() - 4, y, plot.left(), y);
        painter.drawText(QRect(0, y - 8, plot.left() - 6, 16),
                         Qt::AlignRight | Qt::AlignVCenter,
                         QStringLiteral("%1").arg(depth, 0, 'f', 1));
    }
    painter.drawText(QRect(0, plot.bottom() + 4, plot.left() + 40, 16),
                     Qt::AlignRight,
                     QStringLiteral("深度/%1")
                         .arg(data_.depth_unit.empty()
                                  ? QStringLiteral("未声明")
                                  : QString::fromStdString(data_.depth_unit)));

    static const QColor kColors[kMaxDrawnCurves] = {
        QColor(0x1d, 0x4e, 0xd8), QColor(0x15, 0x80, 0x3d),
        QColor(0x7c, 0x3a, 0xed), QColor(0xc2, 0x41, 0x0c),
        QColor(0x02, 0x84, 0xc7), QColor(0xb9, 0x1c, 0x1c),
        QColor(0x4d, 0x7c, 0x0f), QColor(0x6d, 0x28, 0xd9),
    };

    for (int c = 0; c < drawn; ++c) {
        const WellLogPreviewCurve& curve = data_.curves[static_cast<std::size_t>(c)];
        const QRect column(plot.left() +
                               static_cast<int>(column_w * c) + 2,
                           plot.top(),
                           std::max(8, static_cast<int>(column_w) - 4),
                           plot.height());
        // 值域：display_range 优先，否则有限值范围，再否则 (0,1)。
        std::optional<std::pair<double, double>> range =
            curve.display_range.has_value()
                ? curve.display_range
                : (curve.values != nullptr ? finite_range(*curve.values)
                                           : std::nullopt);
        if (!range.has_value()) range = std::pair{0.0, 1.0};
        double v_lo = std::min(range->first, range->second);
        double v_hi = std::max(range->first, range->second);
        if (!(v_hi > v_lo)) v_hi = v_lo + 1.0;

        // 逐列 min-max 压缩（渲染 glue）：NaN 样本断列。
        const std::size_t n =
            curve.depth != nullptr && curve.values != nullptr
                ? std::min(curve.depth->size(), curve.values->size())
                : 0;
        QPainterPath path;
        bool pen_down = false;
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
                pen_down = false;  // 缺测段 → 断口
                continue;
            }
            const double x = static_cast<double>(column.left()) +
                             static_cast<double>(column.width()) *
                                 (static_cast<double>(px) + 0.5) /
                                 static_cast<double>(kDownsampleColumns);
            auto to_y = [&](double v) {
                return static_cast<double>(column.bottom()) -
                       (v - v_lo) / (v_hi - v_lo) *
                           static_cast<double>(column.height());
            };
            if (!pen_down) {
                path.moveTo(x, to_y(v_min));
                pen_down = true;
            } else {
                path.lineTo(x, to_y(v_min));
            }
            path.lineTo(x, to_y(v_max));
        }
        painter.setPen(QPen(kColors[c], 1.2));
        painter.drawPath(path);

        // 列头：曲线名 + 单位。
        painter.setPen(QColor(0x22, 0x22, 0x22));
        const QString label =
            QString::fromStdString(curve.name) +
            (curve.unit.empty()
                 ? QString()
                 : QStringLiteral("\n%1").arg(
                       QString::fromStdString(curve.unit)));
        painter.drawText(QRect(column.left(), 2, column.width(), 24),
                         Qt::AlignHCenter | Qt::AlignVCenter, label);
    }

    if (data_.curves.size() > static_cast<std::size_t>(kMaxDrawnCurves)) {
        painter.setPen(QColor(0x66, 0x66, 0x66));
        painter.drawText(rect().adjusted(0, 0, -6, -4),
                         Qt::AlignRight | Qt::AlignBottom,
                         QStringLiteral("+%1 条未渲染")
                             .arg(static_cast<int>(data_.curves.size()) -
                                  kMaxDrawnCurves));
    }

    painter.setPen(QColor(0x33, 0x33, 0x33));
    painter.drawText(rect().adjusted(0, 0, -6, -2), Qt::AlignLeft |
                                                        Qt::AlignBottom,
                     summary_line());
}

}  // namespace pwb::ui_pages_preview::qt
