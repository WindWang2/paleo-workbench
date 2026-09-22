#include <pwb/seismic_viewer/section_profile_widget.hpp>
#include <QDialog>
#include <QInputDialog>
#include <QMessageBox>
#include <QRegularExpression>
#include <QSettings>
#include <stdexcept>
#include <pwb/seismic_viewer/attribute_fusion_core.hpp>
#include <pwb/seismic_viewer/color_maps.hpp>
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#include <pwb/seismic_viewer/slice_export.hpp>
#include <pwb/seismic_viewer/view_state.hpp>

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFile>
#include <QFileDialog>
#include <QFontMetrics>
#include <QHBoxLayout>
#include <QImage>
#include <QLabel>
#include <QMouseEvent>
#include <QPainter>
#include <QPaintEvent>
#include <QPixmap>
#include <QPushButton>
#include <QResizeEvent>
#include <QSlider>
#include <QSpinBox>
#include <QVBoxLayout>
#include <QVector>
#include <QWheelEvent>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <fstream>
#include <iterator>
#include <limits>
#include <utility>

#include <pwb/domain/json.hpp>

namespace pwb::seismic_viewer {
namespace {

using pwb::viz::VolumeAxis;

std::string next_viewer_origin() {
    static std::atomic<std::uint64_t> counter{0};
    return "seismic_viewer-" + std::to_string(counter.fetch_add(1));
}

// Canonical axis tokens for the view-state schema (horizon binding uses the
// same vocabulary: "inline" | "crossline" | "sample").
const char* axis_schema_name(VolumeAxis axis) {
    switch (axis) {
    case VolumeAxis::inline_:
        return "inline";
    case VolumeAxis::crossline:
        return "crossline";
    case VolumeAxis::sample:
        return "sample";
    }
    return "?";
}

bool axis_from_schema_name(std::string_view name, VolumeAxis& out) {
    if (name == "inline") {
        out = VolumeAxis::inline_;
        return true;
    }
    if (name == "crossline") {
        out = VolumeAxis::crossline;
        return true;
    }
    if (name == "sample") {
        out = VolumeAxis::sample;
        return true;
    }
    return false;
}

const char* axis_display_name(VolumeAxis axis) {
    switch (axis) {
    case VolumeAxis::inline_:
        return "Inline";
    case VolumeAxis::crossline:
        return "Crossline";
    case VolumeAxis::sample:
        return "Sample";
    }
    return "?";
}

// Frozen v3 display mapping — which volume axis the image's vertical (row)
// and horizontal (col) pixel run along. Section views put the sample axis
// (time) vertical and increasing DOWNWARD; the sample slice is a map view.
//   inline view:    y = sample,  x = crossline
//   crossline view: y = sample,  x = inline
//   sample view:    y = inline,  x = crossline
struct PlaneAxes {
    VolumeAxis row; // image y axis
    VolumeAxis col; // image x axis
    std::int64_t row_count;
    std::int64_t col_count;
};

PlaneAxes plane_axes(const pwb::viz::VolumeGeometryV1& geometry, VolumeAxis axis) {
    const auto shape = geometry.shape;
    switch (axis) {
    case VolumeAxis::inline_:
        return {VolumeAxis::sample, VolumeAxis::crossline, shape[2], shape[1]};
    case VolumeAxis::crossline:
        return {VolumeAxis::sample, VolumeAxis::inline_, shape[2], shape[0]};
    case VolumeAxis::sample:
        return {VolumeAxis::inline_, VolumeAxis::crossline, shape[0], shape[1]};
    }
    return {VolumeAxis::sample, VolumeAxis::crossline, shape[2], shape[1]};
}

// Image pixel (x, y) -> flat index into the canonical plane buffer (the
// plane's own rows/cols follow ISeismicVolume order, which is the transpose
// of the section-view image for inline/crossline). `plane_cols` is the
// canonical plane column count (result.cols).
[[nodiscard]] std::int64_t plane_flat_index(VolumeAxis axis, std::int64_t plane_cols,
                                            std::int64_t image_x, std::int64_t image_y) {
    switch (axis) {
    case VolumeAxis::inline_:   // plane rows = crossline (=x), cols = sample (=y)
    case VolumeAxis::crossline: // plane rows = inline (=x),    cols = sample (=y)
        return image_x * plane_cols + image_y;
    case VolumeAxis::sample: // plane rows = inline (=y), cols = crossline (=x)
        return image_y * plane_cols + image_x;
    }
    return 0;
}

std::string axis_unit_for(const pwb::viz::VolumeGeometryV1& geometry, VolumeAxis axis) {
    // inline/crossline are unitless line numbers; only the sample axis is
    // physical (e.g. "ms").
    return axis == VolumeAxis::sample ? geometry.unit : std::string();
}

std::string format_value(double value, const std::string& unit) {
    std::string text = std::to_string(value);
    if (text.find('.') != std::string::npos) {
        while (text.size() > 1 && text.back() == '0') {
            text.pop_back();
        }
        if (!text.empty() && text.back() == '.') {
            text.pop_back();
        }
    }
    return unit.empty() ? text : text + " " + unit;
}

} // namespace

// ---------------------------------------------------------------------------
// SliceCanvas: raster painting of the indexed8 slice with zoom/pan, plus the
// VIZ-D wiggle renderer and horizon pick markers. No moc, no signals:
// interaction results are pushed through SeismicSliceWidget.
// ---------------------------------------------------------------------------
class SliceCanvas final : public QWidget {
public:
    explicit SliceCanvas(SeismicSliceWidget* owner) : QWidget(owner), owner_(owner) {
        setMouseTracking(true);
        setMinimumSize(320, 240);
    }

    void set_image(const QImage* image, const QString& overlay) {
        image_ = image;
        overlay_ = overlay;
        if (!user_moved_) {
            fit_to_image();
        }
        update();
    }

    void set_wiggle(const display::WiggleGeometry* wiggle) {
        wiggle_ = wiggle;
        update();
    }

    void set_pick_markers(const std::vector<QPointF>* markers) {
        pick_markers_ = markers;
        update();
    }

    void set_display_mode(DisplayMode mode) {
        mode_ = mode;
        update();
    }

    void set_picking(bool picking) { picking_ = picking; }

    void fit_to_image() {
        if (image_ == nullptr || image_->isNull() || width() <= 0 || height() <= 0) {
            return;
        }
        const double sx = static_cast<double>(width()) / image_->width();
        const double sy = static_cast<double>(height()) / image_->height();
        scale_ = std::max(1.0, std::min(sx, sy));
        // Center the image; offsets are in image pixels.
        offset_x_ = -(static_cast<double>(width()) / scale_ - image_->width()) / 2.0;
        offset_y_ = -(static_cast<double>(height()) / scale_ - image_->height()) / 2.0;
        user_moved_ = false;
    }

    [[nodiscard]] double scale() const { return scale_; }
    [[nodiscard]] double offset_x() const { return offset_x_; }
    [[nodiscard]] double offset_y() const { return offset_y_; }

    void set_transform(double scale, double ox, double oy) {
        scale_ = std::clamp(scale, 1.0, 64.0);
        offset_x_ = ox;
        offset_y_ = oy;
        clamp_offsets();
        user_moved_ = true;
        update();
    }

    // widget pixel -> image pixel (may be fractional/out of bounds)
    [[nodiscard]] QPointF widget_to_image(const QPointF& point) const {
        return QPointF(point.x() / scale_ + offset_x_, point.y() / scale_ + offset_y_);
    }

protected:
    void paintEvent(QPaintEvent*) override {
        QPainter painter(this);
        if (mode_ == DisplayMode::wiggle && wiggle_ != nullptr) {
            paint_wiggle(painter);
        } else {
            painter.fillRect(rect(), QColor(24, 24, 24));
            if (image_ != nullptr && !image_->isNull()) {
                painter.setRenderHint(QPainter::SmoothPixmapTransform, false);
                painter.drawImage(rect(), *image_, source_rect());
            }
        }
        if (mode_ != DisplayMode::wiggle && pick_markers_ != nullptr) {
            // Horizon picks: 3 px amber dots with a dark rim, in IMAGE pixel
            // coordinates mapped through the current zoom/pan transform.
            painter.setRenderHint(QPainter::Antialiasing, true);
            for (const QPointF& marker : *pick_markers_) {
                const QPointF centre = image_to_widget(marker);
                painter.setPen(QPen(QColor(30, 30, 30), 1.5));
                painter.setBrush(QColor(255, 210, 0));
                painter.drawEllipse(centre, 3.0, 3.0);
            }
        }
        if (!overlay_.isEmpty()) {
            const QFontMetrics metrics = painter.fontMetrics();
            const int text_width = metrics.horizontalAdvance(overlay_);
            painter.fillRect(6, 6, text_width + 12, metrics.height() + 8,
                             QColor(0, 0, 0, 170));
            painter.setPen(QColor(255, 210, 80));
            painter.drawText(12, 12 + metrics.ascent(), overlay_);
        }
        painter.setPen(QColor(160, 160, 160));
        painter.drawRect(0, 0, width() - 1, height() - 1);
    }

    void resizeEvent(QResizeEvent* event) override {
        QWidget::resizeEvent(event);
        if (!user_moved_) {
            fit_to_image();
        }
        owner_->rebuild_wiggle(width(), height());
    }

    void wheelEvent(QWheelEvent* event) override {
        if (mode_ == DisplayMode::wiggle) {
            return; // the wiggle source has no zoom (viewport-fit rendering)
        }
        const QPointF anchor = widget_to_image(event->position());
        const double factor = event->angleDelta().y() > 0 ? 1.25 : 0.8;
        const double next = std::clamp(scale_ * factor, 1.0, 64.0);
        scale_ = next;
        offset_x_ = anchor.x() - event->position().x() / next;
        offset_y_ = anchor.y() - event->position().y() / next;
        clamp_offsets();
        user_moved_ = true;
        update();
    }

    void mousePressEvent(QMouseEvent* event) override {
        if (picking_ && event->button() == Qt::RightButton) {
            if (owner_->report_pick_context_menu(widget_to_image(event->position()))) {
                return; // consumed by a pick deletion
            }
            return;
        }
        if (picking_ && event->button() == Qt::LeftButton) {
            owner_->report_pick_press(widget_to_image(event->position()));
            return;
        }
        if (event->button() == Qt::LeftButton) {
            press_pos_ = event->position();
            last_pos_ = event->position();
            dragging_ = false;
        }
    }

    void mouseMoveEvent(QMouseEvent* event) override {
        if (picking_ && (event->buttons() & Qt::LeftButton)) {
            owner_->report_pick_drag(widget_to_image(event->position()));
            return;
        }
        if ((event->buttons() & Qt::LeftButton) && !press_pos_.isNull()) {
            const QPointF delta = event->position() - last_pos_;
            if ((event->modifiers() & Qt::ShiftModifier) == 0) {
                if (!dragging_ &&
                    std::hypot((event->position() - press_pos_).x(),
                               (event->position() - press_pos_).y()) > 4.0) {
                    dragging_ = true;
                        user_moved_ = true;
                }
                if (dragging_) {
                    offset_x_ -= delta.x() / scale_;
                    offset_y_ -= delta.y() / scale_;
                    clamp_offsets();
                    update();
                }
            }
            last_pos_ = event->position();
        }
        owner_->report_cursor(widget_to_image(event->position()));
    }

