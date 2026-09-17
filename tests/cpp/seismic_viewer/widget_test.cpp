// seismic_viewer.widget — real QWidget behavior under the offscreen platform:
// display states, frozen orientation pixel audits, coordinate/unit labels,
// real child-control paths (slider/combos), zoom/pan, selection events and
// feedback suppression, source swaps discarding late results, 20x
// open/swap/close cycles, GUI heartbeat during slow reads, screenshot output.

#include "sv_fixture_io.hpp"
#include "sv_test.hpp"
#include "sv_test_sources.hpp"

#include <QApplication>
#include <QComboBox>
#include <QElapsedTimer>
#include <QFile>
#include <QImage>
#include <QSlider>
#include <QThread>
#include <QTimer>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <vector>

#include <pwb/seismic_viewer/seismic_slice_widget.hpp>

using namespace pwb::seismic_viewer;
using namespace std::chrono_literals;

namespace {

template <typename Predicate>
bool wait_gui(Predicate&& predicate, int timeout_ms = 6000) {
    QElapsedTimer elapsed;
    elapsed.start();
    while (!predicate()) {
        if (elapsed.elapsed() > timeout_ms) {
            return predicate();
        }
        QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
        QThread::msleep(2);
    }
    return true;
}

QComboBox* combo_with_first_item(SeismicSliceWidget* viewer, const QString& first) {
    const auto combos = viewer->findChildren<QComboBox*>();
    for (QComboBox* combo : combos) {
        if (combo->count() > 0 && combo->itemText(0) == first) {
            return combo;
        }
    }
    return nullptr;
}

pwb::viz::VolumeGeometryV1 pattern_geometry(std::array<std::int64_t, 3> shape) {
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = shape;
    geometry.strides = {0, 0, 0};
    geometry.origin = {1.0, 1.0, 0.0};
    geometry.step = {1.0, 1.0, 2.0};
    geometry.unit = "ms";
    return geometry;
}

std::vector<float> pattern_data(const pwb::viz::VolumeGeometryV1& geometry) {
    std::vector<float> data(static_cast<std::size_t>(geometry.shape[0] *
                                                    geometry.shape[1] *
                                                    geometry.shape[2]));
    for (std::int64_t i = 0; i < geometry.shape[0]; ++i) {
        for (std::int64_t j = 0; j < geometry.shape[1]; ++j) {
            for (std::int64_t k = 0; k < geometry.shape[2]; ++k) {
                data[static_cast<std::size_t>((i * geometry.shape[1] + j) *
                                              geometry.shape[2] + k)] =
                    static_cast<float>(10000 * i + 100 * j + k);
            }
        }
    }
    return data;
}

std::shared_ptr<pwb::viz::ISeismicVolume> pattern_volume(
    std::array<std::int64_t, 3> shape) {
    return std::shared_ptr<pwb::viz::ISeismicVolume>( // unique -> shared
        pwb::viz::make_owning_volume(pattern_geometry(shape),
                                     pattern_data(pattern_geometry(shape))));
}

std::shared_ptr<pwb::viz::ISeismicVolume> owning_volume(
    pwb::viz::VolumeGeometryV1 geometry, std::vector<float> data) {
    return std::shared_ptr<pwb::viz::ISeismicVolume>(
        pwb::viz::make_owning_volume(geometry, std::move(data)));
}

} // namespace

