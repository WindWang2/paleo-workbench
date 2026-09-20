// 05 线 — time_depth 预览页实现（见头注释的合同与探针口径）。

#include "pwb/ui_pages_preview/qt/time_depth_preview_presenter.hpp"

#include <QPainter>
#include <QPainterPath>

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::ui_pages_preview::qt {

namespace {

bool finite(double v) { return std::isfinite(v); }

}  // namespace

TimeDepthPreviewPage::TimeDepthPreviewPage(TimeDepthPreviewData data,
                                           QWidget* parent)
    : QWidget(parent), data_(std::move(data)) {
    setMinimumSize(320, 240);
}

void TimeDepthPreviewPage::set_data(TimeDepthPreviewData data) {
    data_ = std::move(data);
    update();
}

void TimeDepthPreviewPage::set_probe(
    std::function<double(double)> md_to_twt) {
    probe_ = std::move(md_to_twt);
    update();
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

void TimeDepthPreviewPage::paintEvent(QPaintEvent* /*event*/) {
    QPainter painter(this);
    painter.fillRect(rect(), QColor(0xFA, 0xFA, 0xF7));

    if (!data_.diagnostic.empty()) {
        painter.setPen(QColor(0x8A, 0x1C, 0x1C));
        painter.drawText(rect(), Qt::AlignCenter,
                         QStringLiteral("时深预览不可用\n%1")
                             .arg(QString::fromStdString(data_.diagnostic)));
        return;
    }
    if (data_.pairs.size() < 2) {
        painter.setPen(QColor(0x33, 0x33, 0x33));
        painter.drawText(rect(), Qt::AlignCenter,
                         QStringLiteral("时深表无数据（至少需要 2 对）\n%1")
                             .arg(summary_line()));
        return;
    }

    const QRect plot = rect().adjusted(56, 28, -12, -36);
    if (plot.width() < 40 || plot.height() < 40) return;

    double md_lo = std::numeric_limits<double>::infinity();
    double md_hi = -std::numeric_limits<double>::infinity();
    double twt_lo = std::numeric_limits<double>::infinity();
    double twt_hi = -std::numeric_limits<double>::infinity();
    for (const auto& [md, twt] : data_.pairs) {
        if (!finite(md) || !finite(twt)) continue;
        md_lo = std::min(md_lo, md);
        md_hi = std::max(md_hi, md);
        twt_lo = std::min(twt_lo, twt);
        twt_hi = std::max(twt_hi, twt);
    }
    if (!(md_hi > md_lo)) md_hi = md_lo + 1.0;
    if (!(twt_hi > twt_lo)) twt_hi = twt_lo + 1.0;

    // 轴：横 = MD（m），纵 = TWT（ms）。
    painter.setPen(QColor(0x44, 0x44, 0x44));
    for (int i = 0; i <= 4; ++i) {
        const double md = md_lo + (md_hi - md_lo) * i / 4.0;
        const double twt = twt_lo + (twt_hi - twt_lo) * i / 4.0;
        const int x = plot.left() +
                      static_cast<int>(static_cast<double>(plot.width()) *
                                       static_cast<double>(i) / 4.0);
        const int y = plot.top() +
                      static_cast<int>(static_cast<double>(plot.height()) *
                                       (1.0 - static_cast<double>(i) / 4.0));
        painter.drawLine(x, plot.bottom(), x, plot.bottom() + 4);
        painter.drawText(QRect(x - 30, plot.bottom() + 6, 60, 16),
                         Qt::AlignCenter, QStringLiteral("%1").arg(md, 0, 'f', 0));
        painter.drawLine(plot.left() - 4, y, plot.left(), y);
        painter.drawText(QRect(0, y - 8, plot.left() - 6, 16),
                         Qt::AlignRight | Qt::AlignVCenter,
                         QStringLiteral("%1").arg(twt, 0, 'f', 0));
    }
    painter.drawText(QRect(plot.left(), plot.bottom() + 20, plot.width(), 16),
                     Qt::AlignCenter, QStringLiteral("MD / m"));
    painter.save();
    painter.translate(12, plot.center().y());
    painter.rotate(-90);
    painter.drawText(QRect(-80, -40, 160, 16), Qt::AlignCenter,
                     QStringLiteral("TWT / ms"));
    painter.restore();

    auto to_x = [&](double md) {
        return static_cast<double>(plot.left()) +
               (md - md_lo) / (md_hi - md_lo) *
                   static_cast<double>(plot.width());
    };
    auto to_y = [&](double twt) {
        return static_cast<double>(plot.bottom()) -
               (twt - twt_lo) / (twt_hi - twt_lo) *
                   static_cast<double>(plot.height());
    };

    // 校准折线（跳过非有限对）。
    QPainterPath path;
    bool pen_down = false;
    for (const auto& [md, twt] : data_.pairs) {
        if (!finite(md) || !finite(twt)) {
            pen_down = false;
            continue;
        }
        if (!pen_down) {
            path.moveTo(to_x(md), to_y(twt));
            pen_down = true;
        } else {
            path.lineTo(to_x(md), to_y(twt));
        }
    }
    painter.setPen(QPen(QColor(0x1d, 0x4e, 0xd8), 1.6));
    painter.drawPath(path);

    // 标定探针：5 个等距 MD 的权威核插值（空探针 → 不画，诚实降级）。
    if (probe_ != nullptr) {
        painter.setPen(QPen(QColor(0xc2, 0x41, 0x0c), 1.0));
        for (int i = 0; i <= 4; ++i) {
            const double md = md_lo + (md_hi - md_lo) * i / 4.0;
            const double twt = probe_(md);
            if (!finite(twt)) continue;
            const double x = to_x(md);
            const double y = to_y(twt);
            painter.drawEllipse(QPointF(x, y), 3.0, 3.0);
            painter.drawText(QRect(static_cast<int>(x) - 34,
                                   static_cast<int>(y) - 20, 68, 14),
                             Qt::AlignCenter,
                             QStringLiteral("%1 ms").arg(twt, 0, 'f', 1));
        }
    }

    painter.setPen(QColor(0x33, 0x33, 0x33));
    painter.drawText(rect().adjusted(0, 0, -6, -2),
                     Qt::AlignLeft | Qt::AlignBottom, summary_line());
}

}  // namespace pwb::ui_pages_preview::qt
