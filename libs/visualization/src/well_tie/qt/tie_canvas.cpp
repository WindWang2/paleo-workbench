#include <pwb/viz/well_tie/qt/tie_canvas.hpp>

#include <QColor>
#include <QEvent>
#include <QMouseEvent>
#include <QPaintEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPen>
#include <QPointF>
#include <QRectF>

#include <algorithm>
#include <cmath>
#include <limits>

#include <pwb/viz/well_tie/auto_tie.hpp>
#include <pwb/viz/well_tie/calibration.hpp>
#include <pwb/viz/well_tie/synthetic.hpp>
#include <pwb/viz/well_tie/wavelet.hpp>

namespace pwb::viz::well_tie::qt {

namespace {

// canvas.py fixed column widths: Depth/TWT, DT/RHOB, AI, RC, Synthetic,
// Seismic, Correlation.
const double kTrackWidths[kTieTrackCount] = {80.0, 140.0, 110.0, 70.0,
                                             100.0, 120.0, 90.0};
const char* kTrackTitles[kTieTrackCount] = {
    "Depth/TWT", "DT / RHOB", "AI", "RC", "Synthetic", "Seismic",
    "Correlation"};

double track_x(int track) {
    double x = 0.0;
    for (int i = 0; i < track; ++i) x += kTrackWidths[i];
    return x;
}

// Wiggle trace drawing: positive right, negative left, centred line.
void paint_trace(QPainter* painter, double x0, double width, double y_top,
                 double y_bottom, double depth_top, double depth_bottom,
                 const std::vector<double>& depths,
                 const std::vector<double>& values, double amplitude,
                 const QColor& color, bool fill_positive) {
    if (depths.empty() || values.empty() || amplitude <= 0.0) return;
    const double content_h = y_bottom - y_top;
    const double span = depth_bottom - depth_top;
    if (content_h <= 0.0 || span <= 0.0) return;
    QPainterPath path;
    QPainterPath fill;
    bool started = false;
    double last_y = 0.0;
    for (std::size_t i = 0; i < depths.size() && i < values.size(); ++i) {
        if (!std::isfinite(values[i])) continue;
        const double y = y_top + (depths[i] - depth_top) / span * content_h;
        const double v = std::clamp(values[i] / amplitude, -1.0, 1.0);
        const double x = x0 + width / 2.0 + v * (width / 2.0 - 2.0);
        if (!started) {
            path.moveTo(x, y);
            fill.moveTo(x0 + width / 2.0, y);
            fill.lineTo(x, y);
            started = true;
        } else {
            path.lineTo(x, y);
            if (fill_positive && v >= 0.0) {
                fill.lineTo(x, y);
            } else if (fill_positive) {
                fill.lineTo(x0 + width / 2.0, y);
                fill.lineTo(x, y);
            }
        }
        last_y = y;
    }
    (void)last_y;
    painter->setRenderHint(QPainter::Antialiasing, true);
    if (fill_positive && started) {
        QColor fill_color = color;
        fill_color.setAlpha(140);
        painter->setPen(Qt::NoPen);
        painter->setBrush(fill_color);
        painter->drawPath(fill);
    }
    painter->setPen(QPen(color, 1.0));
    painter->setBrush(Qt::NoBrush);
    painter->drawPath(path);
    // Centre reference line.
    painter->setPen(QPen(QColor(0xcb, 0xd5, 0xe0), 1.0));
    painter->drawLine(QPointF(x0 + width / 2.0, y_top),
                      QPointF(x0 + width / 2.0, y_bottom));
}

double max_abs(const std::vector<double>& values) {
    double m = 0.0;
    for (double v : values) m = std::max(m, std::abs(v));
    return m;
}

double max_abs_f(const std::vector<float>& values) {
    double m = 0.0;
    for (float v : values) m = std::max(m, std::abs(static_cast<double>(v)));
    return m;
}

}  // namespace

WellTieCanvas::WellTieCanvas(QWidget* parent) : QWidget(parent) {
    setMouseTracking(true);
    setMinimumSize(710, 320);
    setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Expanding);
    wavelet_ = pwb::viz::well_tie::ricker_wavelet(51, 0.002, 30.0);
}

WellTieCanvas::~WellTieCanvas() = default;

void WellTieCanvas::set_tie_data(const std::vector<double>& depths,
                                 const std::vector<double>& twt,
                                 const std::vector<double>& sonic,
                                 const std::vector<double>& density,
                                 const std::vector<double>& seismic_trace,
                                 const std::vector<float>& wavelet) {
    depths_ = depths;
    twt_ = (twt.size() == depths.size()) ? twt : std::vector<double>{};
    sonic_ = sonic;
    density_ = density;
    seismic_ = seismic_trace;
    // from_sonic may shorten its arrays (NaN masking); mismatched sizes
    // must never reach WellTieCalibration (it throws) — clamp here and
    // let the readout show the honest state.
    const std::size_t n = std::min({depths_.size(), sonic_.size(),
                                    density_.size()});
    depths_.resize(n);
    sonic_.resize(n);
    density_.resize(n);
    if (twt_.size() > n) twt_.resize(n);
    if (!wavelet.empty()) {
        wavelet_ = wavelet;
    }
    cache_dirty_ = true;
    update();
}