TEST(widget_lifecycle_states_are_visible) {
    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();

    // no source
    PWB_CHECK(widget.state() == ViewerState::no_source);

    // empty volume (zero extent)
    pwb::viz::VolumeGeometryV1 empty_geometry;
    empty_geometry.shape = {0, 8, 32};
    widget.set_volume(owning_volume(empty_geometry, {}),
                      VolumeIdentity{"empty", 0}, 1);
    PWB_CHECK(widget.state() == ViewerState::empty);

    // constant volume -> degenerate display with retained diagnostic
    pwb::viz::VolumeGeometryV1 constant_geometry = pattern_geometry({4, 4, 8});
    widget.set_volume(owning_volume(constant_geometry, std::vector<float>(128, 2.5f)),
                      VolumeIdentity{"constant", 0}, 1);
    PWB_CHECK(wait_gui([&] {
        return widget.state() == ViewerState::degenerate;
    }));
    PWB_CHECK(!widget.last_diagnostic().empty());
    PWB_CHECK(!widget.slice_image().isNull()); // plane shown, flagged — not blank

    // read failure -> failed state, diagnostic retained, then recovery
    std::atomic<bool> fail{true};
    auto flaky = std::make_shared<sv_test_sources::FlakyVolume>(
        pattern_volume({4, 4, 8}), &fail);
    widget.set_volume(flaky, VolumeIdentity{"flaky", 0}, 2);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::failed; }));
    PWB_CHECK(!widget.last_diagnostic().empty());

    fail.store(false);
    widget.set_slice_index(2); // re-request: the viewer keeps working
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    PWB_CHECK(widget.controller_stats().read_failures >= 1);
}

TEST(frozen_display_orientation_matches_oracle_pixels) {
    pwb::viz::VolumeGeometryV1 geometry;
    auto volume = sv_fixture_io::load_tiny_sgy(geometry);
    PWB_CHECK(volume != nullptr);
    const std::filesystem::path dir =
        sv_fixture_io::science_fixture_root() / "seismic" / "tiny_sgy";
    const std::vector<float> expected_inline =
        sv_fixture_io::read_f32(dir / "expected_inline.f32");
    const std::vector<float> expected_crossline =
        sv_fixture_io::read_f32(dir / "expected_crossline.f32");
    const std::vector<float> expected_sample =
        sv_fixture_io::read_f32(dir / "expected_sample.f32");
    const std::vector<float> expected_indexed_f32 =
        sv_fixture_io::read_f32(dir / "expected_inline_indexed8.f32");
    std::vector<std::uint8_t> oracle_indexed;
    for (const float value : expected_indexed_f32) {
        oracle_indexed.push_back(static_cast<std::uint8_t>(value));
    }

    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(volume, VolumeIdentity{"tiny-sgy", 1}, 1);

    // --- inline view: image x = crossline (8), y = sample (32, time DOWN) ---
    widget.set_axis(pwb::viz::VolumeAxis::inline_);
    widget.set_slice_index(3);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    {
        const QImage& image = widget.slice_image();
        PWB_CHECK(!image.isNull());
        PWB_CHECK(image.width() == 8);  // crossline count
        PWB_CHECK(image.height() == 32); // sample count
        const pwb::viz::IndexedSlice mapped =
            pwb::viz::map_slice_to_indexed8(expected_inline);
        std::size_t mismatches = 0;
        for (int y = 0; y < image.height(); ++y) {
            for (int x = 0; x < image.width(); ++x) {
                // canonical plane row = crossline j = image x, col = sample k = image y
                const std::size_t flat =
                    static_cast<std::size_t>(x) * 32 + static_cast<std::size_t>(y);
                if (image.pixelIndex(x, y) != mapped.pixels[flat]) {
                    ++mismatches;
                }
            }
        }
        PWB_CHECK_MSG(mismatches == 0, "inline pixels diverge from oracle indexed8");
        // and byte-identical to the frozen oracle file itself
        for (int y = 0; y < image.height(); ++y) {
            for (int x = 0; x < image.width(); ++x) {
                PWB_CHECK(image.pixelIndex(x, y) ==
                          oracle_indexed[static_cast<std::size_t>(x) * 32 +
                                         static_cast<std::size_t>(y)]);
            }
        }
        // value lookup through the same mapping
        SeismicSliceWidget::PlanePoint point;
        PWB_CHECK(widget.plane_point_at(2, 5, point));
        PWB_CHECK(point.has_value);
        PWB_CHECK(point.value == expected_inline[2 * 32 + 5]);
    }

    // --- crossline view: image x = inline (8), y = sample (32) ---
    widget.set_axis(pwb::viz::VolumeAxis::crossline);
    widget.set_slice_index(5);
    PWB_CHECK(wait_gui([&] {
        return widget.state() == ViewerState::ok &&
               widget.slice_image().height() == 32;
    }));
    {
        const QImage& image = widget.slice_image();
        PWB_CHECK(image.width() == 8 && image.height() == 32);
        SeismicSliceWidget::PlanePoint point;
        for (int y = 0; y < 32; y += 3) {
            for (int x = 0; x < 8; ++x) {
                PWB_CHECK(widget.plane_point_at(x, y, point));
                PWB_CHECK(point.value == expected_crossline[static_cast<std::size_t>(x) * 32 +
                                                           static_cast<std::size_t>(y)]);
            }
        }
    }

    // --- sample view: image x = crossline (8), y = inline (8) ---
    widget.set_axis(pwb::viz::VolumeAxis::sample);
    widget.set_slice_index(16);
    PWB_CHECK(wait_gui([&] {
        return widget.state() == ViewerState::ok &&
               widget.slice_image().height() == 8;
    }));
    {
        const QImage& image = widget.slice_image();
        PWB_CHECK(image.width() == 8 && image.height() == 8);
        SeismicSliceWidget::PlanePoint point;
        for (int y = 0; y < 8; ++y) {
            for (int x = 0; x < 8; ++x) {
                PWB_CHECK(widget.plane_point_at(x, y, point));
                PWB_CHECK(point.value ==
                          expected_sample[static_cast<std::size_t>(y) * 8 +
                                          static_cast<std::size_t>(x)]);
            }
        }
    }
}

