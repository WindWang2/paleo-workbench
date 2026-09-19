// viz_d.closure — CLOSURE-SEISMIC (07 line) product binding: the
// SeismicPredictionPage view panel hooks get a real host (the closure gap),
// a real SEG-Y opened through SeismicVolumeService embeds the real
// SeismicSliceWidget, attribute selections run the frozen E-line kernels on
// the displayed plane, RGB fusion needs three planes, and structural
// kernels are declined honestly on a 2-D section. Failures are honest —
// a missing file never fabricates a viewer.

#include "viz_d_test.hpp"

#include <QApplication>
#include <QElapsedTimer>
#include <QEventLoop>

#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include <pwb/seismic_service/volume_service.hpp>
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/seismic_view_panel.hpp>
#include <pwb/ui_workers/worker_common.hpp>

#include "closure_seismic_install.hpp"

namespace {

using pwb::closure_seismic::SeismicPageBinding;
using pwb::closure_seismic::install_seismic_page;
using pwb::seismic_viewer::SeismicSliceWidget;
using pwb::ui_wellseis::qt::SeismicPredictionPage;
using Viewer = pwb::seismic_viewer::SeismicSliceWidget;

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

std::string artifact_dir() {
    const char* dir = std::getenv("VIZ_D_CLOSURE_ARTIFACT_DIR");
    return dir != nullptr ? std::string(dir) : std::string(".");
}

void put_be_u16(unsigned char* p, std::uint16_t v) {
    p[0] = static_cast<unsigned char>(v >> 8);
    p[1] = static_cast<unsigned char>(v & 0xFF);
}

void put_be_i32(unsigned char* p, std::int32_t v) {
    p[0] = static_cast<unsigned char>((v >> 24) & 0xFF);
    p[1] = static_cast<unsigned char>((v >> 16) & 0xFF);
    p[2] = static_cast<unsigned char>((v >> 8) & 0xFF);
    p[3] = static_cast<unsigned char>(v & 0xFF);
}

void put_be_f32(unsigned char* p, float v) {
    std::uint32_t bits = 0;
    static_assert(sizeof(bits) == sizeof(v), "float32");
    std::memcpy(&bits, &v, 4);
    put_be_i32(p, static_cast<std::int32_t>(bits));
}

// Minimal but valid SEG-Y (format 5 IEEE float32): 2 inlines x 3 crosslines
// x 4 samples, dt 2 ms. Values distinguish positions: 10000*il + 100*xl + s.
void write_tiny_segy(const std::filesystem::path& path) {
    constexpr std::int64_t kNi = 2;
    constexpr std::int64_t kNc = 3;
    constexpr std::int64_t kNs = 4;
    std::vector<unsigned char> file;
    file.resize(3600, 0); // 3200 text + 400 binary
    put_be_u16(file.data() + 3200 + 16, 2000); // dt (microseconds)
    put_be_u16(file.data() + 3200 + 20, static_cast<std::uint16_t>(kNs));
    put_be_u16(file.data() + 3200 + 24, 5); // IEEE float32
    for (std::int64_t il = 0; il < kNi; ++il) {
        for (std::int64_t xl = 0; xl < kNc; ++xl) {
            std::vector<unsigned char> trace(240 + kNs * 4, 0);
            // The reader's trace-header offsets are 0-based: inline at 188,
            // crossline at 192 (the SEG-Y spec's 189/193 1-based fields).
            put_be_i32(trace.data() + 188, static_cast<std::int32_t>(il + 1));
            put_be_i32(trace.data() + 192, static_cast<std::int32_t>(xl + 1));
            for (std::int64_t s = 0; s < kNs; ++s) {
                put_be_f32(trace.data() + 240 + s * 4,
                           static_cast<float>(10000 * il + 100 * xl + s));
            }
            file.insert(file.end(), trace.begin(), trace.end());
        }
    }
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out.write(reinterpret_cast<const char*>(file.data()),
              static_cast<std::streamsize>(file.size()));
}

} // namespace

TEST(closure_install_null_page_is_honest_noop) {
    PWB_CHECK(install_seismic_page({nullptr, nullptr}) == nullptr);
}

TEST(closure_missing_volume_stays_honestly_unavailable) {
    SeismicPredictionPage page;
    pwb::seismic_service::SeismicVolumeService service;
    SeismicPageBinding* binding =
        install_seismic_page({&page, &service});
    PWB_CHECK(binding != nullptr);

    pwb::ui_workers::ResourceSlice missing;
    missing.id = "res-missing";
    missing.path = artifact_dir() + "/does-not-exist.sgy";
    PWB_CHECK(!page.view_panel()->show_resource(missing, nullptr));
    PWB_CHECK(!page.view_panel()->is_view_ready());
    PWB_CHECK(binding->bound_volume_path().empty());
    // The failure reason is surfaced, not swallowed.
    PWB_CHECK(!binding->last_unavailable_reason().empty());
    page.shutdown_workers();
}

