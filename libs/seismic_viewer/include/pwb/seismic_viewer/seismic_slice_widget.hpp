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
#include <vector>

#include <QWidget>

#include <pwb/seismic_viewer/colorbar_widget.hpp>
#include <pwb/seismic_viewer/display_core.hpp>
#include <pwb/seismic_viewer/horizon_core.hpp>
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

// VIZ-D display modes (profile_vd / profile_wiggle parity). Wiggle is a
// section-view renderer (the vertical image axis must be the sample axis);
// switching to wiggle on the sample (map) view is a no-op.
enum class DisplayMode : std::uint8_t {
    variable_density,
    wiggle,
};

// Result of a picks file load (identity is always restored from the file;
// a volume mismatch still loads and is reported).
enum class PicksLoadStatus : std::uint8_t { ok, mismatched_volume, error };

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

    // --- VIZ-D advanced display (profile_vd / profile_wiggle parity) ------
    // variable_density (default) paints the indexed8 raster; wiggle paints
    // per-trace deflection polylines with positive fill lobes from the SAME
    // retained float plane (no extra read, no volume copy). Switching to
    // wiggle on the sample (map) view is a no-op (section views only).
    void set_display_mode(DisplayMode mode);
    [[nodiscard]] DisplayMode display_mode() const;

    // SEG polarity flip — display-only (raw readouts and picks keep the
    // survey sign). Applies to both VD normalization and wiggle deflection.
    void set_polarity(bool normal);
    [[nodiscard]] bool polarity_normal() const;

    // Asymmetric percentile clip (P(100-pct)..P(pct)) computed on the raw
    // plane and cached per (volume, axis) across sibling slices — the
    // profile_vd normalization. Disabled by default: the default auto range
    // stays the frozen v3 finite min/max stretch. When enabled, non-finite
    // samples render at the LUT centre (128) instead of index 0 (colormap.py
    // #119 parity).
    void set_clip_percentile_enabled(bool enabled);
    [[nodiscard]] bool clip_percentile_enabled() const;
    void set_clip_percentile(double pct); // clamps to [1, 99]
    [[nodiscard]] double clip_percentile() const;

    // Wiggle deflection gain (one trace slot at 1.0; the source default 2.0
    // lets adjacent traces overlap). Positive finite, else no-op.
    void set_wiggle_gain(double gain);
    [[nodiscard]] double wiggle_gain() const;

    // --- VIZ-D horizon picking ---------------------------------------------
    // While picking is enabled, left-click adds a pick at the clicked
    // survey coordinates, dragging a pick moves it, right-click near a pick
    // deletes it. Picks are stored in survey coordinates; the visible
    // markers re-project per view.
    void enable_picking(bool enabled);
    [[nodiscard]] bool picking_enabled() const;

    // Programmatic pick API (tests and hosts). add_pick records the current
    // volume binding into the set on first use.
    void add_pick(horizon::HorizonPick pick);
    void clear_picks();
    [[nodiscard]] const horizon::HorizonPickSet& picks() const;

    // JSON persistence with stable source binding (volume id + revision,
    // axis, slice index, time unit, schema version). Saving an empty set is
    // allowed (the binding block is still written). Loading restores the
    // exact saved identity; a different current volume loads with
    // mismatched_volume (picks still shown, status notes the mismatch).
    [[nodiscard]] bool save_picks(const std::string& path, std::string& error);
    [[nodiscard]] PicksLoadStatus load_picks(const std::string& path, std::string& error);

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

    // The applied VD value range of the displayed image (percentile clip
    // range when enabled, the v3 stretch otherwise). {0, 0} when nothing is
    // displayed — the colorbar and hosts use this.
    [[nodiscard]] std::pair<double, double> displayed_range() const;

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

    // --- internal wiring (public for the canvas child; not for hosts) -----
    void report_cursor(const class QPointF& image_point);
    void report_click_selection(const class QPointF& image_point);
    void report_drag_selection(const class QPointF& from, const class QPointF& to);
    void handle_result(const SliceResult& result); // queued worker delivery

    // Canvas -> widget pick interactions (public for the canvas child).
    // Returns the image-space markers for the current picks (re-projected
    // onto this view); used by the canvas to hit-test and paint them.
    [[nodiscard]] std::vector<QPointF> pick_markers() const;
    // Canvas left-click while picking is enabled: add / begin-drag-edit.
    void report_pick_press(const class QPointF& image_point);
    void report_pick_drag(const class QPointF& image_point);
    // Returns true when the click deleted a pick (right-click near one).
    bool report_pick_context_menu(const class QPointF& image_point);
    // Rebuilds the cached wiggle geometry for the current canvas size.
    void rebuild_wiggle(int width, int height);
    [[nodiscard]] const display::WiggleGeometry* wiggle_geometry() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace pwb::seismic_viewer