TEST(coordinates_and_units_reflect_physical_axes) {
    // Asymmetric 5 x 3 x 17, non-default origin/step, permuted strides.
    const std::int64_t n_il = 5, n_xl = 3, n_t = 17;
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {n_il, n_xl, n_t};
    geometry.strides = {n_t, n_il * n_t, 1};
    geometry.origin = {1.0, 10.0, 4.0}; // sample axis starts at 4 ms
    geometry.step = {1.0, 2.0, -2.0};   // sample axis runs DOWNWARD physically
    geometry.unit = "ms";
    std::vector<float> data(static_cast<std::size_t>(n_il * n_xl * n_t));
    for (std::int64_t j = 0; j < n_xl; ++j) {
        for (std::int64_t i = 0; i < n_il; ++i) {
            for (std::int64_t k = 0; k < n_t; ++k) {
                data[static_cast<std::size_t>(j * n_il * n_t + i * n_t + k)] =
                    static_cast<float>(i * 100 + j * 10 + k);
            }
        }
    }
    auto buffer = std::make_shared<const std::vector<float>>(std::move(data));
    std::shared_ptr<pwb::viz::ISeismicVolume> volume =
        pwb::viz::make_in_memory_volume(geometry, buffer->data(), buffer);

    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(volume, VolumeIdentity{"asym", 3}, 7);

    widget.set_axis(pwb::viz::VolumeAxis::inline_);
    widget.set_slice_index(2);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));

    // Slice-axis coordinates: inline 1 + 2*1 = 3; axis units: sample only.
    PWB_CHECK(widget.axis_coordinate(2) == 3.0);
    PWB_CHECK(widget.volume_revision() == 7);
    PWB_CHECK(widget.volume_identity().volume_id == "asym");

    // In-plane physical coordinates on the inline view: x = crossline
    // (10 + 2*j), y = sample (4 - 2*k, downward physical step).
    SeismicSliceWidget::PlanePoint point;
    PWB_CHECK(widget.plane_point_at(1, 0, point));
    PWB_CHECK(point.col_coordinate == 12.0); // crossline 10 + 2*1
    PWB_CHECK(point.col_unit.empty());
    PWB_CHECK(point.row_coordinate == 4.0);  // sample origin, top row
    PWB_CHECK(point.row_unit == "ms");
    PWB_CHECK(widget.plane_point_at(1, 3, point));
    PWB_CHECK(point.row_coordinate == -2.0); // 4 - 2*3: negative step honored
    // Value through the permuted layout: inline i=2, crossline j=1, sample k=3
    PWB_CHECK(point.value == static_cast<float>(2 * 100 + 1 * 10 + 3));

    // Sample view: slice coordinate in ms, not an index.
    widget.set_axis(pwb::viz::VolumeAxis::sample);
    widget.set_slice_index(4);
    PWB_CHECK(wait_gui([&] {
        return widget.state() == ViewerState::ok &&
               widget.axis() == pwb::viz::VolumeAxis::sample;
    }));
    PWB_CHECK(widget.axis_coordinate(4) == 4.0 + 4.0 * -2.0); // -4 ms
}

