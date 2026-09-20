// seismic_viewer.advanced_widget — the 07-line widget surface under the
// offscreen platform: attribute pinning and stale-drop, RGB fusion display,
// slice export (npy orientation vs the pattern-volume formula, png real
// render) and view-state save/load with cross-volume rejection.

#include "sv_test.hpp"

#include <QApplication>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QImage>
#include <QPixmap>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <memory>
#include <optional>
#include <vector>

#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#include <pwb/viz/seismic_volume.hpp>

using namespace pwb::seismic_viewer;

namespace {

template <typename Predicate>
bool wait_gui(Predicate&& predicate, int timeout_ms = 6000) {
    QElapsedTimer elapsed;
    elapsed.start();
    while (!predicate()) {
        if (elapsed.elapsed() > timeout_ms) {
            return false;
        }
        QApplication::processEvents(QEventLoop::AllEvents, 10);
    }
    return true;
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
    return std::shared_ptr<pwb::viz::ISeismicVolume>(
        pwb::viz::make_owning_volume(pattern_geometry(shape),
                                     pattern_data(pattern_geometry(shape))));
}

std::string artifact_path(const std::string& name) {
    const char* dir = std::getenv("PWB_SEISMIC_VIEWER_ARTIFACT_DIR");
    return (dir != nullptr ? std::string(dir) : std::string(".")) + "/" + name;
}

std::vector<unsigned char> read_bytes(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

} // namespace

TEST(attribute_plane_pins_drops_and_rejects_stale_shape) {
    SeismicSliceWidget widget;
    widget.resize(320, 240);
    widget.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"attr-body", 0}, 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));

    // Default inline view: plane rows = crossline (4), cols = sample (5).
    const auto plane = widget.retained_plane();
    PWB_CHECK(plane.values.size() == 20);
    PWB_CHECK(plane.rows == 4 && plane.cols == 5);
    PWB_CHECK(plane.axis == pwb::viz::VolumeAxis::inline_);
    PWB_CHECK(plane.revision == 1);

    // Synthetic attribute = 2x amplitude, same shape -> pins.
    std::vector<float> attribute(plane.values.size());
    for (std::size_t i = 0; i < attribute.size(); ++i) {
        attribute[i] = 2.0f * plane.values[i];
    }
    PWB_CHECK(widget.set_attribute_plane(attribute, plane.rows, plane.cols,
                                         "grayscale", "测试属性"));
    PWB_CHECK(widget.attribute_active());

    // Shape mismatch fails closed with a diagnostic, view unchanged.
    PWB_CHECK(!widget.set_attribute_plane(attribute, 2, 2, "grayscale", "x"));
    PWB_CHECK(!widget.last_diagnostic().empty());
    PWB_CHECK(widget.attribute_active());

    // Pinning contract: moving to another slice drops the stale attribute.
    widget.set_slice_index(2);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    PWB_CHECK(!widget.attribute_active());

    // Re-pin on the new slice, then explicit clear.
    PWB_CHECK(widget.slice_index() == 2);
    const auto plane2 = widget.retained_plane();
    std::vector<float> attribute2(plane2.values.size());
    for (std::size_t i = 0; i < attribute2.size(); ++i) {
        attribute2[i] = plane2.values[i];
    }
    PWB_CHECK(widget.set_attribute_plane(attribute2, plane2.rows, plane2.cols,
                                         "grayscale", "测试属性"));
    widget.clear_attribute_view();
    PWB_CHECK(!widget.attribute_active());
}

TEST(rgb_fusion_pins_and_volume_swap_clears) {
    SeismicSliceWidget widget;
    widget.resize(320, 240);
    widget.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"rgb-body", 0}, 7);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    const auto plane = widget.retained_plane();

    std::vector<float> r(plane.values.size());
    std::vector<float> g(plane.values.size());
    std::vector<float> b(plane.values.size());
    for (std::size_t i = 0; i < plane.values.size(); ++i) {
        r[i] = plane.values[i];
        g[i] = 0.5f * plane.values[i];
        b[i] = -0.25f * plane.values[i];
    }
    PWB_CHECK(widget.set_rgb_fusion(r, g, b, plane.rows, plane.cols, 99.0, "RGB融合"));
    PWB_CHECK(widget.attribute_active());

    // Data export refuses while an attribute view is pinned (the retained
    // float plane is amplitude — it would disagree with the screen); png
    // still exports the real displayed render.
    std::string error;
    PWB_CHECK(!widget.export_slice(artifact_path("pinned.npy"),
                                   SeismicSliceWidget::SliceExportFormat::npy,
                                   error));
    PWB_CHECK(!error.empty());
    PWB_CHECK(widget.export_slice(artifact_path("pinned.png"),
                                  SeismicSliceWidget::SliceExportFormat::png,
                                  error));

    // Swapping the volume drops the pinned fusion view (never carried
    // across bodies).
    widget.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"rgb-body", 0}, 8);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    PWB_CHECK(!widget.attribute_active());
}

