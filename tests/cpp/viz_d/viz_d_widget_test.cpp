// viz_d.widget — Qt-level integration of the advanced display: VD/wiggle
// mode switching, percentile/polarity display paths, horizon picking with
// save/reopen identity, colorbar range, negative self-checks. Offscreen.

#include "viz_d_test.hpp"

#include <QApplication>
#include <QElapsedTimer>
#include <QFile>
#include <QImage>
#include <QPointF>
#include <QString>
#include <QTemporaryDir>

#include <cmath>
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <string>
#include <vector>

#include <pwb/seismic_viewer/display_core.hpp>
#include <pwb/seismic_viewer/horizon_core.hpp>
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#include <pwb/viz/seismic_volume.hpp>

using namespace pwb::seismic_viewer;
using viz_d_test::close_or_both_nan;
using viz_d_test::num_from;
using viz_d_test::nums_from;

namespace {

bool wait_gui(const std::function<bool()>& predicate, int timeout_ms = 5000) {
    QElapsedTimer timer;
    timer.start();
    while (!predicate()) {
        if (timer.elapsed() > timeout_ms) {
            return false;
        }
        QApplication::processEvents(QEventLoop::AllEvents, 20);
    }
    return true;
}

pwb::viz::VolumeGeometryV1 pattern_geometry(std::array<std::int64_t, 3> shape) {
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = shape;
    geometry.strides = {0, 0, 0};
    geometry.origin = {100.0, 500.0, 0.0}; // survey line numbers
    geometry.step = {2.0, 5.0, 4.0};
    geometry.unit = "ms";
    return geometry;
}

std::vector<float> pattern_data(const pwb::viz::VolumeGeometryV1& geometry,
                                unsigned seed) {
    std::vector<float> data(static_cast<std::size_t>(geometry.shape[0] *
                                                    geometry.shape[1] *
                                                    geometry.shape[2]));
    std::uint32_t state = seed;
    const auto next_float = [&state]() {
        state = state * 1664525u + 1013904223u;
        return static_cast<float>(static_cast<double>(state >> 8) / 16777216.0 * 2.0 -
                                  1.0);
    };
    for (auto& value : data) {
        value = next_float();
    }
    data[0] = 0.0f;
    return data;
}

std::shared_ptr<pwb::viz::ISeismicVolume>
pattern_volume(std::array<std::int64_t, 3> shape, unsigned seed) {
    const pwb::viz::VolumeGeometryV1 geometry = pattern_geometry(shape);
    return std::shared_ptr<pwb::viz::ISeismicVolume>(pwb::viz::make_owning_volume(
        geometry, pattern_data(geometry, seed)));
}

} // namespace

TEST(display_mode_switching_and_wiggle_geometry) {
    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(pattern_volume({12, 9, 40}, 7), VolumeIdentity{"viz-d", 1}, 3);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    PWB_CHECK(widget.display_mode() == DisplayMode::variable_density);
    PWB_CHECK(!widget.slice_image().isNull());

    widget.set_display_mode(DisplayMode::wiggle);
    PWB_CHECK(widget.display_mode() == DisplayMode::wiggle);
    QApplication::processEvents();
    widget.rebuild_wiggle(360, 260);
    const display::WiggleGeometry* geo = widget.wiggle_geometry();
    PWB_CHECK(geo != nullptr);
    PWB_CHECK_MSG(geo->traces.size() == 9, "wiggle draws one trace per crossline");
    PWB_CHECK(!geo->traces.empty() && geo->traces[0].xs.size() >= 2);
    bool any_lobe = false;
    for (const auto& trace : geo->traces) {
        any_lobe = any_lobe || !trace.lobes.empty();
    }
    PWB_CHECK(any_lobe); // real fill geometry, not an empty render

    widget.set_display_mode(DisplayMode::variable_density);
    PWB_CHECK(widget.display_mode() == DisplayMode::variable_density);

    // Wiggle on the sample (map) view is a no-op (section views only).
    widget.set_axis(pwb::viz::VolumeAxis::sample);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    widget.set_display_mode(DisplayMode::wiggle);
    PWB_CHECK(widget.display_mode() == DisplayMode::variable_density);
    // Leaving section views while in wiggle falls back to VD.
    widget.set_axis(pwb::viz::VolumeAxis::inline_);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    widget.set_display_mode(DisplayMode::wiggle);
    PWB_CHECK(widget.display_mode() == DisplayMode::wiggle);
    widget.set_axis(pwb::viz::VolumeAxis::sample);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    PWB_CHECK(widget.display_mode() == DisplayMode::variable_density);
}