TEST(real_control_paths_change_the_view) {
    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(pattern_volume({8, 8, 32}), VolumeIdentity{"ctrl", 1}, 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));

    QSlider* slider = widget.findChild<QSlider*>();
    QComboBox* axis_combo = combo_with_first_item(&widget, QStringLiteral("Inline"));
    QComboBox* cmap_combo = combo_with_first_item(&widget, QStringLiteral("grayscale"));
    PWB_CHECK(slider != nullptr && axis_combo != nullptr && cmap_combo != nullptr);

    // Real slider interaction drives a new slice request.
    const std::uint64_t submitted_before = widget.controller_stats().submitted;
    slider->setValue(6);
    PWB_CHECK(wait_gui([&] {
        return widget.controller_stats().submitted > submitted_before &&
               widget.slice_index() == 6;
    }));
    PWB_CHECK(widget.controller_stats().submitted == submitted_before + 1);

    // Real axis combo switches the displayed axis (and clamps the index).
    axis_combo->setCurrentIndex(2); // sample
    PWB_CHECK(wait_gui([&] {
        return widget.axis() == pwb::viz::VolumeAxis::sample &&
               widget.state() == ViewerState::ok;
    }));
    PWB_CHECK(widget.slice_image().height() == 8); // inline count as rows

    // Real colormap combo swaps the LUT without a new read.
    const std::uint64_t executed_before = widget.controller_stats().executed;
    cmap_combo->setCurrentIndex(0); // grayscale
    PWB_CHECK(widget.color_map() == "grayscale");
    const QImage gray = widget.slice_image();
    PWB_CHECK(gray.colorTable().size() == 256);
    PWB_CHECK(qRed(gray.colorTable().at(200)) == 200 &&
              qGreen(gray.colorTable().at(200)) == 200);
    PWB_CHECK(widget.controller_stats().executed == executed_before);
}

TEST(explicit_range_restretches_displayed_pixels) {
    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    pwb::viz::VolumeGeometryV1 geometry = pattern_geometry({1, 1, 3});
    widget.set_volume(owning_volume(geometry, std::vector<float>{-10.0f, 0.0f, 10.0f}),
                      VolumeIdentity{"range", 1}, 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));

    // Inline view of a 1x1x3 volume: image x = crossline (1), y = sample (3)
    // — a single column whose three pixels are the three samples.
    PWB_CHECK(widget.slice_image().width() == 1);
    PWB_CHECK(widget.slice_image().height() == 3);
    PWB_CHECK(widget.slice_image().pixelIndex(0, 0) == 0);
    PWB_CHECK(widget.slice_image().pixelIndex(0, 1) == 127);
    PWB_CHECK(widget.slice_image().pixelIndex(0, 2) == 255);

    // Explicit asymmetric range re-stretches the SAME plane without a read.
    // (0,1) is the only pixel that differs between the stretches: wait on it.
    const std::uint64_t executed_before = widget.controller_stats().executed;
    widget.set_explicit_range(0.0, 10.0); // only the positive half
    PWB_CHECK(wait_gui([&] {
        return widget.slice_image().pixelIndex(0, 1) == 0; // 0.0 -> 0 (was 127)
    }));
    PWB_CHECK(widget.slice_image().pixelIndex(0, 0) == 0);   // -10 clamps to 0
    PWB_CHECK(widget.slice_image().pixelIndex(0, 2) == 255); // 10.0 -> 255
    PWB_CHECK(widget.controller_stats().executed == executed_before); // cache hit

    // Invalid explicit range is a no-op; reset returns to auto stretch.
    widget.set_explicit_range(5.0, 5.0);
    PWB_CHECK(widget.slice_image().pixelIndex(0, 2) == 255); // unchanged
    widget.reset_view();
    PWB_CHECK(wait_gui([&] {
        return widget.slice_image().pixelIndex(0, 1) == 127;
    }));
}