    void mouseReleaseEvent(QMouseEvent* event) override {
        if (picking_ && event->button() == Qt::LeftButton) {
            owner_->report_pick_drag(widget_to_image(event->position()));
            return;
        }
        if (event->button() != Qt::LeftButton || press_pos_.isNull()) {
            return;
        }
        const QPointF from = widget_to_image(press_pos_);
        const QPointF to = widget_to_image(event->position());
        const bool shift = (event->modifiers() & Qt::ShiftModifier) != 0;
        if (dragging_ && shift) {
            owner_->report_drag_selection(from, to);
        } else if (!dragging_) {
            owner_->report_click_selection(to);
        }
        press_pos_ = QPointF();
        dragging_ = false;
    }

    void mouseDoubleClickEvent(QMouseEvent*) override { owner_->reset_view(); }

private:
    [[nodiscard]] QPointF image_to_widget(const QPointF& point) const {
        return QPointF((point.x() - offset_x_) * scale_, (point.y() - offset_y_) * scale_);
    }

    // profile_wiggle paint pipeline parity: white background, antialias on,
    // light-gray per-trace baselines, positive lobes filled black at alpha
    // 200 as separate polygons (zero-crossing points already interpolated
    // into the geometry), dark 1 px deflection polylines. Geometry comes
    // precomputed (pure double math, oracle-testable) from the widget.
    void paint_wiggle(QPainter& painter) {
        painter.fillRect(rect(), QColor(255, 255, 255));
        painter.setRenderHint(QPainter::Antialiasing, true);
        QPen baseline_pen(QColor(230, 230, 230));
        baseline_pen.setWidthF(1.0);
        QPen wiggle_pen(QColor(30, 30, 30));
        wiggle_pen.setWidthF(1.0);
        QBrush fill_brush(QColor(0, 0, 0, 200));
        for (const display::WiggleTrace& trace : wiggle_->traces) {
            painter.setPen(baseline_pen);
            painter.drawLine(QPointF(trace.centre_x, 0.0),
                             QPointF(trace.centre_x, static_cast<double>(height())));
            painter.setPen(Qt::NoPen);
            painter.setBrush(fill_brush);
            for (const display::WiggleLobe& lobe : trace.lobes) {
                QPolygonF polygon;
                polygon.reserve(static_cast<std::size_t>(lobe.xs.size()));
                for (std::size_t i = 0; i < lobe.xs.size(); ++i) {
                    polygon.append(QPointF(lobe.xs[i], lobe.ys[i]));
                }
                painter.drawPolygon(polygon);
            }
            painter.setPen(wiggle_pen);
            painter.setBrush(Qt::NoBrush);
            QPolygonF polyline;
            polyline.reserve(trace.xs.size());
            for (std::size_t i = 0; i < trace.xs.size(); ++i) {
                polyline.append(QPointF(trace.xs[i], trace.ys[i]));
            }
            painter.drawPolyline(polyline);
        }
    }

    [[nodiscard]] QRectF source_rect() const {
        // Visible widget area expressed in image pixels.
        return QRectF(offset_x_, offset_y_, width() / scale_, height() / scale_);
    }

    void clamp_offsets() {
        if (image_ == nullptr || image_->isNull()) {
            return;
        }
        const double view_w = width() / scale_;
        const double view_h = height() / scale_;
        // Keep at least a sliver of the image reachable in each direction.
        offset_x_ = std::clamp(offset_x_, -view_w + 8.0,
                               static_cast<double>(image_->width()) - 8.0);
        offset_y_ = std::clamp(offset_y_, -view_h + 8.0,
                               static_cast<double>(image_->height()) - 8.0);
    }

    SeismicSliceWidget* owner_;
    const QImage* image_{nullptr};
    const display::WiggleGeometry* wiggle_{nullptr};
    const std::vector<QPointF>* pick_markers_{nullptr};
    QString overlay_;
    DisplayMode mode_{DisplayMode::variable_density};
    bool picking_{false};
    double scale_{1.0};
    double offset_x_{0};
    double offset_y_{0};
    bool user_moved_{false};
    bool dragging_{false};
    QPointF press_pos_;
    QPointF last_pos_;
};

// ---------------------------------------------------------------------------
// SeismicSliceWidget::Impl
// ---------------------------------------------------------------------------
struct SeismicSliceWidget::Impl {
    std::shared_ptr<pwb::viz::ISeismicVolume> source;
    std::unique_ptr<SliceController> controller;
    std::optional<pwb::viz::VolumeGeometryV1> geometry; // plain copy, not the volume
    ViewerState state{ViewerState::no_source};
    std::string diagnostic;
    VolumeAxis axis{VolumeAxis::inline_};
    std::int64_t index{0};
    std::string color_map_name{"seismic"};
    ColorLut lut;
    bool explicit_range{false};
    double range_min{0.0};
    double range_max{1.0};
    SliceResult plane; // last delivered good plane (owned copy)
    QImage image;
    std::uint64_t volume_revision_value{0};
    VolumeIdentity identity;
    std::optional<LinearTimeDepth> relation;
    SelectionCallback selection_callback;
    const std::string origin = next_viewer_origin();
    bool updating_controls{false}; // suppress control echo during programmatic sets

    // --- VIZ-D advanced display state ---
    DisplayMode display_mode{DisplayMode::variable_density};
    bool polarity_normal{true};
    bool clip_pct_enabled{false};
    double clip_pct{99.0};
    double wiggle_gain{2.0};
    bool picking{false};
    horizon::HorizonPickSet picks;
    std::string picks_note; // status line note (binding mismatch etc.)
    std::optional<int> pick_drag_index; // pick being dragged (edit)
    display::WiggleGeometry wiggle_cache;
    bool wiggle_cache_valid{false};
    // Percentile clip cache: reused across sibling slices of the same
    // volume+axis (profile_vd #119 semantics); invalidated on volume swap,
    // axis change and clip_pct change.
    struct ClipCache {
        bool valid{false};
        double lo{0.0};
        double hi{0.0};
        std::string volume_key;
        pwb::viz::VolumeAxis axis{pwb::viz::VolumeAxis::inline_};
        std::int64_t rows{0};
        std::int64_t cols{0};
        double pct{99.0};
    } clip_cache;
    double displayed_lo{0.0};
    double displayed_hi{0.0};

    // --- VIZ-D attribute / fusion view (07 line) ---------------------------
    // Pinned to the slice it was computed for: binding (axis/index/revision)
    // is checked on every delivered plane, and any other slice drops the
    // pinned view back to amplitude (a stale attribute is never painted).
    bool attribute_active_flag{false};
    std::string attribute_label;
    VolumeAxis attribute_axis{VolumeAxis::inline_};
    std::int64_t attribute_index{0};
    std::uint64_t attribute_revision{0};
    QImage attribute_image; // display-oriented RGB888 / Indexed8 render
    double attribute_lo{0.0};
    double attribute_hi{0.0};

    void clear_attribute_view() {
        if (!attribute_active_flag) {
            return;
        }
        attribute_active_flag = false;
        attribute_label.clear();
        attribute_image = QImage();
        refresh_overlay();
        sync_colorbar();
    }

    // Common guard for the attribute setters: a plane is only accepted for
    // the currently displayed slice (shape + axis + revision) — a stale or
    // misshapen attribute must fail closed with a diagnostic, never paint.
    bool attribute_view_shape_ok(std::int64_t rows, std::int64_t cols) {
        if (plane.values.empty() || plane.rows <= 0 || plane.cols <= 0) {
            diagnostic = "no displayed slice to pin the attribute to";
            return false;
        }
        if (rows != plane.rows || cols != plane.cols) {
            diagnostic = "attribute shape does not match the displayed slice";
            return false;
        }
        return true;
    }


    // widgets
    SliceCanvas* canvas{nullptr};
    QComboBox* axis_combo{nullptr};
    QSlider* index_slider{nullptr};
    QSpinBox* index_spin{nullptr};
    QLabel* coordinate_label{nullptr};
    QComboBox* cmap_combo{nullptr};
    QCheckBox* explicit_range_check{nullptr};
    QDoubleSpinBox* range_min_spin{nullptr};
    QDoubleSpinBox* range_max_spin{nullptr};
    QPushButton* reset_button{nullptr};
    QLabel* status_label{nullptr};
    // VIZ-D toolbar widgets
    QComboBox* mode_combo{nullptr};
    QCheckBox* polarity_check{nullptr};
    QCheckBox* clip_check{nullptr};
    QDoubleSpinBox* clip_spin{nullptr};
    QDoubleSpinBox* gain_spin{nullptr};
    QCheckBox* pick_check{nullptr};
    QPushButton* clear_picks_button{nullptr};
    QPushButton* save_picks_button{nullptr};
    QPushButton* load_picks_button{nullptr};
    ColorbarWidget* colorbar{nullptr};

    [[nodiscard]] bool section_view() const {
        // Wiggle needs the sample axis vertical (inline/crossline views).
        return geometry.has_value() &&
               plane_axes(*geometry, axis).row == VolumeAxis::sample;
    }

    [[nodiscard]] std::string clip_volume_key() const {
        return identity.volume_id + ":" + std::to_string(volume_revision_value);
    }

    void invalidate_clip_cache() { clip_cache.valid = false; }

    void refresh_wiggle() {
        wiggle_cache_valid = false;
        if (canvas != nullptr) {
            canvas->update();
        }
    }

    void sync_colorbar() {
        if (colorbar == nullptr) {
            return;
        }
        colorbar->set_colormap(color_map_name);
        colorbar->set_range(displayed_lo, displayed_hi);
    }

    void resubmit() {
        if (!controller || !geometry) {
            return;
        }
        std::optional<std::pair<double, double>> range;
        if (explicit_range) {
            range = std::make_pair(range_min, range_max);
        }
        controller->submit(axis, index, range);
    }

    void sync_index_controls() {
        updating_controls = true;
        index_slider->setValue(static_cast<int>(index));
        index_spin->setValue(static_cast<int>(index));
        updating_controls = false;
    }

    void sync_axis_combo() {
        updating_controls = true;
        axis_combo->setCurrentIndex(axis == VolumeAxis::inline_   ? 0
                                    : axis == VolumeAxis::crossline ? 1
                                                                    : 2);
        updating_controls = false;
    }

    void update_coordinate_label() {
        if (!geometry) {
            coordinate_label->setText(QStringLiteral("—"));
            return;
        }
        const double coordinate = geometry->axis_value(axis, index);
        const std::string unit = axis_unit_for(*geometry, axis);
        coordinate_label->setText(QString::fromUtf8(axis_display_name(axis)) + " " +
                                  QString::fromStdString(format_value(coordinate, unit)));
    }

    void apply_color_table() {
        QVector<QRgb> table;
        table.reserve(256);
        for (const auto& rgb : lut) {
            table.push_back(qRgb(rgb[0], rgb[1], rgb[2]));
        }
        image.setColorTable(table);
    }

    void set_state(ViewerState next, std::string message) {
        state = next;
        diagnostic = std::move(message);
        refresh_overlay();
    }

