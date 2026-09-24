// platform.export.layout — persistent-layout export smoke: a real
// QgsPrintLayout from the geological template library, exported as
// PNG/PDF/SVG through the unified QgsLayoutExporter service with honest
// capability errors (unknown format rejected).

#include <qgsapplication.h>
#include <QColor>
#include <QFile>
#include <QImage>
#include <QTemporaryDir>

#include <qgsvectorlayer.h>

#include <pwb/qgis/layout_authority.hpp>
#include <pwb/qgis/layout_export_service.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include "test_fixtures.hpp"
#include "test_framework.hpp"

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir;
    const QString gpkg_uri = pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
    PWB_CHECK_MSG(!gpkg_uri.isEmpty(), "fixture creation failed");

    const std::filesystem::path base =
        std::filesystem::path(temp_dir.path().toStdWString());

    {
        pwb::qgis::MapSession map;
        pwb::qgis::LayoutAuthority layouts(map);
        std::string error;
        pwb::qgis::LayerBinding binding{
            "export.layer", "asset-1", "version-1", "vector"};
        QgsVectorLayer* layer = map.addVectorLayer(
            gpkg_uri.toStdString(), "export", binding, &error);
        PWB_CHECK_MSG(layer != nullptr, error);

        layouts.set_map_seed(
            std::optional<std::array<double, 4>>{{108.0, 28.0, 118.0, 36.0}},
            "EPSG:4326");
        const auto instantiated = layouts.instantiate_template("single_factor");
        PWB_CHECK_MSG(instantiated.layout != nullptr,
                      instantiated.warnings.empty()
                          ? std::string("template instantiation failed")
                          : instantiated.warnings.front());

        pwb::qgis::LayoutExportRequest request;
        request.dpi = 96.0;

        const std::filesystem::path png = base / "export.png";
        request.output_path = png.string();
        request.format = "png";
        const auto png_report = pwb::qgis::export_layout(*instantiated.layout, request);
        PWB_CHECK_MSG(png_report.ok, png_report.error);
        QImage image(QString::fromStdWString(png.wstring()));
        PWB_CHECK(!image.isNull());
        PWB_CHECK(image.width() > 100 && image.height() > 50);
        bool non_white = false;
        for (int y = 0; y < image.height() && !non_white; y += 4) {
            for (int x = 0; x < image.width() && !non_white; x += 4) {
                if (image.pixel(x, y) != QColor(Qt::white).rgb()) non_white = true;
            }
        }
        PWB_CHECK_MSG(non_white, "PNG export is blank");

        const std::filesystem::path pdf = base / "export.pdf";
        request.output_path = pdf.string();
        request.format = "pdf";
        const auto pdf_report = pwb::qgis::export_layout(*instantiated.layout, request);
        PWB_CHECK_MSG(pdf_report.ok, pdf_report.error);
        QFile pdf_file(QString::fromStdWString(pdf.wstring()));
        PWB_CHECK(pdf_file.open(QIODevice::ReadOnly));
        const QByteArray magic = pdf_file.read(5);
        PWB_CHECK(magic == QByteArray("%PDF-"));
        pdf_file.close();

        const std::filesystem::path svg = base / "export.svg";
        request.output_path = svg.string();
        request.format = "svg";
        const auto svg_report = pwb::qgis::export_layout(*instantiated.layout, request);
        PWB_CHECK_MSG(svg_report.ok, svg_report.error);
        QFile svg_file(QString::fromStdWString(svg.wstring()));
        PWB_CHECK(svg_file.open(QIODevice::ReadOnly));
        const QByteArray head = svg_file.read(2048);
        PWB_CHECK(head.contains("<svg"));
        svg_file.close();

        // Honest failure: unknown format is rejected, not faked.
        const std::filesystem::path bad_path = base / "export.docx";
        request.output_path = bad_path.string();
        request.format = "docx";
        const auto bad_report = pwb::qgis::export_layout(*instantiated.layout, request);
        PWB_CHECK(!bad_report.ok);
        PWB_CHECK(!bad_report.error.empty());
        PWB_CHECK(!std::filesystem::exists(bad_path));

        // Pixel budget: an A2 page at 2400 dpi is a caller error.
        PWB_CHECK(!pwb::qgis::check_export_pixel_budget(594.0, 420.0, 2400.0).empty());

        map.close();
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.export.layout");
}
