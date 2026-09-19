// viz_a.viewer_flow — hard oracle 3: real load -> display -> track adjust
// -> export over the production dock host (offscreen Qt + software GL),
// plus failure retention, reopen, viewport/cursor interaction, and clean
// teardown. Worker-level cancellation and late-result discard are covered
// by viz_a.wle_load (including the resolve-seam late-discard regression).

#include <QApplication>
#include <QFile>
#include <QTemporaryDir>
#include <QtGlobal>

#include <pwb/viz/well_log_document_plan.hpp>
#include <pwb/viz/well_log_host_widget.hpp>
#include <welllog/io/las.hpp>

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <string>

namespace fs = std::filesystem;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

}  // namespace

int main(int argc, char** argv) {
    // Deterministic software-GL hint regardless of how ctest was invoked;
    // the PLATFORM itself is chosen by the test ENVIRONMENT contract
    // (real display when present — the offscreen GLX path cannot create
    // contexts on some hosts — offscreen under headless CI).
    qputenv("LIBGL_ALWAYS_SOFTWARE", "1");
    QApplication app(argc, argv);
    const fs::path root = PWB_VIZ_A_FIXTURE_ROOT;
    const std::string good1 = (root / "las/01_normal_multisection.las").string();
    const std::string good2 = (root / "las/04_custom_null.las").string();
    const std::string bad = (root / "las/11_missing_vers.las").string();

    QTemporaryDir tmp;
    check(tmp.isValid(), "temp dir");

    {
        pwb::viz::WellLogHostWidget host;
        host.resize(900, 600);

        // Load a real file through the DOCK path (load_las): direct engine
        // parse, one track per curve, lowercased axis unit, and the DTO
        // plan/layout deliberately cleared (host contract: the LAS path has
        // no adapted plan). Show after the document is in.
        QString error;
        check(host.load_las(QString::fromStdString(good1), &error),
              "load 01: " + error.toStdString());
        check(host.has_document(), "document present");
        host.show();
        check(host.last_track_count() >= 3, "real track count (>= 3 curves)");
        check(host.axis_unit_text().toStdString() == "m", "axis unit (lowercased)");
        check(host.track_layout().curve_keys.empty(),
              "LAS path carries no DTO layout (host contract)");

        // Display: viewport exists and reacts to zoom/pan.
        auto viewport = host.depth_viewport();
        check(viewport.has_value(), "viewport present");
        if (viewport) {
            check(host.zoom_at_depth((viewport->first + viewport->second) / 2, 0.5),
                  "zoom");
            auto zoomed = host.depth_viewport();
            check(zoomed.has_value() && zoomed->second - zoomed->first <
                                             viewport->second - viewport->first,
                  "zoom narrowed the viewport");
        }
        check(host.set_depth_cursor(1000.5), "depth cursor set");
        check(host.cursor_depth().has_value() &&
                  std::abs(*host.cursor_depth() - 1000.5) < 1e-9,
              "cursor round-trip");

        // Track adjust — the PRODUCTION path the app uses: deliver the
        // parsed document as a Workbench DTO (load_document populates the
        // layout machinery), then flip one visibility flag; document
        // identity and viewport survive.
        pwb::viz::WellLogDocumentInput dto;
        {
            std::ifstream in(good1, std::ios::binary);
            std::string bytes((std::istreambuf_iterator<char>(in)),
                              std::istreambuf_iterator<char>());
            welllog::BufferSourceReference source;
            source.uri = good1;
            auto parsed =
                welllog::LasSourceAdapter::parse(std::string_view(bytes), source);
            check(parsed.has_value(), "reparse for DTO");
            if (parsed.has_value()) {
                const auto& document = parsed.value().document;
                const auto& axis = document.sampling_axes().front();
                auto depth = std::make_shared<std::vector<double>>();
                for (std::uint64_t i = 0; i < axis.coordinates.length(); ++i) {
                    depth->push_back(*axis.coordinates.value_as_double(i));
                }
                dto.top_depth = depth->front();
                dto.bottom_depth = depth->back();
                dto.depth_unit = axis.unit;
                dto.well_name = "flow";
                for (const auto& curve : document.curves()) {
                    auto values = std::make_shared<std::vector<double>>();
                    for (std::uint64_t i = 0; i < curve.values.length(); ++i) {
                        const auto v = curve.values.value_as_double(i);
                        values->push_back(v ? *v : std::nan(""));
                    }
                    pwb::viz::WellLogCurveInput ci;
                    ci.mnemonic = curve.mnemonic;
                    ci.unit = curve.unit;
                    ci.depth = depth;
                    ci.values = std::move(values);
                    dto.curves.push_back(std::move(ci));
                }
            }
        }
        check(host.load_document(dto, pwb::viz::WellLogTrackLayout{}, &error),
              "load_document for layout: " + error.toStdString());
        auto layout = host.track_layout();
        const std::string id_before = host.document_id_text().toStdString();
        check(!layout.curve_keys.empty() && !layout.visible.empty(),
              "layout has curves after load_document");
        if (!layout.visible.empty()) {
            layout.visible.front() = !layout.visible.front();
        }
        check(host.apply_track_layout(layout, &error),
              "apply layout: " + error.toStdString());
        check(host.has_document() &&
                  host.document_id_text().toStdString() == id_before,
              "layout change keeps document identity");
        check(host.depth_viewport().has_value(),
              "viewport survives layout change");

        // Export: real bytes on disk.
        const std::string png = (fs::path(tmp.path().toStdString()) / "flow.png").string();
        const std::string svg = (fs::path(tmp.path().toStdString()) / "flow.svg").string();
        const std::string pdf = (fs::path(tmp.path().toStdString()) / "flow.pdf").string();
        check(host.export_png(QString::fromStdString(png), &error),
              "export png: " + error.toStdString());
        check(host.export_svg(QString::fromStdString(svg), &error),
              "export svg: " + error.toStdString());
        check(host.export_pdf(QString::fromStdString(pdf), &error),
              "export pdf: " + error.toStdString());
        check(QFile::exists(QString::fromStdString(png)) &&
                  QFile(QString::fromStdString(png)).size() > 0,
              "png non-empty");
        check(QFile::exists(QString::fromStdString(svg)) &&
                  QFile(QString::fromStdString(svg)).size() > 0,
              "svg non-empty");
        check(QFile::exists(QString::fromStdString(pdf)) &&
                  QFile(QString::fromStdString(pdf)).size() > 0,
              "pdf non-empty");
        // PNG is a real image (magic bytes: 89 50 4E 47 ...).
        QFile png_file(QString::fromStdString(png));
        png_file.open(QIODevice::ReadOnly);
        const QByteArray magic = png_file.read(8);
        check(magic.size() == 8 && (unsigned char)magic[0] == 0x89 &&
                  magic[1] == 'P' && magic[2] == 'N' && magic[3] == 'G',
              "png magic bytes");

        // Failure: rejected file keeps the previous document, reports error.
        const auto revision_before = host.document_revision();
        check(!host.load_las(QString::fromStdString(bad), &error) &&
                  !error.isEmpty(),
              "bad file fails with error");
        check(host.has_document() &&
                  host.document_revision() == revision_before,
              "failed reload keeps previous document");

        // Reopen: second good file replaces the document.
        check(host.load_las(QString::fromStdString(good2), &error),
              "reopen 04: " + error.toStdString());
        check(host.has_document() &&
                  host.document_id_text().toStdString() != id_before,
              "reopen replaced document");
        check(host.axis_unit_text().toStdString() == "m", "reopen axis unit");

        host.hide();
    }  // teardown: host destroyed while app alive — must not crash

    if (g_failures == 0) {
        std::printf("viz_a.viewer_flow: OK\n");
        return 0;
    }
    std::printf("viz_a.viewer_flow: %d failure(s)\n", g_failures);
    return 1;
}