    void refresh_overlay() {
        QString overlay;
        switch (state) {
        case ViewerState::no_source:
            overlay = QStringLiteral("no source volume");
            break;
        case ViewerState::empty:
            overlay = QStringLiteral("empty volume");
            break;
        case ViewerState::loading:
            overlay = QStringLiteral("loading slice…");
            break;
        case ViewerState::degenerate:
            overlay = QStringLiteral("degenerate stretch: ") +
                      QString::fromStdString(diagnostic);
            break;
        case ViewerState::failed:
            overlay = QStringLiteral("read failed: ") + QString::fromStdString(diagnostic);
            break;
        case ViewerState::ok:
            if (!plane.values.empty()) {
                overlay = QString::fromStdString(
                    "range " + format_value(plane.value_min, "") + " … " +
                    format_value(plane.value_max, ""));
            }
            break;
        }
        // The pinned attribute view replaces the amplitude raster on screen
        // (same zoom/pan transform, own overlay note); anything else keeps
        // the amplitude image.
        const QImage* shown = &image;
        if (attribute_active_flag && !attribute_image.isNull()) {
            shown = &attribute_image;
            if (!overlay.isEmpty()) {
                overlay += QStringLiteral("  |  ");
            }
            overlay += QString::fromStdString(attribute_label);
        }
        canvas->set_image(shown->isNull() ? nullptr : shown, overlay);
        // VIZ-D overlay state follows every state change so the canvas never
        // paints stale wiggle geometry or pick markers.
        canvas->set_display_mode(display_mode);
        canvas->set_picking(picking);
        canvas->set_wiggle(display_mode == DisplayMode::wiggle && wiggle_cache_valid
                               ? &wiggle_cache
                               : nullptr);
        canvas->set_pick_markers(&pick_marker_cache);
    }

    // Re-projected pick markers for the CURRENT view (image pixel coords).
    std::vector<QPointF> pick_marker_cache;

