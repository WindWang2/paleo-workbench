#include <pwb/qgis/map_project_store.hpp>

#include <QDir>
#include <QString>

#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgsproject.h>
#include <qgsprojectviewsettings.h>
#include <qgsrectangle.h>
#include <qgsreferencedgeometry.h>

#include <pwb/qgis/map_session.hpp>

namespace pwb::qgis::map_project_store {

std::string default_qgs_path(const std::string& paleo_project_file) {
    const QString path = QString::fromStdString(paleo_project_file);
    QString stem = path;
    if (stem.endsWith(QStringLiteral(".paleo.json"), Qt::CaseInsensitive)) {
        stem.chop(static_cast<int>(QStringLiteral(".paleo.json").size()));
    } else if (stem.endsWith(QStringLiteral(".paleo"), Qt::CaseInsensitive)) {
        stem.chop(static_cast<int>(QStringLiteral(".paleo").size()));
    }
    return (stem + QStringLiteral(".qgs")).toStdString();
}

bool save(MapSession& session, const std::string& qgs_path,
          std::string* error) {
    QgsProject* project = session.project();
    if (project == nullptr) {
        if (error != nullptr) {
            *error = "map session is closed; cannot write the QGIS project";
        }
        return false;
    }
    // Remember the live view so a reopen lands where the user left off
    // (first live canvas wins; absent canvases keep the stored setting).
    for (QgsMapCanvas* canvas : session.canvases()) {
        if (canvas == nullptr) continue;
        const QgsRectangle extent = canvas->extent();
        if (extent.isEmpty()) break;
        project->viewSettings()->setDefaultViewExtent(
            QgsReferencedRectangle(extent, project->crs()));
        break;
    }
    const QString destination = QString::fromStdString(qgs_path);
    QDir().mkpath(QFileInfo(destination).absolutePath());
    // Two-phase around QGIS's truncate-in-place write (4.2 has no atomic
    // project write): move the previous file aside, write, restore on
    // failure, drop the backup on success. A crash mid-write can still
    // truncate the fresh file, but the LAST GOOD state is recoverable
    // from the backup and the open path degrades to the catalog
    // bindings honestly.
    const QString backup = destination + QStringLiteral(".pwb-bak");
    std::error_code ec;
    const bool had_previous =
        std::filesystem::exists(std::filesystem::path(qgs_path), ec);
    if (had_previous) {
        std::filesystem::rename(std::filesystem::path(qgs_path),
                                std::filesystem::path(backup.toStdString()),
                                ec);
        if (ec) {
            if (error != nullptr) {
                *error = "cannot stage the previous QGIS project aside: "
                    + ec.message();
            }
            return false;
        }
    }
    project->setFileName(destination);
    if (!project->write(destination)) {
        const QString detail = project->error();
        if (had_previous) {
            std::error_code restore_ec;
            std::filesystem::rename(
                std::filesystem::path(backup.toStdString()),
                std::filesystem::path(qgs_path), restore_ec);
        }
        if (error != nullptr) {
            *error = "QgsProject::write failed for '" + qgs_path + "'"
                + (detail.isEmpty() ? std::string()
                                    : ": " + detail.toStdString());
        }
        return false;
    }
    if (had_previous) {
        std::filesystem::remove(std::filesystem::path(backup.toStdString()),
                                ec);
    }
    return true;
}

RestoreReport load(MapSession& session, const std::string& qgs_path) {
    RestoreReport report;
    QgsProject* project = session.project();
    if (project == nullptr) {
        report.error = "map session is closed; cannot read the QGIS project";
        return report;
    }
    const QString source = QString::fromStdString(qgs_path);
    project->setFileName(source);
    // Project-read window: QgsProject::read services deferred events in
    // its provider-preload loop; a live bridge would then walk a
    // half-rebuilt tree (crash). Drop the bridges for the read, re-attach
    // after the tree is whole again.
    session.detach_canvas_bridges();
    for (QgsMapCanvas* canvas : session.canvases()) {
        if (canvas != nullptr) canvas->setLayers(QList<QgsMapLayer*>());
    }
    bool read_ok = false;
    try {
        read_ok = project->read(source);
    } catch (const std::exception& exc) {
        // Re-attach first: whatever the exception left behind, the
        // canvases must keep following the tree for the rest of the
        // session's life.
        session.attach_canvas_bridges();
        report.error = std::string("QgsProject::read threw for '") + qgs_path
            + "': " + exc.what();
        return report;
    } catch (...) {
        session.attach_canvas_bridges();
        report.error = "QgsProject::read threw for '" + qgs_path + "'";
        return report;
    }
    session.attach_canvas_bridges();
    if (!read_ok) {
        const QString detail = project->error();
        report.error = "QgsProject::read failed for '" + qgs_path + "'"
            + (detail.isEmpty() ? std::string()
                                : ": " + detail.toStdString());
        return report;
    }
    // Canvas destination CRS: QgsLayerTreeMapCanvasBridge keeps canvas
    // layer sets in step with the rebuilt tree, but only the host knows
    // the project CRS must be re-applied (QGIS app does the same after a
    // project read). The stored view extent restores the working scale.
    const QgsCoordinateReferenceSystem crs = project->crs();
    const QgsReferencedRectangle stored_view =
        project->viewSettings()->defaultViewExtent();
    for (QgsMapCanvas* canvas : session.canvases()) {
        if (canvas == nullptr) continue;
        if (crs.isValid()) canvas->setDestinationCrs(crs);
        if (!stored_view.isEmpty()
            && (!stored_view.crs().isValid()
                || !crs.isValid() || stored_view.crs() == crs)) {
            canvas->setExtent(stored_view);
        }
        canvas->refresh();
    }
    // Honest layer state: invalid layers stay in the tree but are
    // reported so the caller can re-materialize or surface them — a
    // broken provider is never papered over as a success.
    const auto layers = project->mapLayers();
    for (auto it = layers.constBegin(); it != layers.constEnd(); ++it) {
        QgsMapLayer* layer = it.value();
        if (layer == nullptr) continue;
        if (!layer->isValid()) {
            const QString detail =
                layer->error().message(QgsErrorMessage::Text);
            report.warnings.push_back(
                "layer '" + layer->name().toStdString()
                + "' restored but invalid (provider: "
                + detail.toStdString() + ")");
        } else {
            ++report.restored_layers;
        }
    }
    report.ok = true;
    return report;
}

}  // namespace pwb::qgis::map_project_store
