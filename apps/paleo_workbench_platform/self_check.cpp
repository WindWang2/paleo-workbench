#include "self_check.hpp"

#include "app_context.hpp"
#include "diagnostics.hpp"
#include "main_window.hpp"

#include <QCoreApplication>
#include <QColor>
#include <QDockWidget>
#include <QFile>
#include <QImage>
#include <QTemporaryDir>
#include <QThread>

#include <algorithm>
#include <numeric>

#include <qgsfeature.h>
#include <qgsgeometry.h>
#include <qgsmapcanvas.h>
#include <qgsmaprendererparalleljob.h>
#include <qgsmapsettings.h>
#include <qgsproject.h>
#include <qgsrasterlayer.h>
#include <qgsvectorfilewriter.h>
#include <qgsvectorlayer.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsproviderregistry.h>

#include <pwb/qgis/layout_service.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#if defined(PWB_WITH_CONV_01)
#include <pwb/mapping/extract.hpp>
#include <pwb/mapping/factor_grid_io.hpp>
#include <pwb/mapping/interpolator.hpp>
#endif

#if defined(PWB_WITH_WORKFLOW_ENGINE)
#include <pwb/workflow_engine/engine.hpp>
#include <pwb/workflow_engine/ops.hpp>
#endif

#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#endif

#include <filesystem>