TEST(zoom_and_pan_transforms_clamp) {
    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(pattern_volume({8, 8, 32}), VolumeIdentity{"zoom", 1}, 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));

    // Inline view of the 8x8x32 volume: image is 8x32 px. In-bounds pan
    // offsets round-trip; out-of-bounds offsets clamp to the image edges.
    widget.set_view_transform(4.0, -20.0, 10.0);
    PWB_CHECK(widget.view_scale() == 4.0);
    PWB_CHECK(widget.view_offset_x() == -20.0 && widget.view_offset_y() == 10.0);

    widget.set_view_transform(4.0, 1000.0, 1000.0); // clamps to (width-8, height-8)
    PWB_CHECK(widget.view_offset_x() == 0.0);   // 8 - 8
    PWB_CHECK(widget.view_offset_y() == 24.0);  // 32 - 8

    widget.set_view_transform(1000.0, 0.0, 0.0); // scale clamps to 64
    PWB_CHECK(widget.view_scale() == 64.0);
    widget.set_view_transform(0.01, 0.0, 0.0); // and down to 1
    PWB_CHECK(widget.view_scale() == 1.0);

    widget.reset_view();
    PWB_CHECK(widget.view_scale() >= 1.0); // fitted
}

TEST(selection_events_units_and_feedback_suppression) {
    pwb::viz::VolumeGeometryV1 geometry;
    auto volume = sv_fixture_io::load_tiny_sgy(geometry);
    PWB_CHECK(volume != nullptr);

    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    std::vector<SliceSelectionEvent> events;
    widget.set_selection_callback(
        [&](const SliceSelectionEvent& event) { events.push_back(event); });
    widget.set_volume(volume, VolumeIdentity{"tiny-sgy", 1}, 4);
    widget.set_axis(pwb::viz::VolumeAxis::inline_);
    widget.set_slice_index(3);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    PWB_CHECK(events.empty()); // programmatic setting never emits

    // Click pick at image (x=2, y=5): crossline 1+2=3, sample 0+2*5=10 ms.
    widget.report_click_selection(QPointF(2.4, 5.6));
    PWB_CHECK(events.size() == 1);
    {
        const SliceSelectionEvent& event = events.front();
        PWB_CHECK(event.origin == widget.viewer_origin());
        PWB_CHECK(event.document_id == "tiny-sgy");
        PWB_CHECK(event.revision == 4);
        PWB_CHECK(event.axis == pwb::viz::VolumeAxis::inline_);
        PWB_CHECK(event.index == 3);
        PWB_CHECK(event.axis_coordinate == 4.0); // inline 1 + 3*1
        PWB_CHECK(event.axis_unit.empty());
        PWB_CHECK(event.has_point);
        PWB_CHECK(event.row_coordinate == 10.0); // sample 0 + 5*2
        PWB_CHECK(event.row_unit == "ms");
        PWB_CHECK(event.col_coordinate == 3.0); // crossline 1 + 2*1
        PWB_CHECK(event.domain == pwb::viz::DepthDomainKind::time);
    }

    // Shift+drag vertically: time range ordered; ms never silently becomes m.
    widget.report_drag_selection(QPointF(1.0, 10.0), QPointF(1.0, 2.0));
    PWB_CHECK(events.size() == 2);
    {
        const SliceSelectionEvent& event = events.back();
        PWB_CHECK(event.has_time_range);
        PWB_CHECK(event.time_top == 4.0 && event.time_bottom == 20.0);
        PWB_CHECK(event.time_unit == "ms");
        PWB_CHECK(event.conversion == ConversionStatus::not_convertible);
    }
    // With an explicit relation the interval converts to meters.
    widget.set_time_depth_relation(LinearTimeDepth{0.0, 2.0});
    widget.report_drag_selection(QPointF(1.0, 2.0), QPointF(1.0, 10.0));
    PWB_CHECK(events.size() == 3);
    {
        const SliceSelectionEvent& event = events.back();
        PWB_CHECK(event.conversion == ConversionStatus::converted);
        PWB_CHECK(event.converted_top == 2.0);  // (4-0)/2
        PWB_CHECK(event.converted_bottom == 10.0); // (20-0)/2
        PWB_CHECK(event.converted_unit == "m");
    }

    // Echo of our own origin: accepted, no view change, no emission.
    SliceSelectionEvent echo = events.front();
    PWB_CHECK(widget.apply_selection(echo));
    PWB_CHECK(events.size() == 3);
    PWB_CHECK(widget.slice_index() == 3);

    // External selection moves the view but never re-emits.
    SliceSelectionEvent external = events.front();
    external.origin = "well-log-view-1";
    external.index = 6;
    PWB_CHECK(widget.apply_selection(external));
    PWB_CHECK(wait_gui([&] { return widget.slice_index() == 6; }));
    PWB_CHECK(events.size() == 3); // feedback loop broken

    // Stale revision and foreign volume are rejected.
    SliceSelectionEvent stale = external;
    stale.revision = 0;
    PWB_CHECK(!widget.apply_selection(stale));
    SliceSelectionEvent foreign = external;
    foreign.document_id = "another-volume";
    PWB_CHECK(!widget.apply_selection(foreign));
}

