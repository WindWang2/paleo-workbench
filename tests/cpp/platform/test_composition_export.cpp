// platform.composition_export — CONV-29 full-chain product test: composition
// JSON → layout_export kernel spec → shared wire-spec executor → native
// PNG/PDF/SVG + honest reports. Covers validate / export / preview /
// map-body / parity / fail-closed hybrid / pixel budget / transparent map
// body — offscreen, against the real vendored QGIS.

#include <qgsapplication.h>

#include <QColor>
#include <QFile>
#include <QImage>
#include <QIODevice>
#include <QTemporaryDir>

#include <exception>
#include <filesystem>

#include <qgsvectorlayer.h>

#include <pwb/domain/json.hpp>
#include <pwb/qgis/composition_layout_service.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include "test_fixtures.hpp"
#include "test_framework.hpp"

using pwb::domain::Json;

namespace {

Json composition_with_elements(const Json& extra_types) {
    Json composition = Json::object();
    composition["id"] = "comp_platform_test";
    composition["title"] = "platform test";
    composition["paper_size"] = "A4";
    composition["orientation"] = "landscape";
    composition["width_mm"] = 297.0;
    composition["height_mm"] = 210.0;
    composition["dpi"] = 300.0;
    Json elements = Json::array();
    auto add_element = [&elements](const char* id, const std::string& type,
                                   double x, double y, double w, double h,
                                   long long z, Json props) {
        Json element = Json::object();
        element["id"] = id;
        element["element_type"] = type;
        element["x_mm"] = x;
        element["y_mm"] = y;
        element["width_mm"] = w;
        element["height_mm"] = h;
        element["z_index"] = z;
        element["visible"] = true;
        element["locked"] = false;
        element["properties"] = std::move(props);
        elements.push_back(std::move(element));
    };
    add_element("el_map", "main_map", 8.0, 16.0, 204.0, 164.0, 1,
                Json::object());
    for (const Json& type : extra_types) {
        Json element = Json::object();
        element["id"] = type.value("id", "el_x");
        element["element_type"] = type.value("type", std::string("text"));
        element["x_mm"] = 10.0;
        element["y_mm"] = 186.0;
        element["width_mm"] = 60.0;
        element["height_mm"] = 10.0;
        element["z_index"] = 2;
        element["visible"] = true;
        element["locked"] = false;
        element["properties"] = type.value("props", Json::object());
        elements.push_back(std::move(element));
    }
    composition["elements"] = elements;
    composition["metadata"] = Json::object();
    return composition;
}

Json default_composition() {
    Json extra = Json::array({
        Json::object({{"id", "el_title"}, {"type", "title"},
                      {"props", Json::object({{"text", "测试"},
                                              {"font_size", 14.0}})}}),
        Json::object({{"id", "el_legend"}, {"type", "legend"},
                      {"props", Json::object()}}),
        Json::object({{"id", "el_scale"}, {"type", "scale_bar"},
                      {"props", Json::object({{"units", ""}})}}),
    });
    return composition_with_elements(extra);
}

std::string composition_dump(const Json& composition) { return composition.dump(); }

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir_guard;
    const QString gpkg_uri =
        pwb::test_fixtures::make_gpkg_fixture(temp_dir_guard.path());
    PWB_CHECK_MSG(!gpkg_uri.isEmpty(), "fixture creation failed");

    const std::filesystem::path base =
        std::filesystem::path(temp_dir_guard.path().toStdWString());

