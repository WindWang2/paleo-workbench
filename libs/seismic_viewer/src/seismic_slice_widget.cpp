#include <pwb/seismic_viewer/color_maps.hpp>
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFontMetrics>
#include <QHBoxLayout>
#include <QImage>
#include <QLabel>
#include <QMouseEvent>
#include <QPainter>
#include <QPaintEvent>
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
#include <utility>

namespace pwb::seismic_viewer {
namespace {

using pwb::viz::VolumeAxis;

std::string next_viewer_origin() {
    static std::atomic<std::uint64_t> counter{0};
    return "seismic_viewer-" + std::to_string(counter.fetch_add(1));
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
// SliceCanvas: raster painting of the indexed8 slice with zoom/pan. No moc,
// no signals: interaction results are pushed through SeismicSliceWidget.
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
        painter.fillRect(rect(), QColor(24, 24, 24));
        if (image_ != nullptr && !image_->isNull()) {
            painter.setRenderHint(QPainter::SmoothPixmapTransform, false);
            painter.drawImage(rect(), *image_, source_rect());
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
    }

    void wheelEvent(QWheelEvent* event) override {
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
        if (event->button() == Qt::LeftButton) {
            press_pos_ = event->position();
            last_pos_ = event->position();
            dragging_ = false;
        }
    }

    void mouseMoveEvent(QMouseEvent* event) override {
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
    QString overlay_;
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
        canvas->set_image(image.isNull() ? nullptr : &image, overlay);
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
    impl_->cmap_combo->setCurrentIndex(1); // match impl_->color_map_name ("seismic")
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

    impl_->canvas = new SliceCanvas(this);
    impl_->status_label = new QLabel(QStringLiteral("no volume"), this);

    auto* layout = new QVBoxLayout(this);
    layout->addLayout(toolbar);
    layout->addWidget(impl_->canvas, 1);
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
    impl_->identity = std::move(identity);
    impl_->volume_revision_value = revision;
    impl_->geometry.reset();
    impl_->plane = SliceResult{};
    impl_->image = QImage();

    if (!volume) {
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

void SeismicSliceWidget::clear_volume() { set_volume(nullptr, VolumeIdentity{}, 0); }

void SeismicSliceWidget::set_axis(pwb::viz::VolumeAxis axis) {
    if (axis == impl_->axis && impl_->geometry) {
        impl_->sync_axis_combo();
        return;
    }
    impl_->axis = axis;
    impl_->sync_axis_combo();
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
    if (!impl_->geometry) {
        return;
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
        for (std::int64_t y = 0; y < axes.row_count; ++y) {
            for (std::int64_t x = 0; x < axes.col_count; ++x) {
                const std::int64_t flat =
                    plane_flat_index(result.axis, result.cols, x, y);
                display[static_cast<std::size_t>(y * axes.col_count + x)] =
                    result.indexed[static_cast<std::size_t>(flat)];
            }
        }
        QImage raw(display.data(), width, height, width, QImage::Format_Indexed8);
        impl_->image = raw.copy(); // own the bytes before the local buffer dies
        impl_->apply_color_table();
    }
    impl_->set_state(result.degenerate ? ViewerState::degenerate : ViewerState::ok,
                     result.diagnostic);
}

} // namespace pwb::seismic_viewer