TEST(source_swap_discards_late_results_from_old_volume) {
    auto slow_a = std::make_shared<sv_test_sources::ObservingVolume>(
        pattern_volume({8, 8, 32}), std::chrono::milliseconds(200));
    auto b = pattern_volume({8, 8, 16}); // different shape: undeniable proof

    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(slow_a, VolumeIdentity{"A", 1}, 1);
    PWB_CHECK(wait_gui([&] { return slow_a->reads_entered() >= 1; }));

    widget.set_volume(b, VolumeIdentity{"B", 2}, 2); // swap while A is in flight
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    PWB_CHECK(widget.volume_identity().volume_id == "B");

    // The displayed image is B's geometry (16 samples), never A's (32).
    PWB_CHECK(widget.slice_image().height() == 16);
    // A's late result was discarded, not delivered or applied.
    PWB_CHECK(widget.controller_stats().discarded_stale >= 1);
    // B's plane values are visible through the point API (pattern formula at
    // slice index 0 — set_volume preserved the viewer's index across the swap).
    SeismicSliceWidget::PlanePoint point;
    PWB_CHECK(widget.plane_point_at(3, 4, point));
    PWB_CHECK(point.value == static_cast<float>(0 * 10000 + 3 * 100 + 4));
}

TEST(open_swap_close_20_cycles_without_hangs_or_dangling_callbacks) {
    std::atomic<std::uint64_t> emissions{0};
    for (int cycle = 0; cycle < 20; ++cycle) {
        auto* widget = new SeismicSliceWidget;
        widget->resize(480, 360);
        widget->show();
        widget->set_selection_callback(
            [&emissions](const SliceSelectionEvent&) { emissions.fetch_add(1); });
        const bool slow = cycle % 2 == 0;
        std::shared_ptr<pwb::viz::ISeismicVolume> volume =
            slow
                ? std::static_pointer_cast<pwb::viz::ISeismicVolume>(
                      std::make_shared<sv_test_sources::ObservingVolume>(
                          pattern_volume({6, 5, 12}),
                          std::chrono::milliseconds(30)))
                : pattern_volume({5, 6, 10});
        widget->set_volume(volume, VolumeIdentity{"cycle", 1},
                           static_cast<std::uint64_t>(cycle));
        if (slow) {
            // leave a read in flight, swap immediately: stress the discard path
            widget->set_volume(pattern_volume({4, 4, 8}),
                               VolumeIdentity{"cycle", 2},
                               static_cast<std::uint64_t>(cycle) + 100);
        }
        PWB_CHECK(wait_gui([&] {
            return widget->state() == ViewerState::ok ||
                   widget->state() == ViewerState::loading;
        }));
        QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
        delete widget; // destructor joins the worker; queued calls are dropped
    }
    const std::uint64_t after_delete = emissions.load();
    QThread::msleep(120); // any late callback would land here (and under ASan,
                          // any dangling access would have crashed already)
    PWB_CHECK(emissions.load() == after_delete);
}