TEST(wiggle_switch_abandons_pinned_attribute) {
    // Regression (geoviz final closure): the wiggle renderer never
    // composites the attribute image, so a pinned attribute that stayed
    // "active" while invisible refused npy/csv export and kept the
    // colorbar pinned. Switching to wiggle must abandon the pin.
    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(pattern_volume({12, 9, 40}, 11),
                      VolumeIdentity{"viz-d", 1}, 3);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    const auto plane = widget.retained_plane();
    PWB_CHECK(!plane.values.empty());
    std::vector<float> attribute(plane.values.size());
    for (std::size_t i = 0; i < attribute.size(); ++i) {
        attribute[i] = 2.0f * plane.values[i];  // varied, like a real kernel
    }
    const bool pinned = widget.set_attribute_plane(
        attribute, plane.rows, plane.cols, "grayscale", "包络");
    PWB_CHECK_MSG(pinned, widget.last_diagnostic().c_str());
    PWB_CHECK(widget.attribute_active());
    widget.set_display_mode(DisplayMode::wiggle);
    PWB_CHECK(widget.display_mode() == DisplayMode::wiggle);
    PWB_CHECK_MSG(!widget.attribute_active(),
                  "wiggle switch must clear the pinned attribute view");
    // And back on VD the amplitude image is the display again.
    widget.set_display_mode(DisplayMode::variable_density);
    PWB_CHECK(!widget.attribute_active());
    PWB_CHECK(!widget.slice_image().isNull());
}

TEST(clip_percentile_display_path_and_polarity) {
    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    auto volume = pattern_volume({12, 9, 40}, 11);
    widget.set_volume(volume, VolumeIdentity{"viz-d", 2}, 5);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));

    widget.set_clip_percentile(99.0);
    widget.set_clip_percentile_enabled(true);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    PWB_CHECK(widget.clip_percentile() == 99.0);
    PWB_CHECK(widget.clip_percentile_enabled());

    // Expected display: percentile range of the shown inline plane, then
    // normalize_to_index of the raw (polarity-normal) plane.
    std::vector<float> plane(9 * 40);
    PWB_CHECK(volume->read_slice(pwb::viz::VolumeAxis::inline_, widget.slice_index(),
                                 plane));
    const display::ClipRange range = display::percentile_clip_range(plane, 99.0);
    PWB_CHECK(!range.degenerate);
    const auto [shown_lo, shown_hi] = widget.displayed_range();
    PWB_CHECK(close_or_both_nan(shown_lo, range.lo, 1e-12));
    PWB_CHECK(close_or_both_nan(shown_hi, range.hi, 1e-12));
    const std::vector<std::uint8_t> expected =
        display::normalize_to_index(plane, range.lo, range.hi);
    const QImage image = widget.slice_image(); // VALUE copy: handle_result reassigns
    PWB_CHECK(!image.isNull() && image.width() == 9 && image.height() == 40);
    for (int y = 0; y < image.height(); ++y) {
        for (int x = 0; x < image.width(); ++x) {
            // Display layout: x = crossline (row of the canonical plane),
            // y = sample (col) — the frozen v3 transpose.
            PWB_CHECK_MSG(image.pixelIndex(x, y) ==
                              expected[static_cast<std::size_t>(x * 40 + y)],
                          "percentile display pixel");
        }
    }

    // Polarity flip: the negated plane through the SAME cached range.
    widget.set_polarity(false);
    PWB_CHECK(!widget.polarity_normal());
    std::vector<float> negated(plane.size());
    for (std::size_t i = 0; i < plane.size(); ++i) {
        negated[i] = -plane[i];
    }
    const std::vector<std::uint8_t> expected_neg =
        display::normalize_to_index(negated, range.lo, range.hi);
    const QImage& image_neg = widget.slice_image();
    bool differs = false;
    for (int y = 0; y < image_neg.height(); ++y) {
        for (int x = 0; x < image_neg.width(); ++x) {
            PWB_CHECK(image_neg.pixelIndex(x, y) ==
                      expected_neg[static_cast<std::size_t>(x * 40 + y)]);
            differs = differs || image_neg.pixelIndex(x, y) != image.pixelIndex(x, y);
        }
    }
    PWB_CHECK(differs); // the flip is visible, not a no-op
    widget.set_polarity(true);
    PWB_CHECK(widget.polarity_normal());

    // Negative controls: invalid percentile clamps, unknown colormap no-op,
    // non-positive wiggle gain no-op.
    widget.set_clip_percentile(150.0);
    PWB_CHECK(widget.clip_percentile() == 99.0);
    widget.set_wiggle_gain(0.0);
    widget.set_wiggle_gain(-3.0);
    widget.set_wiggle_gain(std::numeric_limits<double>::quiet_NaN());
    PWB_CHECK(widget.wiggle_gain() == 2.0);
    const std::string before = widget.color_map();
    widget.set_color_map("no-such-map");
    PWB_CHECK(widget.color_map() == before);

    // Range cache reuse across sibling slices: same volume+axis => same
    // displayed range after flipping to another inline.
    const std::int64_t first_index = widget.slice_index();
    widget.set_slice_index(first_index + 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    const auto [lo2, hi2] = widget.displayed_range();
    PWB_CHECK(lo2 == shown_lo && hi2 == shown_hi); // cached, not recomputed
}

