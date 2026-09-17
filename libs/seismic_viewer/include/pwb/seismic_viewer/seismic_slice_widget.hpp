#pragma once

// SeismicSliceWidget — the D-line embeddable 2-D seismic slice host.
//
// A single QWidget showing one inline / crossline / sample slice of a
// lifecycle-controlled pwb::viz::ISeismicVolume with axis selection, index
// slider/spinbox, physical coordinate + unit labels, colormap selection,
// auto/explicit value range, zoom/pan and selection events. Rendering is
// raster Qt (QImage + QPainter); no OpenGL engine. The widget never copies
// the whole volume: it consumes owned slice planes produced off the GUI
// thread by SliceController.
//
// Display layout (frozen v3, tested):
//   axis = inline_    : image x = crossline index, y = sample index (time
//                       increases DOWNWARD, seismic convention)
//   axis = crossline  : image x = inline index,    y = sample index (down)
//   axis = sample     : image x = crossline index, y = inline index (down)
// Plane bytes follow ISeismicVolume canonical row-major order; the QImage is
// width=cols, height=rows with scanline r holding cols indexes.
//
// Mouse: wheel = zoom, left-drag = pan, double-click = reset view,
// click = point selection, Shift+vertical-drag on section views = time-range
// selection. Programmatic selection goes through apply_selection(), which
// updates the view but never re-emits (echo suppression, feedback-loop rule).
//
// No Q_OBJECT on purpose (moc-free host, mirrors the C-line WellLogHost
// precedent): callbacks are std::function; worker results hop to the GUI
// thread via queued QMetaObject::invokeMethod on this widget.

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>

#include <QWidget>

#include <pwb/seismic_viewer/slice_controller.hpp>
#include <pwb/seismic_viewer/slice_selection.hpp>

class QComboBox;
class QDoubleSpinBox;
class QLabel;
class QSlider;
class QSpinBox;

namespace pwb::seismic_viewer {

enum class ViewerState : std::uint8_t {
    no_source,   // no volume set
    empty,       // volume with a zero extent on some axis
    loading,     // request in flight, nothing displayed yet
    ok,          // slice rendered
    degenerate,  // rendered, but stretch degenerate (constant / all-invalid)
    failed       // read failure; last good slice (if any) stays visible dimmed
};

class SeismicSliceWidget final : public QWidget {
public:
    using SelectionCallback = std::function<void(const SliceSelectionEvent&)>;

    explicit SeismicSliceWidget(QWidget* parent = nullptr);
    ~SeismicSliceWidget() override;

    SeismicSliceWidget(const SeismicSliceWidget&) = delete;
    SeismicSliceWidget& operator=(const SeismicSliceWidget&) = delete;

    // --- volume lifecycle (A passes lifecycle-controlled volumes) ----------
    // `identity`/`revision` ride along on every selection event. Swapping the
    // source bumps the controller epoch: queued/in-flight work from the old
    // volume is dropped or discarded, its cached planes are cleared, and a
    // late old result can never overwrite the new volume's display.
    void set_volume(std::shared_ptr<pwb::viz::ISeismicVolume> volume,
                    VolumeIdentity identity, std::uint64_t revision);
    void clear_volume();

    // --- view controls (programmatic mirrors of the on-widget UI) ---------
    void set_axis(pwb::viz::VolumeAxis axis); // clamps index, resubmits
    void set_slice_index(std::int64_t index); // clamps, resubmits
    void set_color_map(std::string_view name); // unknown name: no-op
    void set_auto_range();                     // per-slice finite stretch
    void set_explicit_range(double min, double max); // min < max, else no-op
    void reset_view();                         // zoom/pan origin + auto range

    // Zoom scales image pixels; pan offsets are in image pixel units. Both
    // clamp so the slice stays reachable. Used by tests and hosts.
    void set_view_transform(double scale, double offset_x, double offset_y);
    [[nodiscard]] double view_scale() const;
    [[nodiscard]] double view_offset_x() const;
    [[nodiscard]] double view_offset_y() const;

    // --- selection --------------------------------------------------------
    void set_selection_callback(SelectionCallback callback);
    // Applies an external selection (e.g. fanned out by the host from another
    // view). Updates axis/index; NEVER re-emits, so a host that rebroadcasts
    // while skipping `origin == self` cannot loop. Returns false when the
    // event does not address this viewer's current volume revision.
    [[nodiscard]] bool apply_selection(const SliceSelectionEvent& event);
    void set_time_depth_relation(std::optional<LinearTimeDepth> relation);

    // --- introspection for hosts and tests --------------------------------
    [[nodiscard]] ViewerState state() const;
    [[nodiscard]] std::string last_diagnostic() const; // retained on failure
    [[nodiscard]] pwb::viz::VolumeAxis axis() const;
    [[nodiscard]] std::int64_t slice_index() const;
    [[nodiscard]] std::string color_map() const;
    [[nodiscard]] std::uint64_t volume_revision() const;
    [[nodiscard]] VolumeIdentity volume_identity() const;
    [[nodiscard]] ControllerStats controller_stats() const;

    // The currently displayed indexed8 image (pre-transform). Null image when
    // nothing is rendered. Ownership stays with the widget.
    [[nodiscard]] const class QImage& slice_image() const;
    // Physical axis value for a slice index (axis_value of the geometry).
    [[nodiscard]] double axis_coordinate(std::int64_t index) const;

    // Image-pixel (x=col, y=row) -> physical coordinates of the row/column
    // axes for the displayed slice; false when out of range or nothing shown.
    struct PlanePoint {
        double row_coordinate{0.0};
        double col_coordinate{0.0};
        std::string row_unit;
        std::string col_unit;
        double value{0.0};
        bool has_value{false};
    };
    [[nodiscard]] bool plane_point_at(int image_x, int image_y, PlanePoint& out) const;

    // Unique per-widget identity used as SliceSelectionEvent::origin.
    [[nodiscard]] std::string viewer_origin() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace pwb::seismic_viewer