TEST(export_npy_matches_pattern_formula_orientation) {
    SeismicSliceWidget widget;
    widget.resize(320, 240);
    widget.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"export-body", 0}, 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));

    const std::string npy_path = artifact_path("advanced_widget_export.npy");
    std::string error;
    PWB_CHECK_MSG(widget.export_slice(npy_path, SeismicSliceWidget::SliceExportFormat::npy,
                                      error),
                  error.c_str());

    // Independent npy decode: data offset from the header, payload checked
    // against the PATTERN FORMULA (not against retained_plane): the widget
    // opens at inline index 0, and the inline view shows image
    // (x=crossline j, y=sample k) = 10000*0 + 100*j + k, with
    // rows = samples (5), cols = crosslines (4).
    const std::vector<unsigned char> bytes = read_bytes(npy_path);
    PWB_CHECK(bytes.size() > 12);
    PWB_CHECK(std::memcmp(bytes.data(), "\x93NUMPY\x01\x00", 8) == 0);
    const std::size_t header_len =
        static_cast<std::size_t>(bytes[8]) | (static_cast<std::size_t>(bytes[9]) << 8);
    const std::size_t offset = 10 + header_len;
    PWB_CHECK(offset % 64 == 0);
    const std::string header(bytes.begin() + 10, bytes.begin() + offset);
    PWB_CHECK(header.find("'descr': '<f4'") != std::string::npos);
    PWB_CHECK(header.find("'shape': (5, 4)") != std::string::npos);
    for (std::int64_t y = 0; y < 5; ++y) {
        for (std::int64_t x = 0; x < 4; ++x) {
            float value = 0.0f;
            std::memcpy(&value,
                        bytes.data() + offset +
                            static_cast<std::size_t>((y * 4 + x) * 4), 4);
            const float expected = static_cast<float>(100 * x + y);
            PWB_CHECK_MSG(value == expected,
                          "orientation mismatch at (y,x)");
        }
    }

    // Nothing displayed -> honest refusal.
    SeismicSliceWidget empty_widget;
    PWB_CHECK(!empty_widget.export_slice(artifact_path("nope.npy"),
                                         SeismicSliceWidget::SliceExportFormat::npy,
                                         error));
    PWB_CHECK(!error.empty());
}

TEST(export_png_is_a_real_render) {
    SeismicSliceWidget widget;
    widget.resize(320, 240);
    widget.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"png-body", 0}, 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));

    const std::string png_path = artifact_path("advanced_widget_export.png");
    std::string error;
    PWB_CHECK_MSG(widget.export_slice(png_path, SeismicSliceWidget::SliceExportFormat::png,
                                      error),
                  error.c_str());
    const QImage image(png_path.c_str());
    PWB_CHECK(!image.isNull());
    // Real content: a rendered slice is not a uniform fill.
    const QRgb first = image.pixel(0, 0);
    bool uniform = true;
    for (int y = 0; y < image.height() && uniform; y += 7) {
        for (int x = 0; x < image.width() && uniform; x += 7) {
            uniform = image.pixel(x, y) == first;
        }
    }
    PWB_CHECK_MSG(!uniform, "png looks blank (no real display render)");
}

