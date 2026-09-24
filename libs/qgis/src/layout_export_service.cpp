// LayoutExportService — implementation. The exporter calls mirror the
// battle-tested layout_spec_exec.cpp result handling (never-fake: failed
// exports remove partial files), applied to *persistent* layouts.

#include <pwb/qgis/layout_export_service.hpp>

#include <qgsexpression.h>
#include <qgslayout.h>
#include <qgslayoutatlas.h>
#include <qgslayoutexporter.h>
#include <qgslayoutitemmap.h>
#include <qgslayoutitempage.h>
#include <qgslayoutpagecollection.h>
#include <qgsprintlayout.h>
#include <qgsvectorlayer.h>

#include <QFile>
#include <QFileInfo>
#include <QImage>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <system_error>

namespace pwb::qgis {

namespace {

std::string normalize_format(const LayoutExportRequest& request) {
    if (!request.format.empty()) return request.format;
    const std::string suffix =
        QFileInfo(QString::fromStdString(request.output_path))
            .suffix()
            .toLower()
            .toStdString();
    if (suffix.empty()) return "png";
    return suffix;
}

}  // namespace

std::string check_export_pixel_budget(double page_w_mm, double page_h_mm,
                                      double dpi) {
    if (!(page_w_mm > 0.0) || !(page_h_mm > 0.0)) {
        return "page dimensions must be positive";
    }
    if (!(dpi > 0.0)) return "dpi must be positive";
    const double pixels =
        (page_w_mm / 25.4) * dpi * (page_h_mm / 25.4) * dpi;
    if (pixels > kMaxExportPixels) {
        char buffer[160];
        std::snprintf(buffer, sizeof(buffer),
                      "export exceeds pixel budget: %.0fx%.0f mm at %.0f dpi "
                      "needs %.2e pixels (max %.2e)",
                      page_w_mm, page_h_mm, dpi, pixels, kMaxExportPixels);
        return buffer;
    }
    return {};
}

domain::Json LayoutExportReport::to_json() const {
    domain::Json out = domain::Json::object();
    out["ok"] = ok;
    out["engine"] = engine;
    if (!error.empty()) out["failure"] = error;
    out["path"] = path;
    out["format"] = format;
    out["dpi"] = dpi;
    out["pages"] = pages;
    if (width_px > 0) {
        out["width_px"] = width_px;
        out["height_px"] = height_px;
    }
    return out;
}

domain::Json AtlasExportReport::to_json() const {
    domain::Json out = domain::Json::object();
    out["ok"] = ok;
    out["engine"] = engine;
    if (!error.empty()) out["failure"] = error;
    out["pages"] = pages;
    domain::Json files_json = domain::Json::array();
    for (const std::string& file : files) {
        files_json.push_back(file);
    }
    out["files"] = std::move(files_json);
    return out;
}

LayoutExportReport export_layout(QgsPrintLayout& layout,
                                 const LayoutExportRequest& request) {
    LayoutExportReport report;
    report.format = normalize_format(request);
    report.dpi = request.dpi > 0.0 ? request.dpi : kDefaultExportDpi;
    report.path = request.output_path;
    if (request.output_path.empty()) {
        report.error = "output path is empty";
        return report;
    }
    if (report.format != "pdf" && report.format != "svg" &&
        report.format != "png") {
        report.error =
            "unsupported composition export format '" + report.format + "'";
        return report;
    }

    if (layout.pageCollection() == nullptr ||
        layout.pageCollection()->page(0) == nullptr) {
        report.error = "layout has no pages to export";
        return report;
    }
    const QgsLayoutSize page =
        layout.pageCollection()->page(0)->sizeWithUnits();
    // Layout units are mm by default; page sizes stored in mm.
    const double page_w = page.width();
    const double page_h = page.height();
    if (const std::string budget =
            check_export_pixel_budget(page_w, page_h, report.dpi);
        !budget.empty()) {
        report.error = budget;
        return report;
    }

    QgsLayoutExporter exporter(&layout);
    QgsLayoutExporter::ExportResult result =
        QgsLayoutExporter::Success;
    if (report.format == "pdf") {
        QgsLayoutExporter::PdfExportSettings settings;
        settings.dpi = report.dpi;
        settings.writeGeoPdf = request.geo_pdf;
        settings.forceVectorOutput = request.force_vector;
        result = exporter.exportToPdf(QString::fromStdString(request.output_path),
                                      settings);
    } else if (report.format == "svg") {
        QgsLayoutExporter::SvgExportSettings settings;
        settings.dpi = report.dpi;
        settings.forceVectorOutput = request.force_vector;
        result = exporter.exportToSvg(QString::fromStdString(request.output_path),
                                      settings);
    } else {
        QgsLayoutExporter::ImageExportSettings settings;
        settings.dpi = report.dpi;
        result = exporter.exportToImage(QString::fromStdString(request.output_path),
                                        settings);
        if (result == QgsLayoutExporter::Success) {
            const QImage image(QString::fromStdString(request.output_path));
            if (!image.isNull()) {
                report.width_px = image.width();
                report.height_px = image.height();
            }
        }
    }
    if (result != QgsLayoutExporter::Success) {
        // Never-fake: a failed export must not leave a partial file callers
        // could mistake for the requested product (spec-exec parity).
        std::error_code remove_error;
        std::filesystem::remove(request.output_path, remove_error);
        report.error = "layout export failed with result code " +
                       std::to_string(static_cast<int>(result));
        return report;
    }
    report.pages = report.format == "png"
                       ? 1
                       : layout.pageCollection()->pageCount();
    report.ok = true;
    return report;
}

QImage render_layout_preview(QgsPrintLayout& layout, double dpi) {
    QgsLayoutExporter exporter(&layout);
    return exporter.renderPageToImage(0, QSize(), dpi > 0.0 ? dpi : 96.0);
}

AtlasExportReport export_atlas(QgsPrintLayout& layout,
                               const AtlasExportRequest& request) {
    AtlasExportReport report;
    if (request.output_base.empty()) {
        report.error = "atlas output base path is empty";
        return report;
    }
    if (request.format != "pdf" && request.format != "png" &&
        request.format != "svg") {
        report.error = "unsupported atlas format '" + request.format + "'";
        return report;
    }

    if (layout.pageCollection() == nullptr ||
        layout.pageCollection()->page(0) == nullptr) {
        report.error = "layout has no pages to export";
        return report;
    }
    // The same product-wide pixel budget as the single-page path — an
    // atlas page is still a rasterised page (A0@1200dpi is a caller error
    // here too).
    {
        const QgsLayoutSize page =
            layout.pageCollection()->page(0)->sizeWithUnits();
        if (const std::string budget = check_export_pixel_budget(
                page.width(), page.height(),
                request.dpi > 0.0 ? request.dpi : kDefaultExportDpi);
            !budget.empty()) {
            report.error = budget;
            return report;
        }
    }

    QgsLayoutAtlas* atlas = layout.atlas();
    if (atlas == nullptr) {
        report.error = "layout has no atlas";
        return report;
    }
    // The atlas configuration belongs to the persisted document; a batch
    // export must leave it exactly as it found it (all exit paths).
    struct AtlasState {
        QgsLayoutAtlas* atlas;
        bool enabled;
        bool hide_coverage;
        bool filter_features;
        QString filter_expression;
        QString filename_expression;
        QgsVectorLayer* coverage = nullptr;
        ~AtlasState() {
            QString sink;
            atlas->setCoverageLayer(coverage);
            atlas->setFilterExpression(filter_expression, sink);
            atlas->setFilterFeatures(filter_features);
            atlas->setFilenameExpression(filename_expression, sink);
            atlas->setHideCoverage(hide_coverage);
            atlas->setEnabled(enabled);
        }
    } const restore{atlas,
                    atlas->enabled(),
                    atlas->hideCoverage(),
                    atlas->filterFeatures(),
                    atlas->filterExpression(),
                    atlas->filenameExpression(),
                    atlas->coverageLayer()};
    (void)restore;

    if (request.coverage_layer != nullptr) {
        atlas->setCoverageLayer(request.coverage_layer);
    }
    if (request.coverage_layer != nullptr || !atlas->enabled()) {
        atlas->setEnabled(true);
    }
    atlas->setHideCoverage(request.hide_coverage);
    QString expression_error;
    if (!request.filter_expression.empty()) {
        if (!atlas->setFilterExpression(
                QString::fromStdString(request.filter_expression),
                expression_error)) {
            report.error = "atlas filter expression rejected: " +
                           expression_error.toStdString();
            return report;
        }
    }
    if (!request.filename_expression.empty() &&
        !atlas->setFilenameExpression(
            QString::fromStdString(request.filename_expression),
            expression_error)) {
        report.error = "atlas filename expression rejected: " +
                       expression_error.toStdString();
        return report;
    }

    const int features = atlas->updateFeatures();
    if (features < 0) {
        report.error = "atlas feature update failed";
        return report;
    }
    if (features == 0) {
        report.error = "atlas matched no features";
        return report;
    }
    if (!atlas->beginRender()) {
        report.error = "atlas beginRender failed";
        return report;
    }

    // Per-feature export with explicit file naming (domain naming stays a
    // Paleo concern; QGIS owns the page iteration/render loop). Atlas
    // rendering parks every map item on the LAST feature's extent — the
    // pre-atlas extents are restored after endRender so the document the
    // user returns to is the document they left.
    QList<QgsLayoutItemMap*> maps;
    layout.layoutItems(maps);
    std::vector<QgsRectangle> map_extents;
    map_extents.reserve(maps.size());
    for (const QgsLayoutItemMap* map : maps) {
        map_extents.push_back(map->extent());
    }
    QgsLayoutExporter exporter(&layout);
    bool all_ok = true;
    std::string first_error;
    for (int i = 0; i < features && all_ok; ++i) {
        if (!atlas->seekTo(i)) {
            all_ok = false;
            first_error = "atlas seekTo(" + std::to_string(i) + ") failed";
            break;
        }
        char index[32];
        std::snprintf(index, sizeof(index), "%03d", i + 1);
        const std::string path =
            request.output_base + "_" + index + "." + request.format;
        QgsLayoutExporter::ExportResult result = QgsLayoutExporter::Success;
        if (request.format == "pdf") {
            QgsLayoutExporter::PdfExportSettings settings;
            settings.dpi = request.dpi > 0.0 ? request.dpi : kDefaultExportDpi;
            result = exporter.exportToPdf(QString::fromStdString(path), settings);
        } else if (request.format == "svg") {
            QgsLayoutExporter::SvgExportSettings settings;
            settings.dpi = request.dpi > 0.0 ? request.dpi : kDefaultExportDpi;
            result = exporter.exportToSvg(QString::fromStdString(path), settings);
        } else {
            QgsLayoutExporter::ImageExportSettings settings;
            settings.dpi = request.dpi > 0.0 ? request.dpi : kDefaultExportDpi;
            result = exporter.exportToImage(QString::fromStdString(path), settings);
        }
        if (result == QgsLayoutExporter::Success) {
            report.files.push_back(path);
            ++report.pages;
        } else {
            std::error_code remove_error;
            std::filesystem::remove(path, remove_error);
            all_ok = false;
            first_error = "atlas page " + std::to_string(i + 1) +
                          " export failed with code " +
                          std::to_string(static_cast<int>(result));
        }
    }
    atlas->endRender();
    {
        QList<QgsLayoutItemMap*> now_maps;
        layout.layoutItems(now_maps);
        for (int i = 0; i < now_maps.size() && i < static_cast<int>(map_extents.size()); ++i) {
            if (now_maps[i] != nullptr) {
                now_maps[i]->setExtent(map_extents[i]);
            }
        }
    }
    if (!all_ok) {
        for (const std::string& file : report.files) {
            std::error_code remove_error;
            std::filesystem::remove(file, remove_error);
        }
        report.files.clear();
        report.pages = 0;
        report.error = first_error;
        return report;
    }
    report.ok = true;
    return report;
}

}  // namespace pwb::qgis