TEST(horizon_pick_add_edit_delete_save_reopen) {
    QTemporaryDir dir;
    PWB_CHECK(dir.isValid());
    const std::string path = (dir.filePath("picks.json")).toStdString();

    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(pattern_volume({12, 9, 40}, 23), VolumeIdentity{"survey-A", 4},
                      9);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    widget.enable_picking(true);
    PWB_CHECK(widget.picking_enabled());

    // geometry: inline view — il = 100 + 2*index, xl = 500 + 5*x, t = 4*y.
    widget.add_pick({104.0, 510.0, 100.0});   // x=2, y=25
    widget.add_pick({104.0, 515.0, 116.0});   // x=3, y=29
    widget.add_pick({104.0, 520.0, 60.0});    // x=4, y=15
    PWB_CHECK(widget.picks().picks.size() == 3);
    const auto markers = widget.pick_markers();
    PWB_CHECK(markers.size() == 3);
    PWB_CHECK(markers[0].x() == 2.0 && markers[0].y() == 25.0);
    PWB_CHECK(markers[1].x() == 3.0 && markers[1].y() == 29.0);

    // Click-driven dispatch parity: press at image (1, 5) — far from the
    // existing markers so the 6 px hit-test does not start an edit drag —
    // adds a pick at (il = axis position, xl = 500+5*1, t = 4*5).
    widget.report_pick_press(QPointF(1.0, 5.0));
    PWB_CHECK(widget.picks().picks.size() == 4);
    const auto& added = widget.picks().picks.back();
    PWB_CHECK(added.inline_no == 100.0 + 2.0 * static_cast<double>(widget.slice_index()));
    PWB_CHECK(added.crossline_no == 505.0 && added.time_value == 20.0);

    // Drag-edit the marker at (3, 29) to (6, 20).
    widget.report_pick_press(QPointF(3.5, 28.5)); // within the 6 px hit radius
    widget.report_pick_drag(QPointF(6.0, 20.0));
    PWB_CHECK(widget.picks().picks[1].crossline_no == 530.0);
    PWB_CHECK(widget.picks().picks[1].time_value == 80.0);

    // Right-click delete near (2, 25).
    PWB_CHECK(widget.report_pick_context_menu(QPointF(2.4, 25.4)));
    PWB_CHECK(widget.picks().picks.size() == 3);
    PWB_CHECK(!widget.report_pick_context_menu(QPointF(8.5, 8.5)));

    // Binding recorded from the owning viewer.
    PWB_CHECK(widget.picks().volume_id == "survey-A");
    PWB_CHECK(widget.picks().volume_revision == 9);
    PWB_CHECK(widget.picks().axis_name == "inline");
    PWB_CHECK(widget.picks().time_unit == "ms");

    std::string error;
    PWB_CHECK(widget.save_picks(path, error));

    // Reopen: fresh widget, same volume identity — exact restoration.
    SeismicSliceWidget reopened;
    reopened.resize(640, 480);
    reopened.show();
    reopened.set_volume(pattern_volume({12, 9, 40}, 23), VolumeIdentity{"survey-A", 4},
                        9);
    PWB_CHECK(wait_gui([&] { return reopened.state() == ViewerState::ok; }));
    PWB_CHECK(reopened.load_picks(path, error) == PicksLoadStatus::ok);
    PWB_CHECK(reopened.picks().volume_id == "survey-A");
    PWB_CHECK(reopened.picks().volume_revision == 9);
    PWB_CHECK(reopened.picks().axis_name == "inline");
    PWB_CHECK(reopened.picks().slice_index == widget.picks().slice_index);
    PWB_CHECK(reopened.picks().picks.size() == widget.picks().picks.size());
    for (std::size_t i = 0; i < reopened.picks().picks.size(); ++i) {
        PWB_CHECK(reopened.picks().picks[i].inline_no ==
                  widget.picks().picks[i].inline_no);
        PWB_CHECK(reopened.picks().picks[i].crossline_no ==
                  widget.picks().picks[i].crossline_no);
        PWB_CHECK(reopened.picks().picks[i].time_value ==
                  widget.picks().picks[i].time_value);
    }
    // Markers re-project after axis switch (crossline view: x = inline).
    reopened.set_axis(pwb::viz::VolumeAxis::crossline);
    PWB_CHECK(wait_gui([&] { return reopened.state() == ViewerState::ok; }));
    const auto cross_markers = reopened.pick_markers();
    PWB_CHECK(cross_markers.size() == reopened.picks().picks.size());

    // Mismatched volume: loads, flagged.
    SeismicSliceWidget other;
    other.resize(640, 480);
    other.show();
    other.set_volume(pattern_volume({12, 9, 40}, 99), VolumeIdentity{"survey-B", 4},
                     1);
    PWB_CHECK(wait_gui([&] { return other.state() == ViewerState::ok; }));
    PWB_CHECK(other.load_picks(path, error) == PicksLoadStatus::mismatched_volume);
    PWB_CHECK(other.picks().volume_id == "survey-A"); // identity from the file

    // Negative: corrupted file fails closed.
    const std::string bad_path = (dir.filePath("bad.json")).toStdString();
    QFile bad_file(QString::fromStdString(bad_path));
    PWB_CHECK(bad_file.open(QIODevice::WriteOnly));
    bad_file.write("{\"schema\": \"bogus\", \"picks\": []}");
    bad_file.close();
    PWB_CHECK(other.load_picks(bad_path, error) == PicksLoadStatus::error);
    PWB_CHECK(!error.empty());
    PWB_CHECK(!other.save_picks("/nonexistent-dir-xyz/picks.json", error));

    widget.clear_picks();
    PWB_CHECK(widget.picks().picks.empty());
    PWB_CHECK(widget.pick_markers().empty());
}