TEST(view_state_save_load_reopen_consistency) {
    // Widget A: full advanced display state, horizon pick included.
    SeismicSliceWidget widget;
    widget.resize(400, 300);
    widget.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"reopen-body", 0}, 1);
    PWB_CHECK(wait_gui([&] { return widget.state() == ViewerState::ok; }));
    widget.set_display_mode(DisplayMode::wiggle);
    widget.set_polarity(false);
    widget.set_clip_percentile_enabled(true);
    widget.set_clip_percentile(95.0);
    widget.set_wiggle_gain(3.0);
    widget.set_color_map("grayscale");
    widget.set_axis(pwb::viz::VolumeAxis::crossline);
    widget.set_slice_index(2);
    // The canvas clamps the requested transform to keep the slice reachable;
    // capture the APPLIED values from the source widget and require the
    // restored widget to reproduce exactly those.
    widget.set_view_transform(2.0, 5.0, -3.0);
    const double applied_scale = widget.view_scale();
    const double applied_offset_x = widget.view_offset_x();
    const double applied_offset_y = widget.view_offset_y();
    widget.enable_picking(true);
    widget.add_pick(horizon::HorizonPick{2.0, 3.0, 100.0});

    const std::string path = artifact_path("advanced_view_state.json");
    std::string error;
    PWB_CHECK_MSG(widget.save_view_state(path, error), error.c_str());

    // Widget B: SAME volume identity, defaults everywhere.
    SeismicSliceWidget restored;
    restored.resize(400, 300);
    restored.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"reopen-body", 0}, 1);
    PWB_CHECK(wait_gui([&] { return restored.state() == ViewerState::ok; }));
    const auto status = restored.load_view_state(path, error);
    PWB_CHECK_MSG(status == SeismicSliceWidget::ViewStateLoadStatus::ok, error.c_str());

    PWB_CHECK(restored.display_mode() == DisplayMode::wiggle);
    PWB_CHECK(!restored.polarity_normal());
    PWB_CHECK(restored.clip_percentile_enabled());
    PWB_CHECK(restored.clip_percentile() == 95.0);
    PWB_CHECK(restored.wiggle_gain() == 3.0);
    PWB_CHECK(restored.color_map() == "grayscale");
    PWB_CHECK(restored.axis() == pwb::viz::VolumeAxis::crossline);
    PWB_CHECK(restored.slice_index() == 2);
    PWB_CHECK(restored.view_scale() == applied_scale);
    PWB_CHECK(restored.view_offset_x() == applied_offset_x);
    PWB_CHECK(restored.view_offset_y() == applied_offset_y);
    PWB_CHECK(restored.picking_enabled());
    PWB_CHECK(restored.picks().picks.size() == 1);
    PWB_CHECK(restored.picks().picks.front().inline_no == 2.0);
    // The delivered slice settles back to ok on the restored placement.
    PWB_CHECK(wait_gui([&] { return restored.state() == ViewerState::ok; }));

    // A modified state is detectable: saving again and loading into a third
    // widget with different current state reproduces the same view.
    SeismicSliceWidget third;
    third.resize(400, 300);
    third.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"reopen-body", 0}, 1);
    PWB_CHECK(wait_gui([&] { return third.state() == ViewerState::ok; }));
    PWB_CHECK(third.load_view_state(path, error) ==
              SeismicSliceWidget::ViewStateLoadStatus::ok);
    PWB_CHECK(third.display_mode() == DisplayMode::wiggle);
    PWB_CHECK(!third.polarity_normal());
}

TEST(view_state_rejects_cross_volume_and_corrupt_files) {
    SeismicSliceWidget source;
    source.resize(320, 240);
    source.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"body-alpha", 0}, 1);
    PWB_CHECK(wait_gui([&] { return source.state() == ViewerState::ok; }));
    source.set_color_map("heat");
    const std::string path = artifact_path("cross_volume_state.json");
    std::string error;
    PWB_CHECK_MSG(source.save_view_state(path, error), error.c_str());

    // Different volume_id: rejected wholesale, nothing applied.
    SeismicSliceWidget other;
    other.resize(320, 240);
    other.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"body-beta", 0}, 1);
    PWB_CHECK(wait_gui([&] { return other.state() == ViewerState::ok; }));
    PWB_CHECK(other.load_view_state(path, error) ==
              SeismicSliceWidget::ViewStateLoadStatus::mismatched_volume);
    PWB_CHECK(other.color_map() == "seismic"); // default unchanged

    // Anonymous bindings only match anonymous bindings.
    SeismicSliceWidget anonymous_source;
    anonymous_source.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{}, 1);
    PWB_CHECK(wait_gui([&] { return anonymous_source.state() == ViewerState::ok; }));
    const std::string anon_path = artifact_path("anonymous_state.json");
    PWB_CHECK(anonymous_source.save_view_state(anon_path, error));
    PWB_CHECK(other.load_view_state(anon_path, error) ==
              SeismicSliceWidget::ViewStateLoadStatus::mismatched_volume);

    // Corrupt file content -> error, nothing applied.
    const std::string corrupt_path = artifact_path("corrupt_state.json");
    {
        std::ofstream out(corrupt_path, std::ios::binary | std::ios::trunc);
        out << "{\"schema_version\": 1,";
    }
    SeismicSliceWidget victim;
    victim.set_volume(pattern_volume({3, 4, 5}), VolumeIdentity{"body-alpha", 0}, 1);
    PWB_CHECK(wait_gui([&] { return victim.state() == ViewerState::ok; }));
    PWB_CHECK(victim.load_view_state(corrupt_path, error) ==
              SeismicSliceWidget::ViewStateLoadStatus::error);
    PWB_CHECK(victim.color_map() == "seismic");

    // Missing file -> error.
    PWB_CHECK(victim.load_view_state("/nonexistent-dir-07/state.json", error) ==
              SeismicSliceWidget::ViewStateLoadStatus::error);
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