TEST(gui_heartbeat_continues_during_slow_slices) {
    // 300 ms read, 10 ms heartbeat timer: up to ~30 beats fit while the
    // worker produces the slice; a blocked GUI thread would score ~0.
    auto slow = std::make_shared<sv_test_sources::ObservingVolume>(
        pattern_volume({8, 8, 32}), std::chrono::milliseconds(300));

    SeismicSliceWidget widget;
    widget.resize(640, 480);
    widget.show();
    widget.set_volume(slow, VolumeIdentity{"slow", 1}, 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));

    int beats = 0;
    QTimer heartbeat;
    heartbeat.setInterval(10);
    QObject::connect(&heartbeat, &QTimer::timeout, [&] { ++beats; });
    heartbeat.start();
    widget.set_slice_index(5); // 300 ms read goes to the worker
    PWB_CHECK(wait_gui([&] {
        return widget.slice_index() == 5 && widget.state() == ViewerState::ok &&
               widget.controller_stats().delivered >= 2;
    }, 5000));
    heartbeat.stop();
    PWB_CHECK_MSG(beats >= 20,
                  "GUI timer must keep firing while slices are produced");
}

TEST(screenshots_saved_as_artifacts) {
    const char* artifact_dir = std::getenv("PWB_SEISMIC_VIEWER_ARTIFACT_DIR");
    PWB_CHECK_MSG(artifact_dir != nullptr && artifact_dir[0] != '\0',
                  "PWB_SEISMIC_VIEWER_ARTIFACT_DIR must be set by ctest");
    const QString dir = QString::fromUtf8(artifact_dir);

    pwb::viz::VolumeGeometryV1 geometry;
    auto volume = sv_fixture_io::load_tiny_sgy(geometry);
    PWB_CHECK(volume != nullptr);

    SeismicSliceWidget widget;
    widget.resize(800, 600);
    widget.show();
    widget.set_volume(volume, VolumeIdentity{"tiny-sgy", 1}, 1);
    widget.set_axis(pwb::viz::VolumeAxis::inline_);
    widget.set_slice_index(3);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    PWB_CHECK(widget.grab().save(dir + QStringLiteral("/seismic_viewer_inline.png")));

    // A real viewer operation trail: axis switch + index move + colormap +
    // explicit range + zoom, then evidence of the operated state.
    widget.set_color_map("grayscale");
    widget.set_explicit_range(-1.0, 1.0);
    widget.set_view_transform(3.0, 2.0, 4.0);
    widget.set_axis(pwb::viz::VolumeAxis::sample);
    widget.set_slice_index(16);
    PWB_CHECK(wait_gui([&] {
        return widget.state() == ViewerState::ok &&
               widget.axis() == pwb::viz::VolumeAxis::sample;
    }));
    PWB_CHECK(widget.grab().save(dir + QStringLiteral("/seismic_viewer_operated.png")));

    for (const char* name :
         {"seismic_viewer_inline.png", "seismic_viewer_operated.png"}) {
        QFile file(dir + QStringLiteral("/") + name);
        PWB_CHECK(file.exists());
        PWB_CHECK(file.size() > 4000); // non-trivial image content
    }
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    if (::sv_test::registry().empty()) {
        std::fprintf(stderr, "no tests registered\n");
        return 2;
    }
    for (const auto& test_case : ::sv_test::registry()) {
        std::printf("[ RUN  ] %s\n", test_case.name.c_str());
        std::fflush(stdout);
        test_case.body();
        std::printf("[ PASS ] %s\n", test_case.name.c_str());
        std::fflush(stdout);
    }
    std::printf("ALL %zu TESTS PASSED\n", ::sv_test::registry().size());
    return 0;
}