    void refresh_pick_markers() {
        pick_marker_cache.clear();
        if (!geometry.has_value()) {
            return;
        }
        for (const auto extent : geometry->shape) {
            if (extent < 1) {
                return; // zero-extent geometry: no valid projections
            }
        }
        const PlaneAxes axes = plane_axes(*geometry, axis);
        const auto value_to_index = [&](VolumeAxis a, double value) -> double {
            const std::size_t ai = pwb::viz::axis_index(a);
            const double step = geometry->step[ai];
            if (step == 0.0) {
                return 0.0;
            }
            const double idx = (value - geometry->origin[ai]) / step;
            return std::clamp(idx, 0.0, static_cast<double>(geometry->shape[ai] - 1));
        };
        for (const horizon::HorizonPick& pick : picks.picks) {
            double x = -1.0;
            double y = -1.0;
            switch (axis) {
            case VolumeAxis::inline_:
                x = value_to_index(VolumeAxis::crossline, pick.crossline_no);
                y = value_to_index(VolumeAxis::sample, pick.time_value);
                break;
            case VolumeAxis::crossline:
                x = value_to_index(VolumeAxis::inline_, pick.inline_no);
                y = value_to_index(VolumeAxis::sample, pick.time_value);
                break;
            case VolumeAxis::sample:
                x = value_to_index(VolumeAxis::crossline, pick.crossline_no);
                y = value_to_index(VolumeAxis::inline_, pick.inline_no);
                break;
            }
            if (axes.col_count > 0 && axes.row_count > 0) {
                pick_marker_cache.emplace_back(x, y);
            }
        }
    }

};

SeismicSliceWidget::SeismicSliceWidget(QWidget* parent) : QWidget(parent) {
    impl_ = std::make_unique<Impl>();

    auto* axis_label = new QLabel(QStringLiteral("Axis"), this);
    impl_->axis_combo = new QComboBox(this);
    impl_->axis_combo->addItem(QStringLiteral("Inline"));
    impl_->axis_combo->addItem(QStringLiteral("Crossline"));
    impl_->axis_combo->addItem(QStringLiteral("Sample"));
    impl_->index_slider = new QSlider(Qt::Horizontal, this);
    impl_->index_slider->setRange(0, 0);
    impl_->index_spin = new QSpinBox(this);
    impl_->index_spin->setRange(0, 0);
    impl_->coordinate_label = new QLabel(this);
    impl_->coordinate_label->setMinimumWidth(150);

    auto* cmap_label = new QLabel(QStringLiteral("Color"), this);
    impl_->cmap_combo = new QComboBox(this);
    for (const auto name : color_map_names()) {
        impl_->cmap_combo->addItem(QString::fromUtf8(name.data(), static_cast<int>(name.size())));
    }
    impl_->updating_controls = true;
    {
        const int seismic_row = impl_->cmap_combo->findText(QStringLiteral("seismic"));
        if (seismic_row >= 0) {
            impl_->cmap_combo->setCurrentIndex(seismic_row); // match default name
        }
    }
    impl_->updating_controls = false;
    impl_->explicit_range_check = new QCheckBox(QStringLiteral("Explicit range"), this);
    impl_->range_min_spin = new QDoubleSpinBox(this);
    impl_->range_max_spin = new QDoubleSpinBox(this);
    for (QDoubleSpinBox* spin : {impl_->range_min_spin, impl_->range_max_spin}) {
        spin->setRange(-1.0e12, 1.0e12);
        spin->setDecimals(4);
        spin->setEnabled(false);
    }
    impl_->reset_button = new QPushButton(QStringLiteral("Reset"), this);

    // --- VIZ-D advanced display toolbar (profile_vd / profile_wiggle) -----
    auto* mode_label = new QLabel(QStringLiteral("Mode"), this);
    impl_->mode_combo = new QComboBox(this);
    impl_->mode_combo->addItem(QStringLiteral("VD"));
    impl_->mode_combo->addItem(QStringLiteral("Wiggle"));
    impl_->polarity_check = new QCheckBox(QStringLiteral("Reverse polarity"), this);
    impl_->clip_check = new QCheckBox(QStringLiteral("Clip %"), this);
    impl_->clip_check->setToolTip(
        QStringLiteral("Asymmetric P(100-p)..P(p) percentile clip (profile_vd)"));
    impl_->clip_spin = new QDoubleSpinBox(this);
    impl_->clip_spin->setRange(1.0, 99.0);
    impl_->clip_spin->setDecimals(1);
    impl_->clip_spin->setSingleStep(0.5);
    impl_->clip_spin->setValue(impl_->clip_pct);
    impl_->clip_spin->setEnabled(false);
    impl_->gain_spin = new QDoubleSpinBox(this);
    impl_->gain_spin->setRange(0.1, 100.0);
    impl_->gain_spin->setDecimals(2);
    impl_->gain_spin->setSingleStep(0.5);
    impl_->gain_spin->setValue(impl_->wiggle_gain);
    impl_->gain_spin->setToolTip(QStringLiteral("Wiggle deflection gain (default 2.0)"));
    auto* gain_label = new QLabel(QStringLiteral("Gain"), this);
    impl_->pick_check = new QCheckBox(QStringLiteral("Pick"), this);
    impl_->clear_picks_button = new QPushButton(QStringLiteral("Clear picks"), this);
    impl_->save_picks_button = new QPushButton(QStringLiteral("Save picks…"), this);
    impl_->load_picks_button = new QPushButton(QStringLiteral("Load picks…"), this);

    auto* toolbar = new QHBoxLayout;
    toolbar->addWidget(axis_label);
    toolbar->addWidget(impl_->axis_combo);
    toolbar->addWidget(impl_->index_slider, 1);
    toolbar->addWidget(impl_->index_spin);
    toolbar->addWidget(impl_->coordinate_label);
    toolbar->addWidget(cmap_label);
    toolbar->addWidget(impl_->cmap_combo);
    toolbar->addWidget(impl_->explicit_range_check);
    toolbar->addWidget(impl_->range_min_spin);
    toolbar->addWidget(impl_->range_max_spin);
    toolbar->addWidget(impl_->reset_button);
    auto* arbitrary_button = new QPushButton(tr("Arbitrary line..."), this);
    arbitrary_button->setObjectName("arbitraryLineButton");
    toolbar->addWidget(arbitrary_button);
    connect(arbitrary_button, &QPushButton::clicked, this, [this] {
        if (!impl_->geometry) return;
        const auto& g = *impl_->geometry;
        const QString key = "seismic/arbitrary/" + QString::fromUtf8(impl_->identity.volume_id).toUtf8().toHex();
        const QString initial = QSettings().value(key,
            QString("%1,%2\n%3,%4").arg(g.origin[0]).arg(g.origin[1])
                .arg(g.axis_value(VolumeAxis::inline_, g.shape[0]-1))
                .arg(g.axis_value(VolumeAxis::crossline, g.shape[1]-1))).toString();
        bool accepted = false;
        const auto text = QInputDialog::getMultiLineText(this, tr("Arbitrary seismic section"),
            tr("Inline,crossline survey numbers; one vertex per line. All samples are retained."), initial, &accepted);
        if (!accepted) return;
        try {
            std::vector<std::pair<double,double>> vertices;
            for (const auto& line : text.split('\n', Qt::SkipEmptyParts)) {
                const auto fields = line.trimmed().split(QRegularExpression("[,;\\s]+"), Qt::SkipEmptyParts);
                bool ok_i = false, ok_x = false;
                if (fields.size() != 2) throw std::invalid_argument("each vertex requires inline,crossline");
                const double i = fields[0].toDouble(&ok_i), x = fields[1].toDouble(&ok_x);
                if (!ok_i || !ok_x) throw std::invalid_argument("invalid survey coordinate");
                vertices.emplace_back(i,x);
            }
            if (open_polyline_section(vertices)) QSettings().setValue(key,text);
        } catch (const std::exception& ex) {
            QMessageBox::warning(this,tr("Invalid arbitrary line"),QString::fromUtf8(ex.what()));
        }
    });

    auto* vizd_toolbar = new QHBoxLayout;
    vizd_toolbar->addWidget(mode_label);
    vizd_toolbar->addWidget(impl_->mode_combo);
    vizd_toolbar->addWidget(impl_->polarity_check);
    vizd_toolbar->addWidget(impl_->clip_check);
    vizd_toolbar->addWidget(impl_->clip_spin);
    vizd_toolbar->addWidget(gain_label);
    vizd_toolbar->addWidget(impl_->gain_spin);
    vizd_toolbar->addWidget(impl_->pick_check);
    vizd_toolbar->addWidget(impl_->clear_picks_button);
    vizd_toolbar->addWidget(impl_->save_picks_button);
    vizd_toolbar->addWidget(impl_->load_picks_button);
    vizd_toolbar->addStretch(1);

    impl_->canvas = new SliceCanvas(this);
    impl_->colorbar = new ColorbarWidget(this);
    auto* canvas_row = new QHBoxLayout;
    canvas_row->setContentsMargins(0, 0, 0, 0);
    canvas_row->setSpacing(0);
    canvas_row->addWidget(impl_->canvas, 1);
    canvas_row->addWidget(impl_->colorbar, 0);
    impl_->status_label = new QLabel(QStringLiteral("no volume"), this);

    auto* layout = new QVBoxLayout(this);
    layout->addLayout(toolbar);
    layout->addLayout(vizd_toolbar);
    layout->addLayout(canvas_row, 1);
    layout->addWidget(impl_->status_label);
    setLayout(layout);
    resize(640, 460);

    impl_->lut = color_lut(impl_->color_map_name);

    connect(impl_->axis_combo, &QComboBox::currentIndexChanged, this, [this](int row) {
        if (impl_->updating_controls) {
            return;
        }
        set_axis(row == 0   ? VolumeAxis::inline_
                 : row == 1 ? VolumeAxis::crossline
                            : VolumeAxis::sample);
    });
    const auto index_changed = [this](int value) {
        if (impl_->updating_controls || !impl_->geometry) {
            return;
        }
        impl_->index = value;
        impl_->update_coordinate_label();
        impl_->set_state(ViewerState::loading, {});
        impl_->resubmit();
    };
    connect(impl_->index_slider, &QSlider::valueChanged, this, index_changed);
    connect(impl_->index_spin, &QSpinBox::valueChanged, this, index_changed);
    connect(impl_->cmap_combo, &QComboBox::currentIndexChanged, this, [this](int row) {
        if (impl_->updating_controls) {
            return;
        }
        const auto names = color_map_names();
        if (row < 0 || static_cast<std::size_t>(row) >= names.size()) {
            return;
        }
        set_color_map(names[static_cast<std::size_t>(row)]);
    });
    const auto apply_explicit_range_from_controls = [this] {
        set_explicit_range(impl_->range_min_spin->value(), impl_->range_max_spin->value());
    };
    connect(impl_->explicit_range_check, &QCheckBox::toggled, this,
            [this, &apply_explicit_range_from_controls](bool checked) {
                if (impl_->updating_controls) {
                    return;
                }
                if (checked) {
                    apply_explicit_range_from_controls();
                } else {
                    set_auto_range();
                }
            });
    const auto range_edited = [this, &apply_explicit_range_from_controls](double) {
        if (impl_->updating_controls || !impl_->explicit_range_check->isChecked()) {
            return;
        }
        apply_explicit_range_from_controls();
    };
    connect(impl_->range_min_spin, &QDoubleSpinBox::valueChanged, this, range_edited);
    connect(impl_->range_max_spin, &QDoubleSpinBox::valueChanged, this, range_edited);
    connect(impl_->reset_button, &QPushButton::clicked, this, [this] { reset_view(); });

    // VIZ-D controls.
    connect(impl_->mode_combo, &QComboBox::currentIndexChanged, this, [this](int row) {
        if (impl_->updating_controls) {
            return;
        }
        set_display_mode(row == 1 ? DisplayMode::wiggle : DisplayMode::variable_density);
    });
    connect(impl_->polarity_check, &QCheckBox::toggled, this, [this](bool checked) {
        if (impl_->updating_controls) {
            return;
        }
        set_polarity(!checked); // checked = flipped display polarity
    });
    connect(impl_->clip_check, &QCheckBox::toggled, this, [this](bool checked) {
        if (impl_->updating_controls) {
            return;
        }
        set_clip_percentile_enabled(checked);
    });
    connect(impl_->clip_spin, &QDoubleSpinBox::valueChanged, this, [this](double value) {
        if (impl_->updating_controls) {
            return;
        }
        set_clip_percentile(value);
    });
    connect(impl_->gain_spin, &QDoubleSpinBox::valueChanged, this, [this](double value) {
        if (impl_->updating_controls) {
            return;
        }
        set_wiggle_gain(value);
    });
    connect(impl_->pick_check, &QCheckBox::toggled, this, [this](bool checked) {
        if (impl_->updating_controls) {
            return;
        }
        enable_picking(checked);
    });
    connect(impl_->clear_picks_button, &QPushButton::clicked, this, [this] { clear_picks(); });
    connect(impl_->save_picks_button, &QPushButton::clicked, this, [this] {
        const QString path = QFileDialog::getSaveFileName(
            this, tr("Save horizon picks"), QStringLiteral("horizon_picks.json"),
            tr("Horizon picks (*.json)"));
        if (path.isEmpty()) {
            return;
        }
        std::string error;
        if (!save_picks(path.toStdString(), error)) {
            impl_->picks_note = tr("picks save failed: %1")
                                    .arg(QString::fromStdString(error))
                                    .toStdString();
        } else {
            impl_->picks_note = "picks saved";
        }
        impl_->canvas->update();
    });
    connect(impl_->load_picks_button, &QPushButton::clicked, this, [this] {
        const QString path = QFileDialog::getOpenFileName(
            this, tr("Load horizon picks"), QString(), tr("Horizon picks (*.json)"));
        if (path.isEmpty()) {
            return;
        }
        std::string error;
        const PicksLoadStatus status = load_picks(path.toStdString(), error);
        if (status == PicksLoadStatus::error) {
            impl_->picks_note = tr("picks load failed: %1")
                                    .arg(QString::fromStdString(error))
                                    .toStdString();
        } else if (status == PicksLoadStatus::mismatched_volume) {
            impl_->picks_note = "picks loaded (different source volume)";
        } else {
            impl_->picks_note = "picks loaded";
        }
        impl_->canvas->update();
    });

    // Worker -> GUI bridge: queued invocation on this widget. Qt drops the
    // call if the widget is destroyed first; the widget destructor joins the
    // worker before QWidget teardown touches shared state.
    impl_->controller = std::make_unique<SliceController>(
        nullptr, 4, [this](const SliceResult& result) {
            QMetaObject::invokeMethod(
                this, [this, result] { handle_result(result); }, Qt::QueuedConnection);
        });
    impl_->set_state(ViewerState::no_source, {});
}

SeismicSliceWidget::~SeismicSliceWidget() {
    // Close order per contract: stop the worker (joins; no sink afterwards),
    // then QWidget teardown proceeds.
    impl_->controller->request_shutdown();
}

void SeismicSliceWidget::set_volume(std::shared_ptr<pwb::viz::ISeismicVolume> volume,
                                    VolumeIdentity identity, std::uint64_t revision) {
    for (auto* dialog : findChildren<QDialog*>("arbitrarySectionDialog", Qt::FindDirectChildrenOnly))
        delete dialog; // cancel/join extraction before releasing the old survey
    volume = serialized_volume(std::move(volume));
    impl_->source = volume;
    impl_->identity = std::move(identity);
    impl_->volume_revision_value = revision;
    impl_->geometry.reset();
    impl_->plane = SliceResult{};
    impl_->image = QImage();
    impl_->clear_attribute_view(); // volume swap: pinned attribute is stale
    impl_->invalidate_clip_cache(); // volume swap: no inherited P(100-p)/P(p)
    impl_->wiggle_cache_valid = false;
    if (!volume) {
        impl_->picks.picks.clear(); // picks without a source are meaningless
        impl_->pick_drag_index.reset();
        impl_->refresh_pick_markers();
        impl_->controller->set_source(nullptr);
        impl_->set_state(ViewerState::no_source, {});
        impl_->status_label->setText(QStringLiteral("no volume"));
        return;
    }
    impl_->geometry = volume->geometry();
    // Source swap: the controller bumps the epoch, drops queued work and
    // cached planes; late results from the previous volume are discarded on
    // epoch mismatch and can never reach the display.
    impl_->controller->set_source(std::move(volume));
    const auto& geometry = *impl_->geometry;
    if (geometry.shape[0] <= 0 || geometry.shape[1] <= 0 || geometry.shape[2] <= 0) {
        impl_->set_state(ViewerState::empty, "zero extent on some axis");
        impl_->status_label->setText(QStringLiteral("empty volume"));
        return;
    }
    const std::size_t a = pwb::viz::axis_index(impl_->axis);
    impl_->index = std::clamp<std::int64_t>(impl_->index, 0, geometry.shape[a] - 1);
    impl_->updating_controls = true;
    impl_->index_slider->setRange(0, static_cast<int>(geometry.shape[a]) - 1);
    impl_->index_spin->setRange(0, static_cast<int>(geometry.shape[a]) - 1);
    impl_->updating_controls = false;
    impl_->sync_index_controls();
    impl_->update_coordinate_label();
    impl_->set_state(ViewerState::loading, {});
    impl_->resubmit();
    impl_->status_label->setText(
        QStringLiteral("volume %1 rev %2")
            .arg(QString::fromStdString(impl_->identity.volume_id))
            .arg(impl_->volume_revision_value));
}

SectionProfileWidget* SeismicSliceWidget::open_polyline_section(
    const std::vector<std::pair<double,double>>& vertices) {
    if (!impl_->source || !impl_->geometry) return nullptr;
    const auto& geometry = *impl_->geometry;
    if (vertices.size() < 2 || geometry.step[0] == 0 || geometry.step[1] == 0)
        throw std::invalid_argument("a nondegenerate survey and at least two vertices are required");
    std::vector<std::pair<double,double>> indices;
    for (const auto& [il,xl] : vertices) {
        const double i=(il-geometry.origin[0])/geometry.step[0];
        const double x=(xl-geometry.origin[1])/geometry.step[1];
        if (!std::isfinite(i)||!std::isfinite(x)||i<0||x<0||i>geometry.shape[0]-1||x>geometry.shape[1]-1)
            throw std::invalid_argument("arbitrary-line vertex lies outside the survey");
        indices.emplace_back(i,x);
    }
    bool distinct = false;
    for(std::size_t k=1;k<indices.size();++k)
        distinct = distinct || std::hypot(indices[k].first-indices[k-1].first,indices[k].second-indices[k-1].second)>=0.01;
    if(!distinct) throw std::invalid_argument("arbitrary line has no nonzero segment");
    auto* dialog = new QDialog(this);
    dialog->setObjectName("arbitrarySectionDialog");
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowTitle(tr("Arbitrary section — %1").arg(QString::fromStdString(impl_->identity.volume_id)));
    auto* profile = new SectionProfileWidget(dialog);
    auto* layout = new QVBoxLayout(dialog); layout->addWidget(profile);
    profile->set_color_map(impl_->color_map_name);
    profile->load_polyline(impl_->source,std::move(indices));
    dialog->resize(950,620); dialog->show();
    return profile;
}

void SeismicSliceWidget::clear_volume() { set_volume(nullptr, VolumeIdentity{}, 0); }

void SeismicSliceWidget::set_axis(pwb::viz::VolumeAxis axis) {
    if (impl_->geometry &&
        impl_->geometry->shape[pwb::viz::axis_index(axis)] < 1) {
        return; // zero-extent axis: nothing to show (clamp guard)
    }
    if (axis == impl_->axis && impl_->geometry) {
        impl_->sync_axis_combo();
        return;
    }
    impl_->axis = axis;
    impl_->sync_axis_combo();
    impl_->invalidate_clip_cache(); // sibling reuse is per volume + axis
    if (impl_->display_mode == DisplayMode::wiggle && !impl_->section_view()) {
        // Leaving the section views turns wiggle off (map view has no
        // vertical sample axis to wiggle along).
        impl_->display_mode = DisplayMode::variable_density;
        impl_->updating_controls = true;
        impl_->mode_combo->setCurrentIndex(0);
        impl_->updating_controls = false;
    }
    if (impl_->geometry) {
        const std::size_t a = pwb::viz::axis_index(axis);
        const std::int64_t extent = impl_->geometry->shape[a];
        impl_->index = std::clamp<std::int64_t>(impl_->index, 0, extent - 1);
        impl_->updating_controls = true;
        impl_->index_slider->setRange(0, static_cast<int>(extent) - 1);
        impl_->index_spin->setRange(0, static_cast<int>(extent) - 1);
        impl_->updating_controls = false;
        impl_->sync_index_controls();
        impl_->set_state(ViewerState::loading, {});
        impl_->resubmit();
    }
    impl_->update_coordinate_label();
}

void SeismicSliceWidget::set_slice_index(std::int64_t index) {
    if (!impl_->geometry || impl_->geometry->shape[pwb::viz::axis_index(impl_->axis)] < 1) {
        return; // zero-extent axis: nothing to select (clamp guard)
    }
    const std::size_t a = pwb::viz::axis_index(impl_->axis);
    const std::int64_t clamped =
        std::clamp<std::int64_t>(index, 0, impl_->geometry->shape[a] - 1);
    if (clamped == impl_->index) {
        return;
    }
    impl_->index = clamped;
    impl_->sync_index_controls();
    impl_->update_coordinate_label();
    impl_->set_state(ViewerState::loading, {});
    impl_->resubmit();
}

void SeismicSliceWidget::set_color_map(std::string_view name) {
    if (color_lut(name).empty()) {
        return; // unknown colormap is a no-op (contract)
    }
    impl_->color_map_name = std::string(name);
    impl_->lut = color_lut(name);
    const int row = impl_->cmap_combo->findText(
        QString::fromUtf8(impl_->color_map_name.c_str()));
    if (row >= 0 && row != impl_->cmap_combo->currentIndex()) {
        impl_->updating_controls = true;
        impl_->cmap_combo->setCurrentIndex(row);
        impl_->updating_controls = false;
    }
    impl_->apply_color_table();
    impl_->sync_colorbar();
    impl_->canvas->update();
}

void SeismicSliceWidget::set_auto_range() {
    impl_->explicit_range = false;
    impl_->updating_controls = true;
    impl_->explicit_range_check->setChecked(false);
    impl_->range_min_spin->setEnabled(false);
    impl_->range_max_spin->setEnabled(false);
    impl_->updating_controls = false;
    if (impl_->geometry) {
        impl_->set_state(ViewerState::loading, {});
        impl_->resubmit();
    }
}

void SeismicSliceWidget::set_explicit_range(double min, double max) {
    if (!(min < max) || !std::isfinite(min) || !std::isfinite(max)) {
        return; // contract: invalid ranges are a no-op
    }
    impl_->explicit_range = true;
    impl_->range_min = min;
    impl_->range_max = max;
    impl_->updating_controls = true;
    impl_->explicit_range_check->setChecked(true);
    impl_->range_min_spin->setValue(min);
    impl_->range_max_spin->setValue(max);
    impl_->range_min_spin->setEnabled(true);
    impl_->range_max_spin->setEnabled(true);
    impl_->updating_controls = false;
    if (impl_->geometry) {
        impl_->set_state(ViewerState::loading, {});
        impl_->resubmit();
    }
}

void SeismicSliceWidget::reset_view() {
    set_auto_range();
    impl_->canvas->fit_to_image();
    impl_->canvas->update();
}

void SeismicSliceWidget::set_view_transform(double scale, double offset_x,
                                            double offset_y) {
    impl_->canvas->set_transform(scale, offset_x, offset_y);
}

double SeismicSliceWidget::view_scale() const { return impl_->canvas->scale(); }
double SeismicSliceWidget::view_offset_x() const { return impl_->canvas->offset_x(); }
double SeismicSliceWidget::view_offset_y() const { return impl_->canvas->offset_y(); }

void SeismicSliceWidget::set_selection_callback(SelectionCallback callback) {
    impl_->selection_callback = std::move(callback);
}

void SeismicSliceWidget::set_time_depth_relation(std::optional<LinearTimeDepth> relation) {
    impl_->relation = relation;
}

bool SeismicSliceWidget::apply_selection(const SliceSelectionEvent& event) {
    if (event.origin == impl_->origin) {
        return true; // own echo: accepted, no view change, never re-emitted
    }
    if (!impl_->geometry) {
        return false;
    }
    if (!event.document_id.empty() && !impl_->identity.volume_id.empty() &&
        event.document_id != impl_->identity.volume_id) {
        return false; // addresses a different volume
    }
    if (event.revision < impl_->volume_revision_value) {
        return false; // stale selection from an older revision
    }
    if (event.axis != impl_->axis) {
        set_axis(event.axis);
    }
    if (event.index != impl_->index) {
        set_slice_index(event.index);
    }
    // Programmatic application never emits (feedback-loop rule).
    return true;
}

ViewerState SeismicSliceWidget::state() const { return impl_->state; }
std::string SeismicSliceWidget::last_diagnostic() const { return impl_->diagnostic; }
pwb::viz::VolumeAxis SeismicSliceWidget::axis() const { return impl_->axis; }
std::int64_t SeismicSliceWidget::slice_index() const { return impl_->index; }
std::string SeismicSliceWidget::color_map() const { return impl_->color_map_name; }
std::uint64_t SeismicSliceWidget::volume_revision() const {
    return impl_->volume_revision_value;
}
VolumeIdentity SeismicSliceWidget::volume_identity() const { return impl_->identity; }
ControllerStats SeismicSliceWidget::controller_stats() const {
    return impl_->controller->stats();
}

const QImage& SeismicSliceWidget::slice_image() const { return impl_->image; }

double SeismicSliceWidget::axis_coordinate(std::int64_t index) const {
    if (!impl_->geometry) {
        return 0.0;
    }
    return impl_->geometry->axis_value(impl_->axis, index);
}

std::string SeismicSliceWidget::viewer_origin() const { return impl_->origin; }

bool SeismicSliceWidget::plane_point_at(int image_x, int image_y, PlanePoint& out) const {
    if (impl_->image.isNull() || !impl_->geometry) {
        return false;
    }
    if (image_x < 0 || image_x >= impl_->image.width() || image_y < 0 ||
        image_y >= impl_->image.height()) {
        return false;
    }
    const PlaneAxes axes = plane_axes(*impl_->geometry, impl_->axis);
    out.row_coordinate = impl_->geometry->axis_value(axes.row, image_y);
    out.col_coordinate = impl_->geometry->axis_value(axes.col, image_x);
    out.row_unit = axis_unit_for(*impl_->geometry, axes.row);
    out.col_unit = axis_unit_for(*impl_->geometry, axes.col);
    const std::int64_t flat =
        plane_flat_index(impl_->axis, impl_->plane.cols, image_x, image_y);
    if (flat >= 0 && flat < static_cast<std::int64_t>(impl_->plane.values.size())) {
        out.value = impl_->plane.values[static_cast<std::size_t>(flat)];
        out.has_value = true;
    } else {
        out.has_value = false;
    }
    return true;
}

// --- SliceCanvas callbacks --------------------------------------------------

void SeismicSliceWidget::report_cursor(const QPointF& image_point) {
    if (!impl_->geometry || impl_->image.isNull()) {
        return;
    }
    PlanePoint point;
    if (!plane_point_at(static_cast<int>(std::floor(image_point.x())),
                        static_cast<int>(std::floor(image_point.y())), point)) {
        impl_->status_label->setText(QString());
        return;
    }
    const PlaneAxes axes = plane_axes(*impl_->geometry, impl_->axis);
    QString text =
        QString::fromUtf8(axis_display_name(axes.row)) + " " +
        QString::fromStdString(format_value(point.row_coordinate, point.row_unit)) +
        " · " + QString::fromUtf8(axis_display_name(axes.col)) + " " +
        QString::fromStdString(format_value(point.col_coordinate, point.col_unit));
    if (point.has_value) {
        text += " · value " + QString::number(point.value, 'g', 7);
    }
    impl_->status_label->setText(text);
}

void SeismicSliceWidget::report_click_selection(const QPointF& image_point) {
    if (!impl_->geometry) {
        return;
    }
    SliceSelectionEvent event;
    event.origin = impl_->origin;
    event.document_id = impl_->identity.volume_id;
    event.revision = impl_->volume_revision_value;
    event.axis = impl_->axis;
    event.index = impl_->index;
    event.axis_coordinate = impl_->geometry->axis_value(impl_->axis, impl_->index);
    event.axis_unit = axis_unit_for(*impl_->geometry, impl_->axis);
    PlanePoint point;
    if (plane_point_at(static_cast<int>(std::floor(image_point.x())),
                       static_cast<int>(std::floor(image_point.y())), point)) {
        event.has_point = true;
        event.row_coordinate = point.row_coordinate;
        event.col_coordinate = point.col_coordinate;
        event.row_unit = point.row_unit;
        event.col_unit = point.col_unit;
    }
    event.domain = unit_kind(impl_->geometry->unit) == UnitKind::length
                       ? pwb::viz::DepthDomainKind::measured_depth
                       : pwb::viz::DepthDomainKind::time;
    event.conversion = ConversionStatus::native;
    if (impl_->selection_callback) {
        impl_->selection_callback(event);
    }
}

void SeismicSliceWidget::report_drag_selection(const QPointF& from, const QPointF& to) {
    if (!impl_->geometry) {
        return;
    }
    // Shift+drag on section views selects a sample-axis (time) interval: the
    // vertical image axis is the sample axis there. The sample slice view has
    // the inline axis vertical, so drags select no time range.
    const PlaneAxes axes = plane_axes(*impl_->geometry, impl_->axis);
    if (axes.row != VolumeAxis::sample) {
        return;
    }
    const auto clamp_row = [&](double v) {
        return std::clamp<double>(std::floor(v), 0.0,
                                  static_cast<double>(axes.row_count - 1));
    };
    const double top = impl_->geometry->axis_value(
        VolumeAxis::sample, static_cast<std::int64_t>(clamp_row(from.y())));
    const double bottom = impl_->geometry->axis_value(
        VolumeAxis::sample, static_cast<std::int64_t>(clamp_row(to.y())));

    SliceSelectionEvent event;
    event.origin = impl_->origin;
    event.document_id = impl_->identity.volume_id;
    event.revision = impl_->volume_revision_value;
    event.axis = impl_->axis;
    event.index = impl_->index;
    event.axis_coordinate = impl_->geometry->axis_value(impl_->axis, impl_->index);
    event.axis_unit = axis_unit_for(*impl_->geometry, impl_->axis);
    event.has_time_range = true;
    event.time_top = std::min(top, bottom);
    event.time_bottom = std::max(top, bottom);
    event.time_unit = impl_->geometry->unit;
    event.domain = unit_kind(impl_->geometry->unit) == UnitKind::length
                       ? pwb::viz::DepthDomainKind::measured_depth
                       : pwb::viz::DepthDomainKind::time;
    // Explicit conversion policy: time/length never cross implicitly. With a
    // LinearTimeDepth relation the interval converts to meters; without one a
    // length-domain consumer sees not_convertible (never m-as-ms).
    const UnitKind kind = unit_kind(impl_->geometry->unit);
    if (kind == UnitKind::length) {
        event.conversion = ConversionStatus::native;
    } else if (impl_->relation.has_value()) {
        const double origin_ms = impl_->relation->origin_ms;
        const double ms_per_m = impl_->relation->ms_per_m;
        event.converted_top = (event.time_top - origin_ms) / ms_per_m;
        event.converted_bottom = (event.time_bottom - origin_ms) / ms_per_m;
        event.converted_unit = "m";
        event.conversion = ConversionStatus::converted;
    } else {
        event.conversion = ConversionStatus::not_convertible;
    }
    if (impl_->selection_callback) {
        impl_->selection_callback(event);
    }
}

// --- worker results (GUI thread, queued) ------------------------------------

void SeismicSliceWidget::handle_result(const SliceResult& result) {
    if (impl_->controller == nullptr || result.epoch != impl_->controller->epoch()) {
        return; // stale result from before a source swap: never applied
    }
    if (!result.ok) {
        // Keep the last good image visible; the failed state + retained
        // diagnostic is the visible status (no white-image pretend success).
        impl_->set_state(ViewerState::failed, result.diagnostic);
        return;
    }
    impl_->plane = result;
    // Pinning contract: an attribute view computed for a different slice or
    // volume revision is dropped when the new plane arrives — the widget
    // never paints a stale attribute over a new slice.
    if (impl_->attribute_active_flag &&
        (result.axis != impl_->attribute_axis || result.index != impl_->attribute_index ||
         impl_->volume_revision_value != impl_->attribute_revision)) {
        impl_->clear_attribute_view();
    }
    if (!impl_->geometry || result.indexed.empty() || result.rows <= 0 ||
        result.cols <= 0) {
        impl_->image = QImage();
    } else {
        // Lay the canonical plane out in the frozen display orientation
        // (section views transpose: time runs down the image).
        const PlaneAxes axes = plane_axes(*impl_->geometry, result.axis);
        const int width = static_cast<int>(axes.col_count);
        const int height = static_cast<int>(axes.row_count);
        std::vector<std::uint8_t> display(
            static_cast<std::size_t>(width) * static_cast<std::size_t>(height), 0);
        if (impl_->clip_pct_enabled && !impl_->explicit_range) {
            // VIZ-D parity path (profile_vd._renormalize). The degenerate
            // pre-check runs on EVERY plane (before the cache), exactly like
            // the Python dmax == dmin early return:
            //   * constant finite plane -> all-zero indexes, NaN included
            //     (Python bypasses ColormapManager entirely);
            //   * all-invalid plane -> finite 0 / NaN centre via a NaN range
            //     (NOT cached — deliberate deviation: the Python cache
            //     would poison sibling slices with (nan, nan); C++
            //     recomputes so the next good slice recovers).
            bool have_finite = false;
            double dmin = 0.0;
            double dmax = 0.0;
            for (const float value : result.values) {
                if (std::isfinite(value)) {
                    const double v = static_cast<double>(value);
                    if (!have_finite) {
                        dmin = dmax = v;
                        have_finite = true;
                    } else {
                        dmin = std::min(dmin, v);
                        dmax = std::max(dmax, v);
                    }
                }
            }
            double lo = 0.0;
            double hi = 0.0;
            bool plain_zeros = false;
            if (have_finite && dmin == dmax) {
                plain_zeros = true; // constant plane: zeros, no NaN remap
                lo = dmin;
                hi = dmax;
            } else if (have_finite) {
                const std::string key = impl_->clip_volume_key();
                if (!(impl_->clip_cache.valid && impl_->clip_cache.volume_key == key &&
                      impl_->clip_cache.axis == result.axis &&
                      impl_->clip_cache.rows == result.rows &&
                      impl_->clip_cache.cols == result.cols &&
                      impl_->clip_cache.pct == impl_->clip_pct)) {
                    const display::ClipRange range =
                        display::percentile_clip_range(result.values, impl_->clip_pct);
                    impl_->clip_cache.valid = !range.degenerate;
                    impl_->clip_cache.lo = range.lo;
                    impl_->clip_cache.hi = range.hi;
                    impl_->clip_cache.volume_key = key;
                    impl_->clip_cache.axis = result.axis;
                    impl_->clip_cache.rows = result.rows;
                    impl_->clip_cache.cols = result.cols;
                    impl_->clip_cache.pct = impl_->clip_pct;
                }
                if (impl_->clip_cache.valid) {
                    lo = impl_->clip_cache.lo;
                    hi = impl_->clip_cache.hi;
                } else {
                    lo = dmin;
                    hi = dmax;
                }
            } else {
                lo = std::numeric_limits<double>::quiet_NaN();
                hi = std::numeric_limits<double>::quiet_NaN();
            }
            if (plain_zeros) {
                // Constant plane: profile_vd's early return (NaN -> 0 too).
                for (std::int64_t y = 0; y < axes.row_count; ++y) {
                    for (std::int64_t x = 0; x < axes.col_count; ++x) {
                        display[static_cast<std::size_t>(y * axes.col_count + x)] = 0;
                    }
                }
            } else {
                const int polarity = impl_->polarity_normal ? 1 : -1;
                std::vector<float> display_values(result.values.size());
                for (std::size_t i = 0; i < result.values.size(); ++i) {
                    display_values[i] = polarity * result.values[i];
                }
                const std::vector<std::uint8_t> parity =
                    display::normalize_to_index(display_values, lo, hi);
                for (std::int64_t y = 0; y < axes.row_count; ++y) {
                    for (std::int64_t x = 0; x < axes.col_count; ++x) {
                        const std::int64_t flat =
                            plane_flat_index(result.axis, result.cols, x, y);
                        display[static_cast<std::size_t>(y * axes.col_count + x)] =
                            parity[static_cast<std::size_t>(flat)];
                    }
                }
            }
            impl_->displayed_lo = lo;
            impl_->displayed_hi = hi;
        } else {
            // Frozen v3 path: bytes straight from map_slice_to_indexed8
            // (non-finite -> index 0). Kept byte-identical to the frozen v3
            // contract; the colormap.py NaN-at-centre rule applies only to
            // the percentile parity path above (declared in the ledger).
            for (std::int64_t y = 0; y < axes.row_count; ++y) {
                for (std::int64_t x = 0; x < axes.col_count; ++x) {
                    const std::int64_t flat =
                        plane_flat_index(result.axis, result.cols, x, y);
                    display[static_cast<std::size_t>(y * axes.col_count + x)] =
                        result.indexed[static_cast<std::size_t>(flat)];
                }
            }
            impl_->displayed_lo = result.value_min;
            impl_->displayed_hi = result.value_max;
        }
        QImage raw(display.data(), width, height, width, QImage::Format_Indexed8);
        impl_->image = raw.copy(); // own the bytes before the local buffer dies
        impl_->apply_color_table();
    }
    impl_->refresh_wiggle();
    rebuild_wiggle(impl_->canvas->width(), impl_->canvas->height());
    impl_->refresh_pick_markers();
    impl_->sync_colorbar();
    impl_->set_state(result.degenerate ? ViewerState::degenerate : ViewerState::ok,
                     result.diagnostic);
}

// --- VIZ-D advanced display ---------------------------------------------------

void SeismicSliceWidget::set_display_mode(DisplayMode mode) {
    if (mode == DisplayMode::wiggle && !impl_->section_view()) {
        return; // wiggle is a section-view renderer (sample axis vertical)
    }
    if (mode == impl_->display_mode) {
        return;
    }
    // The wiggle renderer draws waveforms only — a pinned attribute / fusion
    // image is never composited in that branch. Abandon the pin on the mode
    // switch instead of leaving an invisible-but-active attribute view that
    // still refuses npy/csv export ("属性视图激活中") while painting nothing.
    if (mode == DisplayMode::wiggle && impl_->attribute_active_flag) {
        impl_->clear_attribute_view();
    }
    impl_->display_mode = mode;
    impl_->updating_controls = true;
    impl_->mode_combo->setCurrentIndex(mode == DisplayMode::wiggle ? 1 : 0);
    impl_->updating_controls = false;
    impl_->refresh_wiggle();
    rebuild_wiggle(impl_->canvas->width(), impl_->canvas->height());
    impl_->refresh_overlay();
}

DisplayMode SeismicSliceWidget::display_mode() const { return impl_->display_mode; }

void SeismicSliceWidget::set_polarity(bool normal) {
    if (normal == impl_->polarity_normal) {
        return;
    }
    impl_->polarity_normal = normal;
    impl_->updating_controls = true;
    impl_->polarity_check->setChecked(!normal);
    impl_->updating_controls = false;
    if (impl_->clip_pct_enabled && !impl_->explicit_range && !impl_->plane.values.empty()) {
        handle_result(impl_->plane); // re-normalize through the same range
    }
    impl_->refresh_wiggle();
    rebuild_wiggle(impl_->canvas->width(), impl_->canvas->height());
    impl_->refresh_overlay();
}

bool SeismicSliceWidget::polarity_normal() const { return impl_->polarity_normal; }

void SeismicSliceWidget::set_clip_percentile_enabled(bool enabled) {
    if (enabled == impl_->clip_pct_enabled) {
        return;
    }
    impl_->clip_pct_enabled = enabled;
    impl_->updating_controls = true;
    impl_->clip_check->setChecked(enabled);
    impl_->clip_spin->setEnabled(enabled);
    impl_->updating_controls = false;
    if (!impl_->plane.values.empty()) {
        handle_result(impl_->plane); // re-map the retained plane
    }
    impl_->sync_colorbar();
    impl_->refresh_overlay();
}

bool SeismicSliceWidget::clip_percentile_enabled() const {
    return impl_->clip_pct_enabled;
}

void SeismicSliceWidget::set_clip_percentile(double pct) {
    pct = std::clamp(pct, 1.0, 99.0);
    if (std::abs(pct - impl_->clip_pct) < 0.01) {
        return; // profile_vd set_clip_percentile dead zone
    }
    impl_->clip_pct = pct;
    impl_->invalidate_clip_cache();
    impl_->updating_controls = true;
    impl_->clip_spin->setValue(pct);
    impl_->updating_controls = false;
    if (impl_->clip_pct_enabled && !impl_->plane.values.empty()) {
        handle_result(impl_->plane);
    }
}

double SeismicSliceWidget::clip_percentile() const { return impl_->clip_pct; }

void SeismicSliceWidget::set_wiggle_gain(double gain) {
    if (!(gain > 0.0) || !std::isfinite(gain)) {
        return; // positive finite, else no-op (set_gain ValueError parity)
    }
    if (gain == impl_->wiggle_gain) {
        return;
    }
    impl_->wiggle_gain = gain;
    impl_->updating_controls = true;
    impl_->gain_spin->setValue(gain);
    impl_->updating_controls = false;
    impl_->refresh_wiggle();
    rebuild_wiggle(impl_->canvas->width(), impl_->canvas->height());
}

double SeismicSliceWidget::wiggle_gain() const { return impl_->wiggle_gain; }

// --- VIZ-D horizon picking ----------------------------------------------------

void SeismicSliceWidget::enable_picking(bool enabled) {
    impl_->picking = enabled;
    impl_->updating_controls = true;
    impl_->pick_check->setChecked(enabled);
    impl_->updating_controls = false;
    impl_->canvas->set_picking(enabled);
    impl_->canvas->update();
}

bool SeismicSliceWidget::picking_enabled() const { return impl_->picking; }

void SeismicSliceWidget::add_pick(horizon::HorizonPick pick) {
    if (impl_->picks.picks.empty()) {
        // First pick stamps the source binding (stable identity for the
        // save/reopen round trip).
        impl_->picks.volume_id = impl_->identity.volume_id;
        impl_->picks.volume_revision = impl_->volume_revision_value;
        impl_->picks.axis_name = impl_->axis == VolumeAxis::inline_ ? "inline"
                                  : impl_->axis == VolumeAxis::crossline ? "crossline"
                                                                          : "sample";
        impl_->picks.slice_index = impl_->index;
        impl_->picks.time_unit = impl_->geometry ? impl_->geometry->unit : std::string();
        impl_->picks_note.clear();
    }
    horizon::add_pick(impl_->picks, pick);
    impl_->refresh_pick_markers();
    impl_->refresh_overlay();
}

void SeismicSliceWidget::clear_picks() {
    horizon::clear_picks(impl_->picks);
    impl_->picks_note.clear();
    impl_->pick_drag_index.reset();
    impl_->refresh_pick_markers();
    impl_->refresh_overlay();
}

const horizon::HorizonPickSet& SeismicSliceWidget::picks() const { return impl_->picks; }

bool SeismicSliceWidget::save_picks(const std::string& path, std::string& error) {
    if (impl_->picks.picks.empty() && impl_->identity.volume_id.empty() &&
        impl_->picks.volume_id.empty()) {
        error = "nothing to save (no picks, no binding)";
        return false;
    }
    // Refresh the binding from the CURRENT viewer when one is bound; a
    // viewer without a volume keeps the binding the set already carries
    // (e.g. loaded from a file) instead of wiping it to empty.
    if (!impl_->identity.volume_id.empty()) {
        impl_->picks.volume_id = impl_->identity.volume_id;
        impl_->picks.volume_revision = impl_->volume_revision_value;
        impl_->picks.axis_name = impl_->axis == VolumeAxis::inline_ ? "inline"
                                  : impl_->axis == VolumeAxis::crossline ? "crossline"
                                                                          : "sample";
        impl_->picks.slice_index = impl_->index;
        impl_->picks.time_unit = impl_->geometry ? impl_->geometry->unit : std::string();
    }
    const std::string text = horizon::to_json(impl_->picks);
    QFile file(QString::fromStdString(path));
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        error = "cannot open file for writing";
        return false;
    }
    if (file.write(text.data(), static_cast<qint64>(text.size())) !=
        static_cast<qint64>(text.size())) {
        error = "short write";
        return false;
    }
    return true;
}