namespace pwb::app {
namespace {

using Result = SelfCheck::Result;

// Memory layer -> GeoPackage via QGIS's own writer: the fixture is real
// provider data, not a fake layer.
QString makeFixtureGpkg(const QString& dir) {
    const QString uri_base = QStringLiteral(
        "Polygon?crs=EPSG:4326&field=id:integer&field=name:string(64)");
    QgsVectorLayer scratch(uri_base, QStringLiteral("scratch"),
                           QStringLiteral("memory"));
    if (!scratch.isValid()) return QString();
    if (!scratch.startEditing()) return QString();
    for (int i = 0; i < 3; ++i) {
        QgsFeature feature(scratch.fields());
        feature.setAttribute(0, i + 1);
        feature.setAttribute(1, QStringLiteral("poly-%1").arg(i));
        const double x0 = 110.0 + i * 2.0;
        const double y0 = 30.0 + i * 1.0;
        QgsGeometry geometry = QgsGeometry::fromWkt(QStringLiteral(
            "POLYGON((%1 %2, %3 %2, %3 %4, %1 %4, %1 %2))")
            .arg(x0).arg(y0).arg(x0 + 1.5).arg(y0 + 1.2));
        feature.setGeometry(geometry);
        scratch.addFeature(feature);
    }
    if (!scratch.commitChanges(true)) return QString();
    const QString path = dir + QStringLiteral("/fixture.gpkg");
    QgsVectorFileWriter::SaveVectorOptions options;
    options.driverName = QStringLiteral("GPKG");
    options.layerName = QStringLiteral("facies_boundary");
    QString error;
    QString new_filename;
    QString new_layer;
    const auto result = QgsVectorFileWriter::writeAsVectorFormatV3(
        &scratch, path, QgsCoordinateTransformContext(), options, &error,
        &new_filename, &new_layer);
    if (result != QgsVectorFileWriter::NoError) {
        diagnostics::critical(diagnostics::LogArea::Data,
                              QStringLiteral("fixture write failed: %1").arg(error));
        return QString();
    }
    return path + QStringLiteral("|layername=facies_boundary");
}

Result checkQgisRuntime() {
    Result r{QStringLiteral("qgis_runtime"), false, {}};
    if (!pwb::qgis::QgisRuntime::initialized()) {
        r.detail = QStringLiteral("QgisRuntime not initialized");
        return r;
    }
    const QString version = QString::fromStdString(
        pwb::qgis::QgisRuntime::qgis_version());
    if (version.isEmpty()) {
        r.detail = QStringLiteral("QGIS version probe empty");
        return r;
    }
    r.passed = true;
    r.detail = QStringLiteral("qgis %1, prefix %2").arg(
        version, QString::fromStdString(pwb::qgis::QgisRuntime::prefix_path()));
    return r;
}

Result checkProvidersAndCrs() {
    Result r{QStringLiteral("providers_crs"), false, {}};
    QgsProviderRegistry* registry = QgsProviderRegistry::instance();
    if (registry == nullptr) {
        r.detail = QStringLiteral("provider registry missing");
        return r;
    }
    const QStringList providers = registry->providerList();
    for (const char* required : {"ogr", "gdal", "memory"}) {
        if (!providers.contains(QLatin1String(required))) {
            r.detail = QStringLiteral("provider '%1' absent (have: %2)")
                           .arg(QLatin1String(required), providers.join(u','));
            return r;
        }
    }
    const QgsCoordinateReferenceSystem crs(QStringLiteral("EPSG:4326"));
    if (!crs.isValid()) {
        r.detail = QStringLiteral("EPSG:4326 CRS invalid (PROJ db unreachable?)");
        return r;
    }
    r.passed = true;
    r.detail = QStringLiteral("providers %1; EPSG:4326 ok")
                   .arg(providers.join(u','));
    return r;
}

Result checkPythonFree() {
    Result r{QStringLiteral("python_free_process"), false, {}};
    const diagnostics::EnvironmentReport env = diagnostics::probe_environment();
    r.detail = env.python_runtime_state;
    r.passed = env.python_runtime_state == QStringLiteral("verified")
               || env.python_runtime_state == QStringLiteral("not-probed");
    if (!r.passed) {
        diagnostics::critical(diagnostics::LogArea::Startup,
                              QStringLiteral("python runtime mapped: %1")
                                  .arg(env.python_runtime_state));
    }
    return r;
}

#if defined(PWB_WITH_CONV_01)
// Minimal mapping-kernel flow: JSON well records -> extract_factors ->
// IDW interpolate -> statistics. The kernels are the frozen numeric core
// of the Geological Factor Map product chain (CONV-01); this proves they
// are alive inside the product binary, not just linked.
Result checkMappingKernel() {
    Result r{QStringLiteral("mapping_kernel_minimal"), false, {}};
    const pwb::domain::Json wells = pwb::domain::Json::array(
        {pwb::domain::Json{{"well_id", "W1"}, {"x", 114.1}, {"y", 22.5},
                           {"porosity", 18.5}},
         pwb::domain::Json{{"well_id", "W2"}, {"x", 114.4}, {"y", 22.7},
                           {"porosity", 25.0}},
         pwb::domain::Json{{"well_id", "W3"}, {"x", 114.2}, {"y", 22.9},
                           {"porosity", 11.0}}});
    const pwb::mapping::FactorDataset dataset = pwb::mapping::extract_factors(
        wells, "porosity", pwb::mapping::ExtractOptions{});
    if (dataset.points.size() != 3) {
        r.detail = QStringLiteral("extract_factors returned %1 points (want 3)")
                       .arg(dataset.points.size());
        return r;
    }
    std::vector<pwb::mapping::SamplePoint> samples;
    for (const auto& point : dataset.points) {
        samples.push_back(
            pwb::mapping::SamplePoint{point.x, point.y, point.value});
    }
    pwb::mapping::InterpolateOptions options;
    options.method = "idw";
    options.grid_n = 16;
    const pwb::mapping::FactorGrid grid =
        pwb::mapping::interpolate_factor(samples, options);
    if (grid.statistics.min > grid.statistics.max
        || grid.statistics.min != grid.statistics.min /* NaN guard */) {
        r.detail = QStringLiteral("interpolate_factor statistics unusable");
        return r;
    }
    r.passed = true;
    r.detail = QStringLiteral("3 wells -> idw %1x%1 grid, min %2 max %3")
                   .arg(options.grid_n)
                   .arg(grid.statistics.min)
                   .arg(grid.statistics.max);
    return r;
}
#endif

#if defined(PWB_WITH_WORKFLOW_ENGINE)
// Minimal DAG: three nodes, one diamond dependency — the engine runs them
// in topological order on this thread. Proves the workflow closure
// (CONV-07) is alive in the product binary.
Result checkWorkflowDag() {
    Result r{QStringLiteral("workflow_dag_minimal"), false, {}};
    pwb::workflow_engine::NodeRegistry registry;
    pwb::workflow_engine::register_builtin_ops(registry);
    registry.register_op(
        "probe.mark",
        [](const pwb::workflow_engine::Json& /*params*/,
           const pwb::workflow_engine::CancelToken& /*token*/) {
            return pwb::workflow_engine::NodeResult{};
        });
    pwb::workflow_engine::WorkflowSpec spec;
    spec.workflow_id = "selfcheck.minimal_dag";
    spec.nodes = {
        {"a", "probe.mark", pwb::workflow_engine::Json{{"rank", 0}}, {}},
        {"b", "probe.mark", pwb::workflow_engine::Json{{"rank", 1}}, {"a"}},
        {"c", "probe.mark", pwb::workflow_engine::Json{{"rank", 2}}, {"a"}},
        {"d", "probe.mark", pwb::workflow_engine::Json{{"rank", 3}}, {"b", "c"}},
    };
    const std::vector<std::string> problems =
        pwb::workflow_engine::validate_spec(spec, registry);
    if (!problems.empty()) {
        r.detail = QStringLiteral("validate_spec: %1")
                       .arg(QString::fromStdString(problems[0]));
        return r;
    }
    const std::vector<std::string> topo =
        pwb::workflow_engine::topological_order(spec);
    // Diamond contract: a before b and c; b and c before d.
    auto rank = [&topo](const char* id) {
        return static_cast<int>(std::find(topo.begin(), topo.end(),
                                          std::string(id))
                                - topo.begin());
    };
    if (!(rank("a") < rank("b") && rank("a") < rank("c")
          && rank("b") < rank("d") && rank("c") < rank("d"))) {
        r.detail = QStringLiteral("topological order wrong: %1")
                       .arg(QString::fromStdString(
                           std::accumulate(topo.begin(), topo.end(), std::string(),
                                           [](const std::string& a, const std::string& b) {
                                               return a.empty() ? b : a + "," + b;
                                           })));
        return r;
    }
    pwb::workflow_engine::Engine engine(registry);
    const pwb::workflow_engine::WorkflowRun run = engine.run(spec);
    if (run.state != pwb::workflow_engine::RunState::completed) {
        r.detail = QStringLiteral("run state %1")
                       .arg(QString::fromLatin1(
                           pwb::workflow_engine::to_string(run.state)));
        return r;
    }
    for (const auto& node_run : run.node_runs) {
        if (node_run.state != pwb::workflow_engine::NodeState::succeeded) {
            r.detail = QStringLiteral("node %1 state %2 (%3)")
                           .arg(QString::fromStdString(node_run.node_id),
                                QString::fromLatin1(pwb::workflow_engine::to_string(
                                    node_run.state)),
                                QString::fromStdString(node_run.error));
            return r;
        }
    }
    r.passed = true;
    r.detail = QStringLiteral("4-node diamond completed in topo order");
    return r;
}
#endif

// Offscreen UI shell: the real MainWindow (menus, toolbar, canvas, docks)
// constructs and destroys cleanly over a real AppContext.
Result checkUiShell() {
    Result r{QStringLiteral("ui_shell"), false, {}};
    {
        AppContext context;
        MainWindow window(context);
        if (window.session() == nullptr) {
            r.detail = QStringLiteral("window has no session");
            return r;
        }
        if (!window.actionWired(QStringLiteral("pan"))) {
            r.detail = QStringLiteral("pan action not wired");
            return r;
        }
    }
    r.passed = true;
    r.detail = QStringLiteral("MainWindow + AppContext constructed/destroyed");
    return r;
}

}  // namespace

QVector<SelfCheck::Result> SelfCheck::run(const QString& source_dir) {
    QVector<Result> results;
    auto add = [&results](Result r) {
        results.append(r);
        if (!r.passed) {
            diagnostics::critical(diagnostics::LogArea::Startup,
                                  QStringLiteral("self-check %1 FAILED: %2")
                                      .arg(r.name, r.detail));
        }
    };

    add(checkQgisRuntime());
    add(checkProvidersAndCrs());
    add(checkPythonFree());
#if defined(PWB_WITH_CONV_01)
    add(checkMappingKernel());
#endif
#if defined(PWB_WITH_WORKFLOW_ENGINE)
    add(checkWorkflowDag());
#endif
    add(checkUiShell());

    // ---- data roundtrip battery: one window shared across the checks ---
    QTemporaryDir temp_dir;
    if (!temp_dir.isValid()) {
        add(Result{QStringLiteral("data_gpkg_roundtrip"), false,
                   QStringLiteral("cannot create temp dir")});
        return results;
    }
    const QString gpkg_uri = makeFixtureGpkg(temp_dir.path());
    AppContext context;
    MainWindow window(context);

    {
        Result r{QStringLiteral("data_gpkg_roundtrip"), false, {}};
        if (gpkg_uri.isEmpty()) {
            r.detail = QStringLiteral("fixture GeoPackage creation failed");
            add(r);
        } else {
            const QString load_error = window.loadFixtures(gpkg_uri, QString());
            if (!load_error.isEmpty()) {
                r.detail = QStringLiteral("fixture load: %1").arg(load_error);
            } else {
                pwb::qgis::MapSession& map = context.session().map();
                QgsVectorLayer* layer =
                    map.vectorLayerById("fixture.facies_boundary");
                if (layer == nullptr || !layer->isValid()
                    || layer->featureCount() != 3) {
                    r.detail = QStringLiteral(
                        "layer verification failed (count=%1)")
                                   .arg(layer != nullptr ? layer->featureCount() : -1);
                } else if (layer->crs().authid()
                               != QStringLiteral("EPSG:4326")
                           || map.project()->crs().authid()
                                  != QStringLiteral("EPSG:4326")) {
                    r.detail = QStringLiteral("CRS mismatch layer=%1 project=%2")
                                   .arg(layer->crs().authid(),
                                        map.project()->crs().authid());
                } else {
                    r.passed = true;
                    r.detail = QStringLiteral(
                        "3 features, layer+project CRS EPSG:4326");
                }
            }
            add(r);
        }
    }

    {
        // Render one frame synchronously through the same map-render job
        // engine the canvas uses (widget->grab() is not deterministic for
        // an unshown window under the offscreen platform).
        Result r{QStringLiteral("render_frame"), false, {}};
        QgsMapCanvas* canvas = window.findChild<QgsMapCanvas*>();
        QgsVectorLayer* layer =
            context.session().map().vectorLayerById("fixture.facies_boundary");
        if (canvas == nullptr || layer == nullptr) {
            r.detail = QStringLiteral("canvas or layer missing");
        } else {
            canvas->resize(800, 600);
            canvas->setExtent(layer->extent());
            QgsMapSettings settings = canvas->mapSettings();
            settings.setOutputSize(QSize(800, 600));
            settings.setBackgroundColor(Qt::white);
            QgsMapRendererParallelJob job(settings);
            job.start();
            job.waitForFinished();
            const QImage frame = job.renderedImage();
            bool non_white = false;
            for (int y = 0; y < frame.height() && !non_white; y += 8) {
                for (int x = 0; x < frame.width() && !non_white; x += 8) {
                    if (frame.pixel(x, y) != QColor(Qt::white).rgb()) {
                        non_white = true;
                    }
                }
            }
            if (frame.size() != QSize(800, 600)) {
                r.detail = QStringLiteral("frame size %1x%2")
                               .arg(frame.width()).arg(frame.height());
            } else if (!non_white) {
                r.detail = QStringLiteral("rendered frame is blank");
            } else {
                r.passed = true;
                r.detail = QStringLiteral("800x600 non-blank frame");
            }
        }
        add(r);
    }

    {
        Result r{QStringLiteral("layout_export"), false, {}};
        pwb::qgis::LayoutService layouts(context.session().map());
        pwb::qgis::LayoutSpec spec;
        const std::filesystem::path png =
            std::filesystem::path(temp_dir.path().toStdWString()) / "smoke.png";
        const std::string export_error =
            layouts.export_layout(spec, png, "png", 96.0);
        if (!export_error.empty()) {
            r.detail = QString::fromStdString(export_error);
        } else if (!std::filesystem::exists(png)) {
            r.detail = QStringLiteral("export reported success, file absent");
        } else {
            r.passed = true;
            r.detail = QStringLiteral("%1 bytes").arg(
                static_cast<qulonglong>(std::filesystem::file_size(png)));
        }
        add(r);
    }

#ifdef PWB_WITH_WELL_LOG
    {
        // Well-log dock embedding: the real WLE-backed host loads the
        // committed LAS fixture (dev tree; a missing file is reported, a
        // failed parse of a present fixture is a hard error).
        Result r{QStringLiteral("well_log_dock"), true, {}};
        const QString las_path =
            source_dir + QStringLiteral("/tests/fixtures/realdata/A1.Las");
        if (QFile::exists(las_path)) {
            const QString las_error = window.loadLasIntoDock(las_path);
            if (!las_error.isEmpty()) {
                r.passed = false;
                r.detail = las_error;
            } else {
                r.detail = QStringLiteral("LAS loaded into WLE dock");
            }
        } else {
            r.detail = QStringLiteral("skipped: LAS fixture absent (dev tree only)");
        }
        add(r);
    }
#endif

#if defined(PWB_WITH_DATA_INTEGRATION)
    {
        // Project lifecycle (M2): fresh project -> open layer -> edit ->
        // save through the real catalog transaction -> manifest checkpoint.
        Result r{QStringLiteral("project_lifecycle"), false, {}};
        const QString fresh_dir =
            temp_dir.path() + QStringLiteral("/fresh-project");
        const QString new_error =
            window.newProject(fresh_dir, QStringLiteral("selfcheck"));
        if (!new_error.isEmpty()) {
            r.detail = QStringLiteral("newProject: %1").arg(new_error);
        } else if (window.session()->store() == nullptr) {
            r.detail = QStringLiteral("newProject attached no store");
        } else {
            const QString open_error = window.openVectorLayer(gpkg_uri);
            if (!open_error.isEmpty()) {
                r.detail = QStringLiteral("layer open: %1").arg(open_error);
            } else if (!window.session()->edit()
                            .start_editing("fixture").empty()) {
                r.detail = QStringLiteral("edit session failed to start");
            } else {
                QgsVectorLayer* fresh_layer =
                    window.session()->map().vectorLayerById("fixture");
                const QgsPointXY v0 =
                    fresh_layer->getFeature(1).geometry().vertexAt(0);
                window.session()->edit().move_vertex(
                    "fixture", 1, 0, v0.x() + 0.2, v0.y());
                const QString save_error = window.commitActiveLayer(
                    std::filesystem::path(temp_dir.path().toStdWString())
                    / "selfcheck-staged");
                if (!save_error.isEmpty()) {
                    r.detail = QStringLiteral("commit: %1").arg(save_error);
                } else {
                    const std::filesystem::path manifest =
                        std::filesystem::path(fresh_dir.toStdWString())
                        / "selfcheck.artifacts" / "metadata" / "catalog.json";
                    if (!std::filesystem::exists(manifest)) {
                        r.detail = QStringLiteral(
                            "catalog.json manifest checkpoint missing");
                    } else {
                        r.passed = true;
                        r.detail = QStringLiteral(
                            "new->open->edit->commit; manifest checkpoint ok");
                    }
                }
            }
        }
        add(r);
    }

#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_SEISMIC_VIEWER) \
    && defined(PWB_WITH_SEISMIC_ATTRIBUTES)
    {
        // M3 chain: SEG-Y import -> attribute run -> slice display. The
        // real fixture only exists in dev trees; deployed packages skip
        // the check (like the LAS dock check above).
        Result r{QStringLiteral("seismic_chain"), true, {}};
        const QString sgy_path =
            source_dir + QStringLiteral("/tests/fixtures/realdata/tiny.sgy");
        if (QFile::exists(sgy_path)) {
            std::string import_error;
            const std::string imported = window.importSegy(sgy_path, &import_error);
            if (imported.empty()) {
                r.passed = false;
                r.detail = QString::fromStdString(import_error);
            } else {
                std::string run_error;
                const std::string request_id = window.runAttribute(
                    "seismic.rms_amplitude", {{"window", "21"}}, imported,
                    &run_error);
                if (request_id.empty()) {
                    r.passed = false;
                    r.detail = QString::fromStdString(run_error);
                } else {
                    std::string status;
                    for (int i = 0; i < 2000; ++i) {
                        const auto outcome = window.attributeOutcome(request_id);
                        status = outcome.status;
                        if (status != "queued" && status != "running"
                            && status != "publishing") {
                            if (status != "succeeded") {
                                r.passed = false;
                                r.detail = QString::fromStdString(
                                    status + ": " + outcome.error);
                            }
                            break;
                        }
                        QThread::msleep(5);
                    }
                    if (r.passed && status != "succeeded") {
                        r.passed = false;
                        r.detail = QStringLiteral("attribute run never finished");
                    } else if (r.passed) {
                        const QString view_error = window.openVolumeVersion(imported);
                        if (!view_error.isEmpty()) {
                            r.passed = false;
                            r.detail = view_error;
                        } else {
                            QDockWidget* seismic_dock =
                                window.findChild<QDockWidget*>("seismic-dock");
                            auto* slice =
                                static_cast<pwb::seismic_viewer::SeismicSliceWidget*>(
                                    seismic_dock != nullptr
                                        ? seismic_dock->widget()
                                        : nullptr);
                            if (slice == nullptr) {
                                r.passed = false;
                                r.detail = QStringLiteral("seismic dock missing");
                            } else {
                                for (int spin = 0;
                                     spin < 200
                                     && slice->state()
                                            != pwb::seismic_viewer::ViewerState::ok;
                                     ++spin) {
                                    QCoreApplication::processEvents();
                                    QThread::msleep(5);
                                }
                                if (slice->state()
                                    != pwb::seismic_viewer::ViewerState::ok) {
                                    r.passed = false;
                                    r.detail = QStringLiteral(
                                        "slice viewer did not reach ok state");
                                } else {
                                    r.detail = QStringLiteral(
                                        "import->rms->publish->view ok");
                                }
                            }
                        }
                    }
                }
            }
        } else {
            r.detail = QStringLiteral(
                "skipped: SEG-Y fixture absent (dev tree only)");
        }
        add(r);
    }
#endif
#endif

    // Service registry audit: every hard capability of this build has a
    // reachable service in the (still alive) context.
    {
        Result r{QStringLiteral("service_registry"), false, {}};
        const AppContext::ServiceAudit audit = context.auditServices();
        QStringList failed;
        for (const auto& entry : audit.entries) {
            if (!entry.ok) {
                failed << QStringLiteral("%1 (%2)")
                              .arg(entry.id, entry.detail);
            }
        }
        if (!audit.ok) {
            r.detail = failed.join(QStringLiteral("; "));
        } else {
            r.passed = true;
            r.detail = QStringLiteral("%1 hard services present").arg(
                QString::number(audit.entries.size()));
        }
        add(r);
    }

    return results;
}

QString SelfCheck::render(const QVector<Result>& results) {
    QString text;
    int failed = 0;
    for (const Result& result : results) {
        if (!result.passed) ++failed;
        text += QStringLiteral("%1  %2 — %3\n")
                    .arg(result.passed ? QStringLiteral("PASS")
                                       : QStringLiteral("FAIL"),
                         result.name, result.detail);
    }
    text += QStringLiteral("\n%1/%2 checks passed\n")
                .arg(results.size() - failed)
                .arg(results.size());
    return text;
}

}  // namespace pwb::app