void WellTieCanvas::recalculate() {
    if (!cache_dirty_) return;
    cache_dirty_ = false;
    impedance_.assign(sonic_.size(), 0.0);
    for (std::size_t i = 0; i < sonic_.size(); ++i) {
        impedance_[i] = (1.0e6 / sonic_[i]) * density_[i];
    }
    reflectivity_ = pwb::viz::well_tie::compute_reflectivity(sonic_, density_);
    synthetic_ =
        pwb::viz::well_tie::generate_synthetic(reflectivity_, wavelet_);
    // Auto tie: synthetic (interface series) against the seismic trace
    // resampled on the same TWT grid is the caller's concern; here the
    // correlation runs synthetic-vs-seismic directly (canvas contract:
    // correlation column mirrors correlate_synthetic_to_trace).
    if (!seismic_.empty() && synthetic_.size() >= 2) {
        std::vector<double> syn_double(synthetic_.begin(),
                                       synthetic_.end());
        const auto result =
            pwb::viz::well_tie::correlate_synthetic_to_trace(syn_double,
                                                             seismic_);
        correlation_ = result.correlation;
        lag_samples_ = result.shift_samples;
        // 2 ms default sampling for the ms conversion; the dock knows
        // the true dt and overrides lag_ms_ via its own model.
        lag_ms_ = static_cast<double>(lag_samples_) * 2.0;
    } else {
        correlation_ = 0.0;
        lag_samples_ = 0;
        lag_ms_ = 0.0;
    }
}