PicksLoadStatus SeismicSliceWidget::load_picks(const std::string& path, std::string& error) {
    QFile file(QString::fromStdString(path));
    if (!file.open(QIODevice::ReadOnly)) {
        error = "cannot open file";
        return PicksLoadStatus::error;
    }
    const QByteArray bytes = file.readAll();
    const horizon::PickParseResult parsed =
        horizon::from_json(std::string_view(bytes.constData(), static_cast<std::size_t>(bytes.size())));
    if (!parsed.ok) {
        error = parsed.error;
        return PicksLoadStatus::error;
    }
    const bool mismatch = !impl_->identity.volume_id.empty() &&
                          !parsed.set.volume_id.empty() &&
                          parsed.set.volume_id != impl_->identity.volume_id;
    impl_->picks = parsed.set;
    impl_->pick_drag_index.reset();
    impl_->refresh_pick_markers();
    impl_->refresh_overlay();
    return mismatch ? PicksLoadStatus::mismatched_volume : PicksLoadStatus::ok;
}

std::pair<double, double> SeismicSliceWidget::displayed_range() const {
    if (impl_->image.isNull()) {
        return {0.0, 0.0};
    }
    return {impl_->displayed_lo, impl_->displayed_hi};
}

std::vector<QPointF> SeismicSliceWidget::pick_markers() const {
    return impl_->pick_marker_cache;
}