    {
        pwb::qgis::MapSession session;
        std::string error;
        pwb::qgis::LayerBinding binding{
            "export.layer", "asset-1", "version-1", "vector"};
        QgsVectorLayer* layer = session.addVectorLayer(
            gpkg_uri.toStdString(), "export", binding, &error);
        PWB_CHECK_MSG(layer != nullptr, error);
        session.setDestinationCrs("EPSG:4326", &error);

        pwb::qgis::CompositionLayoutService service(session);
        pwb::qgis::CompositionExportRequest request;
        request.format = "png";
        request.dpi = 96.0;
        request.has_extent = true;
        request.extent[0] = 108.0;
        request.extent[1] = 28.0;
        request.extent[2] = 118.0;
        request.extent[3] = 36.0;
        request.crs = "EPSG:4326";
        request.mirror_layers = Json::array({Json::object(
            {{"id", "export.layer"}, {"layer_type", "vector"}})});

        // --- canvas state + validate ------------------------------------
        const std::string canvas_state = session.canvas_state_json();
        Json state = Json::parse(canvas_state);
        PWB_CHECK(state.value("crs", std::string()) == "EPSG:4326");
        PWB_CHECK(state.contains("extent") && state["extent"].is_array());
        PWB_CHECK(state.contains("layers") && state["layers"].size() == 1);

        const Json composition = default_composition();
        const std::string composition_json = composition_dump(composition);
        const Json validation = service.validate_layout(composition_json, request);
        PWB_CHECK_MSG(validation.value("ok", false),
                      validation.value("failure", std::string("validate failed")));
        PWB_CHECK(validation.value("items", 0ULL) >= 4);
        PWB_CHECK(validation.value("hybrid_items", Json::array()).empty());

        // --- full-layout export: PNG / PDF / SVG ------------------------
        const std::filesystem::path png = base / "composition.png";
        request.format = "png";
        const Json png_report = service.export_layout(composition_json, png, request);
        PWB_CHECK_MSG(png_report.value("ok", false),
                      png_report.value("failure", std::string("png failed")));
        PWB_CHECK(png_report.value("engine", std::string()) == "qgis_layout");
        PWB_CHECK(std::filesystem::exists(png));
        PWB_CHECK(std::filesystem::file_size(png) > 0);
        const QImage image(QString::fromStdWString(png.wstring()));
        PWB_CHECK(!image.isNull());
        PWB_CHECK(png_report.value("width_px", 0LL) == image.width());
        PWB_CHECK(png_report.value("height_px", 0LL) == image.height());
        bool non_white = false;
        for (int y = 0; y < image.height() && !non_white; y += 4) {
            for (int x = 0; x < image.width() && !non_white; x += 4) {
                if (image.pixel(x, y) != QColor(Qt::white).rgb()) non_white = true;
            }
        }
        PWB_CHECK_MSG(non_white, "PNG export is blank");

        const std::filesystem::path pdf = base / "composition.pdf";
        request.format = "pdf";
        const Json pdf_report = service.export_layout(composition_json, pdf, request);
        PWB_CHECK_MSG(pdf_report.value("ok", false),
                      pdf_report.value("failure", std::string("pdf failed")));
        QFile pdf_file(QString::fromStdWString(pdf.wstring()));
        PWB_CHECK(pdf_file.open(QIODevice::ReadOnly));
        PWB_CHECK(pdf_file.read(5) == QByteArray("%PDF-"));
        pdf_file.close();

        const std::filesystem::path svg = base / "composition.svg";
        request.format = "svg";
        request.force_vector = true;  // vector-preservation opt-in
        const Json svg_report = service.export_layout(composition_json, svg, request);
        PWB_CHECK_MSG(svg_report.value("ok", false),
                      svg_report.value("failure", std::string("svg failed")));
        QFile svg_file(QString::fromStdWString(svg.wstring()));
        PWB_CHECK(svg_file.open(QIODevice::ReadOnly));
        PWB_CHECK(svg_file.read(2048).contains("<svg"));
        svg_file.close();
        request.force_vector = false;

        // --- preview -----------------------------------------------------
        const Json preview_report =
            service.preview(composition_json, base / "preview", request);
        PWB_CHECK_MSG(preview_report.value("ok", false),
                      preview_report.value("failure", std::string("preview failed")));
        PWB_CHECK(preview_report.value("format", std::string()) == "png");
        PWB_CHECK(preview_report.value("dpi", 0.0) == 96.0);
        PWB_CHECK(std::filesystem::exists(base / "preview" / "pwb_preview.png"));

        // --- map body only (transparent) --------------------------------
        pwb::qgis::MapBodyRequest body;
        body.has_extent = true;
        body.extent[0] = 108.0;
        body.extent[1] = 28.0;
        body.extent[2] = 118.0;
        body.extent[3] = 36.0;
        body.crs = "EPSG:4326";
        body.format = "png";
        body.dpi = 96.0;
        body.transparent = true;
        const std::filesystem::path body_png = base / "map_body.png";
        const Json body_report = service.export_map_body(body_png, body);
        PWB_CHECK_MSG(body_report.value("ok", false),
                      body_report.value("failure", std::string("map body failed")));
        const QImage body_image(QString::fromStdWString(body_png.wstring()));
        PWB_CHECK(!body_image.isNull());
        PWB_CHECK(body_image.width() > 100 && body_image.height() > 50);

        // --- parity ------------------------------------------------------
        const Json parity = service.parity_report(canvas_state,
                                                  composition_json, request);
        PWB_CHECK(parity.value("equal", false));
        pwb::qgis::CompositionExportRequest shifted = request;
        shifted.extent[0] = 100.0;  // export extent no longer the canvas one
        const Json parity_drift = service.parity_report(canvas_state,
                                                        composition_json, shifted);
        PWB_CHECK(!parity_drift.value("equal", true));

        // --- fail-closed: hybrid element --------------------------------
        const Json hybrid = composition_with_elements(Json::array(
            {Json::object({{"id", "el_chart"}, {"type", "stat_chart"},
                           {"props", Json::object()}})}));
        const std::string hybrid_json = composition_dump(hybrid);
        const Json hybrid_validation = service.validate_layout(hybrid_json, request);
        PWB_CHECK(!hybrid_validation.value("ok", true));
        PWB_CHECK(hybrid_validation.value("failure", std::string())
                      .find("stat_chart") != std::string::npos);
        request.format = "png";
        const std::filesystem::path hybrid_png = base / "hybrid.png";
        const Json hybrid_report =
            service.export_layout(hybrid_json, hybrid_png, request);
        PWB_CHECK(!hybrid_report.value("ok", true));
        PWB_CHECK(!hybrid_report.value("engine", std::string()).empty());
        PWB_CHECK(!std::filesystem::exists(hybrid_png));
        PWB_CHECK(hybrid_report.value("hybrid_items", Json::array())
                      .get<std::vector<std::string>>().size() == 1);

        // --- pixel budget (caller error, honest failure) -----------------
        pwb::qgis::CompositionExportRequest huge = request;
        huge.dpi = 100000.0;  // far beyond the 2e8 px budget
        const Json budget_report =
            service.export_layout(composition_json, base / "huge.png", huge);
        PWB_CHECK(!budget_report.value("ok", true));
        PWB_CHECK(budget_report.value("failure", std::string())
                      .find("budget") != std::string::npos);
        PWB_CHECK(!std::filesystem::exists(base / "huge.png"));

        // --- malformed composition ---------------------------------------
        const Json bad_report = service.export_layout(
            "{not json", base / "bad.png", request);
        PWB_CHECK(!bad_report.value("ok", true));
        PWB_CHECK(bad_report.value("failure", std::string())
                      .find("composition parse failed") != std::string::npos);

        session.close();
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.composition_export");
}
