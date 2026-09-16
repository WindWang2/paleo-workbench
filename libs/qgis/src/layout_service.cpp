#include <pwb/qgis/layout_service.hpp>

#include <QList>

#include <qgscoordinatereferencesystem.h>
#include <qgslayout.h>
#include <qgslayoutexporter.h>
#include <qgslayoutitemlegend.h>
#include <qgslayoutitemmap.h>
#include <qgslayoutitempage.h>
#include <qgslayoutpagecollection.h>
#include <qgsmaplayer.h>
#include <qgsprintlayout.h>
#include <qgsproject.h>
#include <qgslayertree.h>

#include <pwb/qgis/map_session.hpp>

namespace pwb::qgis {

namespace {
QgsLayoutSize mm(double w, double h) { return QgsLayoutSize(w, h, Qgis::LayoutUnit::Millimeters); }
QgsLayoutPoint mm_point(double x, double y) {
    return QgsLayoutPoint(x, y, Qgis::LayoutUnit::Millimeters);
}
}  // namespace

LayoutService::LayoutService(MapSession& session) : session_(session) {}

std::string LayoutService::export_layout(const LayoutSpec& spec,
                                         const std::filesystem::path& output_path,
                                         const std::string& format, double dpi) {
    QgsProject* project = session_.project();
    if (project == nullptr) return "no project";

    QgsPrintLayout layout(project);
    layout.initializeDefaults();
    QgsLayoutItemPage* page_item = layout.pageCollection()->page(0);
    page_item->setPageSize(mm(spec.page_width_mm, spec.page_height_mm));

    auto* map_item = new QgsLayoutItemMap(&layout);
    map_item->attemptMove(mm_point(spec.map.x_mm, spec.map.y_mm));
    map_item->attemptResize(mm(spec.map.w_mm, spec.map.h_mm));
    if (!spec.map.crs.empty()) {
        map_item->setCrs(QgsCoordinateReferenceSystem(
            QString::fromStdString(spec.map.crs)));
    }
    // Layer order: full tree order top-first reversed = bottom-first draw
    // order consumed by QgsLayoutItemMap (V11 parity).
    QList<QgsMapLayer*> ordered;
    const QList<QgsMapLayer*> tree_order = project->layerTreeRoot()->layerOrder();
    for (auto it = tree_order.rbegin(); it != tree_order.rend(); ++it) {
        QgsMapLayer* layer = *it;
        if (layer == nullptr || !layer->isSpatial()) continue;
        ordered.append(layer);
    }
    if (!ordered.isEmpty()) map_item->setLayers(ordered);
    map_item->setFrameEnabled(true);
    if (spec.map.extent[0] != 0.0 || spec.map.extent[1] != 0.0
        || spec.map.extent[2] != 0.0 || spec.map.extent[3] != 0.0) {
        map_item->setExtent(QgsRectangle(spec.map.extent[0], spec.map.extent[1],
                                         spec.map.extent[2], spec.map.extent[3]));
    }
    layout.addLayoutItem(map_item);

    if (spec.include_legend) {
        auto* legend = new QgsLayoutItemLegend(&layout);
        legend->setTitle(QStringLiteral("图例"));
        legend->setLinkedMap(map_item);
        legend->setResizeToContents(true);
        legend->attemptMove(mm_point(spec.legend_x_mm, spec.legend_y_mm));
        legend->setBackgroundEnabled(true);
        layout.addLayoutItem(legend);
    }

    QgsLayoutExporter exporter(&layout);
    QgsLayoutExporter::ExportResult result = QgsLayoutExporter::Success;
    if (format == "pdf") {
        QgsLayoutExporter::PdfExportSettings settings;
        settings.dpi = dpi;
        result = exporter.exportToPdf(
            QString::fromStdWString(output_path.wstring()), settings);
    } else if (format == "svg") {
        QgsLayoutExporter::SvgExportSettings settings;
        settings.dpi = dpi;
        result = exporter.exportToSvg(
            QString::fromStdWString(output_path.wstring()), settings);
    } else if (format == "png") {
        QgsLayoutExporter::ImageExportSettings settings;
        settings.dpi = dpi;
        result = exporter.exportToImage(
            QString::fromStdWString(output_path.wstring()), settings);
    } else {
        return "format must be png|pdf|svg, got: " + format;
    }
    if (result != QgsLayoutExporter::Success) {
        std::error_code ec;
        std::filesystem::remove(output_path, ec);
        return "layout export failed with result code "
            + std::to_string(static_cast<int>(result));
    }
    std::error_code ec;
    if (!std::filesystem::exists(output_path, ec)
        || std::filesystem::file_size(output_path, ec) == 0) {
        return "layout export produced no output: " + output_path.string();
    }
    return "";
}

}  // namespace pwb::qgis