// Canvas click -> survey coordinates, dispatching per the slice type
// (seismic_view._on_horizon_picked parity: position is the survey line
// number of the shown slice; h/v map to the remaining axes).
bool image_point_to_pick(const pwb::viz::VolumeGeometryV1& geometry, VolumeAxis axis,
                         std::int64_t slice_index, double image_x, double image_y,
                         horizon::HorizonPick& out) {
    const PlaneAxes axes = plane_axes(geometry, axis);
    const double h_value = geometry.axis_value(axes.col, static_cast<std::int64_t>(std::lround(image_x)));
    const double v_value = geometry.axis_value(axes.row, static_cast<std::int64_t>(std::lround(image_y)));
    const double position = geometry.axis_value(axis, slice_index);
    switch (axis) {
    case VolumeAxis::inline_:
        out = {position, h_value, v_value};
        return true;
    case VolumeAxis::crossline:
        out = {h_value, position, v_value};
        return true;
    case VolumeAxis::sample:
        out = {v_value, h_value, position};
        return true;
    }
    return false;
}

void SeismicSliceWidget::report_pick_press(const QPointF& image_point) {
    if (!impl_->geometry) {
        return;
    }
    // Near an existing marker (6 image px): begin an edit drag.
    double best = 6.0;
    std::optional<std::size_t> hit;
    for (std::size_t i = 0; i < impl_->pick_marker_cache.size(); ++i) {
        const double d = std::hypot(impl_->pick_marker_cache[i].x() - image_point.x(),
                                    impl_->pick_marker_cache[i].y() - image_point.y());
        if (d <= best) {
            best = d;
            hit = i;
        }
    }
    if (hit.has_value()) {
        impl_->pick_drag_index = hit;
        return;
    }
    horizon::HorizonPick pick;
    if (image_point_to_pick(*impl_->geometry, impl_->axis, impl_->index, image_point.x(),
                            image_point.y(), pick)) {
        add_pick(pick);
    }
}