TEST(closure_real_segy_binds_viewer_attributes_and_fusion) {
    const std::filesystem::path segy =
        std::filesystem::path(artifact_dir()) / "closure_tiny.sgy";
    write_tiny_segy(segy);

    SeismicPredictionPage page;
    pwb::seismic_service::SeismicVolumeService service;
    SeismicPageBinding* binding = install_seismic_page({&page, &service});
    PWB_CHECK(binding != nullptr);

    pwb::ui_workers::ResourceSlice resource;
    resource.id = "res-tiny";
    resource.path = segy.string();
    PWB_CHECK(page.view_panel()->show_resource(resource, nullptr));
    PWB_CHECK(page.view_panel()->is_view_ready());
    PWB_CHECK(binding->bound_volume_path() == segy.string());
    PWB_CHECK(page.view_panel()->view() != nullptr);
    const auto shape = page.view_panel()->volume_shape();
    // Comma-free comparison: braced lists inside a PWB_CHECK argument would
    // split the macro's arguments.
    PWB_CHECK(shape.has_value() && (*shape)[0] == 2 && (*shape)[1] == 3 &&
              (*shape)[2] == 4);

    auto* viewer = static_cast<Viewer*>(page.view_panel()->view());
    PWB_CHECK(wait_gui([&] {
        return viewer->state() == pwb::seismic_viewer::ViewerState::ok;
    }));
    PWB_CHECK(viewer->volume_identity().volume_id == segy.string());

    // E-line attributes compute on the displayed plane and pin the view.
    const auto plane = viewer->retained_plane();
    PWB_CHECK(plane.values.size() == 3 * 4);
    PWB_CHECK(!viewer->attribute_active());
    binding->apply_attribute(QStringLiteral("包络"));
    PWB_CHECK_MSG(viewer->attribute_active(),
                  binding->last_unavailable_reason().c_str());
    binding->apply_attribute(QStringLiteral("RMS振幅"));
    binding->apply_attribute(QStringLiteral("瞬时相位"));
    PWB_CHECK(viewer->attribute_active());

    // RGB fusion: three computed attribute planes are available now.
    binding->apply_attribute(QStringLiteral("RGB融合"));
    PWB_CHECK(viewer->attribute_active());

    // Slice change drops the pinned fusion view (stale attribute never
    // carried to a new slice).
    viewer->set_slice_index(2);
    PWB_CHECK(wait_gui([&] {
        return viewer->state() == pwb::seismic_viewer::ViewerState::ok;
    }));
    PWB_CHECK(!viewer->attribute_active());

    // Structural kernels need 3-D neighborhoods — declined honestly.
    binding->apply_attribute(QStringLiteral("平均曲率"));
    PWB_CHECK(!viewer->attribute_active());
    PWB_CHECK(binding->last_unavailable_reason().find("2D") != std::string::npos);

    page.shutdown_workers();
}

TEST(closure_display_mode_forwards_to_real_viewer) {
    const std::filesystem::path segy =
        std::filesystem::path(artifact_dir()) / "closure_tiny_mode.sgy";
    write_tiny_segy(segy);

    SeismicPredictionPage page;
    pwb::seismic_service::SeismicVolumeService service;
    SeismicPageBinding* binding = install_seismic_page({&page, &service});
    PWB_CHECK(binding != nullptr);
    pwb::ui_workers::ResourceSlice resource;
    resource.id = "res-mode";
    resource.path = segy.string();
    PWB_CHECK(page.view_panel()->show_resource(resource, nullptr));

    page.view_panel()->set_display_mode(QStringLiteral("wiggle"));
    auto* viewer = static_cast<Viewer*>(page.view_panel()->view());
    PWB_CHECK(wait_gui([&] {
        return viewer->state() == pwb::seismic_viewer::ViewerState::ok;
    }));
    PWB_CHECK(viewer->display_mode() ==
              pwb::seismic_viewer::DisplayMode::wiggle);
    page.view_panel()->set_display_mode(QStringLiteral("vd"));
    PWB_CHECK(viewer->display_mode() ==
              pwb::seismic_viewer::DisplayMode::variable_density);
    page.shutdown_workers();
}

int main(int argc, char** argv) {
    // Qt widgets are constructed (the real viewer lives inside the page), so
    // this suite owns a QApplication main — same as viz_d.widget.
    QApplication app(argc, argv);
    if (::viz_d_test::registry().empty()) {
        std::fprintf(stderr, "no tests registered\n");
        return 2;
    }
    for (const auto& test_case : ::viz_d_test::registry()) {
        std::printf("[ RUN  ] %s\n", test_case.name.c_str());
        std::fflush(stdout);
        test_case.body();
        std::printf("[ PASS ] %s\n", test_case.name.c_str());
        std::fflush(stdout);
    }
    std::printf("ALL %zu TESTS PASSED\n", ::viz_d_test::registry().size());
    return 0;
}
