// platform.export.layout — A3 export smoke: one real layout (page + map item
// + legend, live tree layer order) exported as PNG/PDF/SVG with honest
// capability errors (unknown format rejected; empty output rejected).

#include <qgsapplication.h>
#include <QColor>
#include <QFile>
#include <QImage>
#include <QTemporaryDir>

#include <qgsvectorlayer.h>

#include <pwb/qgis/layout_service.hpp>
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
        pwb::qgis::MapSession session;
        std::string error;
        pwb::qgis::LayerBinding binding{
            "export.layer", "asset-1", "version-1", "vector"};
        QgsVectorLayer* layer = session.addVectorLayer(
            gpkg_uri.toStdString(), "export", binding, &error);
        PWB_CHECK_MSG(layer != nullptr, error);
        pwb::qgis::LayoutService layouts(session);

        pwb::qgis::LayoutSpec spec;
        spec.map.extent[0] = 108.0;
        spec.map.extent[1] = 28.0;
        spec.map.extent[2] = 118.0;
        spec.map.extent[3] = 36.0;

        const std::filesystem::path png = base / "export.png";
        PWB_CHECK_MSG(layouts.export_layout(spec, png, "png", 96.0).empty(),
                      "PNG export failed");
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
        PWB_CHECK_MSG(layouts.export_layout(spec, pdf, "pdf", 96.0).empty(),
                      "PDF export failed");
        QFile pdf_file(QString::fromStdWString(pdf.wstring()));
        PWB_CHECK(pdf_file.open(QIODevice::ReadOnly));
        const QByteArray magic = pdf_file.read(5);
        PWB_CHECK(magic == QByteArray("%PDF-"));
        pdf_file.close();

        const std::filesystem::path svg = base / "export.svg";
        PWB_CHECK_MSG(layouts.export_layout(spec, svg, "svg", 96.0).empty(),
                      "SVG export failed");
        QFile svg_file(QString::fromStdWString(svg.wstring()));
        PWB_CHECK(svg_file.open(QIODevice::ReadOnly));
        const QByteArray head = svg_file.read(2048);
        PWB_CHECK(head.contains("<svg"));
        svg_file.close();

        // Honest failure: unknown format is rejected, not faked.
        const std::string bad = layouts.export_layout(spec, base / "export.docx",
                                                      "docx", 96.0);
        PWB_CHECK(!bad.empty());
        PWB_CHECK(!std::filesystem::exists(base / "export.docx"));

        session.close();
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.export.layout");
}