void SeismicSliceWidget::report_pick_drag(const QPointF& image_point) {
    if (!impl_->geometry || !impl_->pick_drag_index.has_value()) {
        return;
    }
    horizon::HorizonPick pick;
    if (image_point_to_pick(*impl_->geometry, impl_->axis, impl_->index, image_point.x(),
                            image_point.y(), pick)) {
        static_cast<void>(
            horizon::move_pick(impl_->picks, *impl_->pick_drag_index, pick));
        impl_->refresh_pick_markers();
        impl_->refresh_overlay();
    }
}

bool SeismicSliceWidget::report_pick_context_menu(const QPointF& image_point) {
    if (!impl_->geometry) {
        return false;
    }
    double best = 6.0;
    std::optional<std::size_t> hit;
    for (std::size_t i = 0; i < impl_->pick_marker_cache.size(); ++i) {
        const double d = std::hypot(impl_->pick_marker_cache[i].x() - image_point.x(),
                                    impl_->pick_marker_cache[i].y() - image_point.y());
        if (d <= best) {
            best = d;
            hit = i;
        }
    }
    if (!hit.has_value()) {
        return false;
    }
    // Delete by exact index of the hit marker (markers and picks are 1:1).
    if (*hit < impl_->picks.picks.size()) {
        impl_->picks.picks.erase(impl_->picks.picks.begin() +
                                 static_cast<std::ptrdiff_t>(*hit));
        impl_->pick_drag_index.reset();
        impl_->refresh_pick_markers();
        impl_->refresh_overlay();
        return true;
    }
    return false;
}

void SeismicSliceWidget::rebuild_wiggle(int width, int height) {
    if (impl_->display_mode != DisplayMode::wiggle || !impl_->geometry ||
        impl_->plane.values.empty() || width < 2 || height < 2) {
        impl_->wiggle_cache_valid = false;
        return;
    }
    // The display orientation puts x = trace axis, y = sample for section
    // views; the plane buffer itself is canonical (rows x cols), so build
    // the (n_samples, n_traces) input the same way plane_point_at reads it.
    const PlaneAxes axes = plane_axes(*impl_->geometry, impl_->plane.axis);
    const std::int64_t n_samples = axes.row_count; // sample axis vertical
    const std::int64_t n_traces = axes.col_count;
    std::vector<float> section(static_cast<std::size_t>(n_samples * n_traces));
    for (std::int64_t s = 0; s < n_samples; ++s) {
        for (std::int64_t t = 0; t < n_traces; ++t) {
            const std::int64_t flat =
                plane_flat_index(impl_->plane.axis, impl_->plane.cols, t, s);
            section[static_cast<std::size_t>(s * n_traces + t)] =
                impl_->plane.values[static_cast<std::size_t>(flat)];
        }
    }
    const int polarity = impl_->polarity_normal ? 1 : -1;
    impl_->wiggle_cache = display::wiggle_geometry(
        section, n_samples, n_traces, polarity, impl_->wiggle_gain, width, height);
    impl_->wiggle_cache_valid = true;
    impl_->canvas->set_wiggle(&impl_->wiggle_cache);
    impl_->canvas->update();
}

const display::WiggleGeometry* SeismicSliceWidget::wiggle_geometry() const {
    return impl_->wiggle_cache_valid ? &impl_->wiggle_cache : nullptr;
}

// --- VIZ-D attribute / RGB-fusion display (07 line) ---------------------------

SeismicSliceWidget::RetainedPlane SeismicSliceWidget::retained_plane() const {
    RetainedPlane out;
    out.values = impl_->plane.values;
    out.rows = impl_->plane.rows;
    out.cols = impl_->plane.cols;
    out.axis = impl_->plane.axis;
    out.index = impl_->plane.index;
    out.revision = impl_->volume_revision_value;
    return out;
}