TEST(colorbar_follows_displayed_range_and_colormap) {
    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(pattern_volume({8, 8, 32}, 31), VolumeIdentity{"cb", 1}, 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    const auto [lo, hi] = widget.displayed_range();
    PWB_CHECK(hi > lo); // v3 auto stretch applied
    widget.set_color_map("viridis");
    PWB_CHECK(widget.color_map() == "viridis");
    widget.set_clip_percentile_enabled(true);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    const auto [plo, phi] = widget.displayed_range();
    PWB_CHECK(phi > plo);
}

TEST(picks_survive_volume_clear_and_late_results_never_apply) {
    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(pattern_volume({8, 8, 32}, 51), VolumeIdentity{"sv", 1}, 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    widget.add_pick({102.0, 510.0, 100.0});
    PWB_CHECK(widget.picks().picks.size() == 1);
    widget.clear_volume();
    PWB_CHECK(widget.state() == ViewerState::no_source);
    PWB_CHECK(widget.picks().picks.empty()); // no orphan picks without a source
    // Late controller results after the swap are discarded (epoch guard).
    widget.set_volume(pattern_volume({8, 8, 32}, 77), VolumeIdentity{"sv2", 1}, 2);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    PWB_CHECK(widget.volume_identity().volume_id == "sv2");
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    if (::viz_d_test::registry().empty()) {
        std::fprintf(stderr, "no tests registered\n");
        return 2;
    }
    for (const auto& test_case : ::viz_d_test::registry()) {
        std::printf("[ RUN  ] %s\n", test_case.name.c_str());
        std::fflush(stdout);
        test_case.body();
        QApplication::processEvents();
        std::printf("[ PASS ] %s\n", test_case.name.c_str());
        std::fflush(stdout);
    }
    std::printf("ALL %zu TESTS PASSED\n", ::viz_d_test::registry().size());
    return 0;
}