void WellTieCanvas::paintEvent(QPaintEvent*) {
    recalculate();
    QPainter painter(this);
    const double w = static_cast<double>(width());
    const double h = static_cast<double>(height());
    painter.fillRect(QRectF(0, 0, w, h), QColor(250, 249, 245));
    const double content_h = std::max(10.0, h - kTieHeaderHeightPx);
    // Header row.
    QFont header_font = painter.font();
    header_font.setPointSize(9);
    header_font.setBold(true);
    painter.setFont(header_font);
    for (int t = 0; t < kTieTrackCount; ++t) {
        const double x = track_x(t);
        const QRectF header(x, 0.0, kTrackWidths[t], kTieHeaderHeightPx);
        painter.fillRect(header, QColor(241, 244, 249));
        painter.setPen(QPen(QColor(229, 234, 241), 1.0));
        painter.drawRect(header);
        painter.setPen(QPen(QColor(31, 102, 212), 1.0));
        painter.drawText(header, Qt::AlignCenter,
                         QString::fromUtf8(kTrackTitles[t]));
    }
    // Column separators through the full height.
    painter.setPen(QPen(QColor(229, 234, 241), 1.0));
    for (int t = 1; t < kTieTrackCount; ++t) {
        painter.drawLine(QPointF(track_x(t), 0.0),
                         QPointF(track_x(t), h));
    }
    if (depths_.empty()) return;
    const double depth_top = depths_.front();
    const double depth_bottom = depths_.back();
    const double y_top = kTieHeaderHeightPx;
    const double y_bottom = h;
    // Track 0: depth + TWT labels.
    QFont small = painter.font();
    small.setPointSize(8);
    small.setBold(false);
    painter.setFont(small);
    const int steps = 10;
    for (int i = 0; i <= steps; ++i) {
        const double depth =
            depth_top + (depth_bottom - depth_top) * i / steps;
        const double y = y_top + (y_bottom - y_top) * i / steps;
        painter.setPen(QPen(QColor(0x2d, 0x37, 0x48), 1.0));
        painter.drawText(QPointF(4.0, y + 3.0),
                         QString::number(depth, 'f', 0));
        // TWT from the table when available (interpolate by index
        // proximity — the twt_ array is aligned with depths_).
        if (i < static_cast<int>(twt_.size())) {
            const std::size_t idx = std::min<std::size_t>(
                twt_.size() - 1,
                static_cast<std::size_t>(
                    static_cast<double>(twt_.size() - 1) * i / steps));
            painter.setPen(QPen(QColor(0, 100, 180), 1.0));
            painter.drawText(QPointF(44.0, y + 3.0),
                             QString::number(twt_[idx], 'f', 0));
        }
    }
    // Track 1: DT + RHOB curves (normalized to their own ranges).
    {
        const double x0 = track_x(1);
        const std::vector<double> depth_axis(depths_.begin(),
                                             depths_.end());
        paint_trace(&painter, x0, kTrackWidths[1] / 2.0, y_top, y_bottom,
                    depth_top, depth_bottom, depth_axis, sonic_,
                    max_abs(sonic_), QColor(0x08, 0x91, 0xb2), false);
        paint_trace(&painter, x0 + kTrackWidths[1] / 2.0,
                    kTrackWidths[1] / 2.0, y_top, y_bottom, depth_top,
                    depth_bottom, depth_axis, density_,
                    max_abs(density_), QColor(0xd9, 0x77, 0x06), false);
    }
    // Track 2: AI.
    {
        const std::vector<double> depth_axis(depths_.begin(),
                                             depths_.end());
        paint_trace(&painter, track_x(2), kTrackWidths[2], y_top, y_bottom,
                    depth_top, depth_bottom, depth_axis, impedance_,
                    max_abs(impedance_), QColor(0x7c, 0x3a, 0xed), false);
        // Track 3: RC (interface series -> draw against midpoints).
        std::vector<double> rc_depths;
        std::vector<double> rc_values(reflectivity_.begin(),
                                      reflectivity_.end());
        for (std::size_t i = 0; i + 1 < depths_.size(); ++i) {
            rc_depths.push_back(0.5 * (depths_[i] + depths_[i + 1]));
        }
        paint_trace(&painter, track_x(3), kTrackWidths[3], y_top, y_bottom,
                    depth_top, depth_bottom, rc_depths, rc_values,
                    std::max(max_abs_f(reflectivity_), 1e-9),
                    QColor(0x05, 0x96, 0x69), true);
        // Track 4: Synthetic.
        std::vector<double> syn_depths;
        for (std::size_t i = 0; i + 1 < depths_.size(); ++i) {
            syn_depths.push_back(0.5 * (depths_[i] + depths_[i + 1]));
        }
        std::vector<double> syn_double(synthetic_.begin(),
                                       synthetic_.end());
        paint_trace(&painter, track_x(4), kTrackWidths[4], y_top, y_bottom,
                    depth_top, depth_bottom, syn_depths, syn_double,
                    std::max(max_abs_f(synthetic_), 1e-9),
                    QColor(0xdc, 0x26, 0x26), true);
    }
    // Track 5: Seismic (uniform grid on the TWT axis).
    if (!seismic_.empty()) {
        std::vector<double> seis_depths(seismic_.size());
        for (std::size_t i = 0; i < seismic_.size(); ++i) {
            seis_depths[i] =
                twt_.empty()
                    ? depth_top
                    : pwb::viz::well_tie::WellTieCalibration(depths_, twt_)
                          .twt_to_depth(static_cast<double>(i) * 2.0 +
                                        (!twt_.empty() ? twt_.front()
                                                       : 0.0));
        }
        paint_trace(&painter, track_x(5), kTrackWidths[5], y_top, y_bottom,
                    depth_top, depth_bottom, seis_depths, seismic_,
                    max_abs(seismic_), QColor(0x1f, 0x66, 0xd4), true);
    }
    // Track 6: Correlation readout.
    {
        painter.setPen(QPen(QColor(0x2d, 0x37, 0x48), 1.0));
        QFont f = painter.font();
        f.setPointSize(10);
        painter.setFont(f);
        painter.drawText(
            QRectF(track_x(6), y_top + 8.0, kTrackWidths[6], 40.0),
            Qt::AlignLeft | Qt::TextWordWrap,
            QString("R = %1\nlag = %2 ms")
                .arg(correlation_, 0, 'f', 3)
                .arg(lag_ms_, 0, 'f', 1));
    }
    // Hover crosshair (canvas.py: red dashed full-width line).
    if (has_hover_) {
        QPen pen(QColor(220, 38, 38), 1.0);
        pen.setStyle(Qt::DashLine);
        painter.setPen(pen);
        painter.drawLine(QPointF(0.0, hover_y_), QPointF(w, hover_y_));
    }
}

void WellTieCanvas::mouseMoveEvent(QMouseEvent* event) {
    has_hover_ = true;
    hover_y_ = event->position().y();
    // Interpolated depth/TWT under the cursor + correlation value.
    if (!depths_.empty()) {
        const double h = static_cast<double>(height());
        const double content_h =
            std::max(10.0, h - kTieHeaderHeightPx);
        const double ratio = std::clamp(
            (hover_y_ - kTieHeaderHeightPx) / content_h, 0.0, 1.0);
        const double depth = depths_.front() +
                             ratio * (depths_.back() - depths_.front());
        double twt = depth;
        if (!twt_.empty()) {
            twt = pwb::viz::well_tie::WellTieCalibration(depths_, twt_)
                      .depth_to_twt(depth);
        }
        emit cursor_moved(depth, twt, correlation_);
    }
    update();
}

void WellTieCanvas::leaveEvent(QEvent*) {
    has_hover_ = false;
    update();
}

}  // namespace pwb::viz::well_tie::qt