bool SeismicSliceWidget::set_attribute_plane(std::span<const float> plane,
                                             std::int64_t rows, std::int64_t cols,
                                             std::string_view color_map,
                                             std::string_view label) {
    if (!impl_->attribute_view_shape_ok(rows, cols)) {
        return false;
    }
    if (color_lut(color_map).empty()) {
        impl_->diagnostic = "unknown attribute colormap";
        return false;
    }
    // Attribute rendering mirrors the amplitude VD path minus SEG polarity:
    // percentile clip when enabled, the finite min/max stretch otherwise.
    double lo = 0.0;
    double hi = 0.0;
    if (impl_->clip_pct_enabled) {
        const display::ClipRange range =
            display::percentile_clip_range(plane, impl_->clip_pct);
        if (range.degenerate || !std::isfinite(range.lo) || !std::isfinite(range.hi)) {
            impl_->diagnostic = "attribute plane has no usable value range";
            return false;
        }
        lo = range.lo;
        hi = range.hi;
    } else {
        bool have_finite = false;
        double dmin = 0.0;
        double dmax = 0.0;
        for (const float value : plane) {
            if (std::isfinite(value)) {
                dmin = have_finite ? std::min(dmin, static_cast<double>(value))
                                   : static_cast<double>(value);
                dmax = have_finite ? std::max(dmax, static_cast<double>(value))
                                   : static_cast<double>(value);
                have_finite = true;
            }
        }
        if (!have_finite || !(dmax > dmin)) {
            impl_->diagnostic = "attribute plane has no usable value range";
            return false;
        }
        lo = dmin;
        hi = dmax;
    }

    // Display orientation (section views: time runs down the image), the
    // same canonical->display mapping the amplitude raster uses.
    const PlaneAxes axes = plane_axes(*impl_->geometry, impl_->plane.axis);
    const int width = static_cast<int>(axes.col_count);
    const int height = static_cast<int>(axes.row_count);
    std::vector<std::uint8_t> display(static_cast<std::size_t>(width) * static_cast<std::size_t>(height), 0);
    const std::vector<std::uint8_t> indexed =
        display::normalize_to_index(plane, lo, hi);
    for (std::int64_t y = 0; y < axes.row_count; ++y) {
        for (std::int64_t x = 0; x < axes.col_count; ++x) {
            const std::int64_t flat =
                plane_flat_index(impl_->plane.axis, impl_->plane.cols, x, y);
            display[static_cast<std::size_t>(y * axes.col_count + x)] =
                indexed[static_cast<std::size_t>(flat)];
        }
    }
    QImage raw(display.data(), width, height, width, QImage::Format_Indexed8);
    impl_->attribute_image = raw.copy();
    // The attribute renders through its OWN colormap LUT, not the amplitude
    // one: rebuild the color table on the copy.
    const ColorLut attribute_lut = color_lut(color_map);
    QVector<QRgb> table;
    table.reserve(256);
    for (const auto& rgb : attribute_lut) {
        table.push_back(qRgb(rgb[0], rgb[1], rgb[2]));
    }
    impl_->attribute_image.setColorTable(table);

    impl_->attribute_active_flag = true;
    impl_->attribute_label = std::string(label);
    impl_->attribute_axis = impl_->plane.axis;
    impl_->attribute_index = impl_->plane.index;
    impl_->attribute_revision = impl_->volume_revision_value;
    impl_->attribute_lo = lo;
    impl_->attribute_hi = hi;
    impl_->refresh_overlay();
    impl_->sync_colorbar();
    return true;
}

bool SeismicSliceWidget::set_rgb_fusion(std::span<const float> channel_r,
                                        std::span<const float> channel_g,
                                        std::span<const float> channel_b,
                                        std::int64_t rows, std::int64_t cols,
                                        double clip_pct, std::string_view label) {
    if (!impl_->attribute_view_shape_ok(rows, cols)) {
        return false;
    }
    const std::vector<std::uint8_t> fused =
        fusion::fuse_rgb(channel_r, channel_g, channel_b, rows, cols, clip_pct);
    const PlaneAxes axes = plane_axes(*impl_->geometry, impl_->plane.axis);
    const int width = static_cast<int>(axes.col_count);
    const int height = static_cast<int>(axes.row_count);
    std::vector<std::uint8_t> display(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 3, 0);
    for (std::int64_t y = 0; y < axes.row_count; ++y) {
        for (std::int64_t x = 0; x < axes.col_count; ++x) {
            const std::int64_t flat =
                plane_flat_index(impl_->plane.axis, impl_->plane.cols, x, y);
            const std::size_t src = static_cast<std::size_t>(flat) * 3;
            const std::size_t dst =
                (static_cast<std::size_t>(y * axes.col_count + x)) * 3;
            display[dst] = fused[src];
            display[dst + 1] = fused[src + 1];
            display[dst + 2] = fused[src + 2];
        }
    }
    QImage raw(display.data(), width, height, width * 3, QImage::Format_RGB888);
    impl_->attribute_image = raw.copy();

    impl_->attribute_active_flag = true;
    impl_->attribute_label = std::string(label);
    impl_->attribute_axis = impl_->plane.axis;
    impl_->attribute_index = impl_->plane.index;
    impl_->attribute_revision = impl_->volume_revision_value;
    impl_->attribute_lo = 0.0;
    impl_->attribute_hi = 255.0;
    impl_->refresh_overlay();
    impl_->sync_colorbar();
    return true;
}

void SeismicSliceWidget::clear_attribute_view() { impl_->clear_attribute_view(); }

bool SeismicSliceWidget::attribute_active() const { return impl_->attribute_active_flag; }

// --- slice export (07 line) ----------------------------------------------------

bool SeismicSliceWidget::export_slice(const std::string& path, SliceExportFormat format,
                                      std::string& error) {
    error.clear();
    if (path.empty()) {
        error = "empty export path";
        return false;
    }
    if (impl_->plane.values.empty() || !impl_->geometry) {
        error = "nothing displayed to export";
        return false;
    }
    if (format == SliceExportFormat::png) {
        // Real display render of the canvas (the plot area only — controls,
        // sliders and status strips stay out), the widget.grab() parity of
        // the frozen export. Whatever is on screen — amplitude or a pinned
        // attribute/fusion view — is what the png contains.
        const QPixmap shot = impl_->canvas->grab();
        if (shot.isNull()) {
            error = "canvas render failed";
            return false;
        }
        if (!shot.save(QString::fromStdString(path))) {
            error = "png write failed: " + path;
            return false;
        }
        return true;
    }
    if (impl_->attribute_active_flag) {
        // The displayed pixels are the pinned attribute/fusion view, but the
        // retained float plane is the AMPLITUDE data — exporting it here
        // would hand back different numbers than the screen shows. Refuse
        // with the honest remedy instead (png above exports the real view).
        error = "属性视图激活中：数据导出仅支持振幅数据面，请先清除属性视图";
        return false;
    }
    // Data exports use DISPLAY orientation: rows = image vertical axis (the
    // sample axis on section views), cols = horizontal — what was exported
    // is what was on screen.
    const PlaneAxes axes = plane_axes(*impl_->geometry, impl_->plane.axis);
    std::vector<float> oriented(static_cast<std::size_t>(axes.row_count * axes.col_count));
    for (std::int64_t y = 0; y < axes.row_count; ++y) {
        for (std::int64_t x = 0; x < axes.col_count; ++x) {
            const std::int64_t flat =
                plane_flat_index(impl_->plane.axis, impl_->plane.cols, x, y);
            oriented[static_cast<std::size_t>(y * axes.col_count + x)] =
                impl_->plane.values[static_cast<std::size_t>(flat)];
        }
    }
    if (format == SliceExportFormat::npy) {
        return slice_export::write_npy(path, oriented, axes.row_count, axes.col_count,
                                       error);
    }
    return slice_export::write_csv(path, oriented, axes.row_count, axes.col_count, error);
}

// --- view state persistence (07 line) ------------------------------------------

bool SeismicSliceWidget::save_view_state(const std::string& path, std::string& error) {
    SeismicViewState state;
    state.volume_id = impl_->identity.volume_id;
    state.volume_version = impl_->identity.version;
    state.axis = axis_schema_name(impl_->axis);
    state.slice_index = impl_->index;
    state.color_map = impl_->color_map_name;
    state.display_mode = impl_->display_mode == DisplayMode::wiggle ? "wiggle"
                                                                    : "variable_density";
    state.polarity_normal = impl_->polarity_normal;
    state.clip_enabled = impl_->clip_pct_enabled;
    state.clip_percentile = impl_->clip_pct;
    state.wiggle_gain = impl_->wiggle_gain;
    state.auto_range = !impl_->explicit_range;
    state.range_min = impl_->range_min;
    state.range_max = impl_->range_max;
    state.view_scale = impl_->canvas->scale();
    state.view_offset_x = impl_->canvas->offset_x();
    state.view_offset_y = impl_->canvas->offset_y();
    state.picking_enabled = impl_->picking;
    // Embedded pick set (own binding block inside); an unparsable document
    // is a programming error — the codec round-trips its own output.
    const domain::Json picks = domain::Json::parse(horizon::to_json(impl_->picks));
    state.picks = picks;

    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        error = "cannot open file: " + path;
        return false;
    }
    const std::string text = to_json_text(state);
    out.write(text.data(), static_cast<std::streamsize>(text.size()));
    out.close();
    if (!out) {
        error = "write failed: " + path;
        return false;
    }
    return true;
}

SeismicSliceWidget::ViewStateLoadStatus SeismicSliceWidget::load_view_state(
    const std::string& path, std::string& error) {
    error.clear();
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        error = "cannot open file: " + path;
        return ViewStateLoadStatus::error;
    }
    const std::string text((std::istreambuf_iterator<char>(in)),
                           std::istreambuf_iterator<char>());
    SeismicViewState state;
    if (from_json_text(text, state, error) != ViewStateParse::ok) {
        return ViewStateLoadStatus::error;
    }
    // Cross-volume restore is rejected wholesale: a saved view of another
    // body must never reshape this one (anonymous bindings only match
    // anonymous bindings — there is no identity to verify otherwise).
    if (state.volume_id != impl_->identity.volume_id) {
        error = "view state belongs to volume '" + state.volume_id +
                "', current is '" + impl_->identity.volume_id + "'";
        return ViewStateLoadStatus::mismatched_volume;
    }
    // Validate every token BEFORE mutating any state (fail closed).
    VolumeAxis axis;
    DisplayMode mode;
    if (!axis_from_schema_name(state.axis, axis)) {
        error = "unknown axis token: " + state.axis;
        return ViewStateLoadStatus::error;
    }
    if (state.display_mode != "variable_density" && state.display_mode != "wiggle") {
        error = "unknown display mode token: " + state.display_mode;
        return ViewStateLoadStatus::error;
    }
    if (state.display_mode == "wiggle") {
        mode = DisplayMode::wiggle;
    } else {
        mode = DisplayMode::variable_density;
    }
    if (color_lut(state.color_map).empty()) {
        error = "unknown colormap: " + state.color_map;
        return ViewStateLoadStatus::error;
    }
    const horizon::PickParseResult picks = horizon::from_json(state.picks.dump());
    if (!picks.ok) {
        error = "embedded picks invalid: " + picks.error;
        return ViewStateLoadStatus::error;
    }
    // The embedded pick set carries its own volume binding; a non-empty set
    // naming ANOTHER body makes the whole state a cross-body restore (the
    // same rejection rule as the state-level volume_id above).
    if (!picks.set.picks.empty() && !picks.set.volume_id.empty() &&
        picks.set.volume_id != impl_->identity.volume_id) {
        error = "embedded picks belong to volume '" + picks.set.volume_id + "'";
        return ViewStateLoadStatus::mismatched_volume;
    }

    // Apply in dependency order: colormap/range -> mode -> polarity/clip/
    // gain -> slice placement -> transform -> picking + picks. Clamps inside
    // the setters keep out-of-extent indices on the same volume honest.
    set_color_map(state.color_map);
    if (state.auto_range) {
        set_auto_range();
    } else {
        set_explicit_range(state.range_min, state.range_max);
    }
    set_display_mode(mode);
    set_polarity(state.polarity_normal);
    set_clip_percentile(state.clip_percentile);
    set_clip_percentile_enabled(state.clip_enabled);
    set_wiggle_gain(state.wiggle_gain);
    set_axis(axis);
    set_slice_index(state.slice_index);
    set_view_transform(state.view_scale, state.view_offset_x, state.view_offset_y);
    enable_picking(state.picking_enabled);
    impl_->picks = picks.set;
    impl_->refresh_pick_markers();
    impl_->refresh_overlay();
    return ViewStateLoadStatus::ok;
}

} // namespace pwb::seismic_viewer
