#include "main_window.hpp"

#include <QDockWidget>
#include <QFileDialog>
#include <QFileInfo>
#include <QInputDialog>
#include <QItemSelectionModel>
#include <QLabel>
#include <QLineEdit>
#include <QMenuBar>
#include <QMessageBox>
#include <QStatusBar>
#include <QToolBar>

// BEGIN CONV-30 — product job runtime wiring (top-level: needed by the
// ctor/dtor/closeEvent protocol and all migrated surfaces, independent of
// CONV_01/SEISMIC_* guards)
#include <QEventLoop>
#include <QProgressDialog>
#include <chrono>
#ifdef PWB_WITH_CONV_30
#include <algorithm>
#include <any>
#include <utility>
#include "job_center.hpp"
#include <pwb/job_runtime/qt/job_bridge.hpp>
#endif
// END CONV-30

// BEGIN VIZ-E — data/preview page assembly (plan P-A + V6).
#if defined(PWB_WITH_VIZ_E) && defined(PWB_WITH_CONV_30)
#include "viz_e_install.hpp"
#endif
// END VIZ-E

#include <fstream>

// CONV-PS platform services.
#include <QActionGroup>
#include <QApplication>
#include <QClipboard>
#include <QDialogButtonBox>
#include <QPushButton>
#include <QSettings>
#include <QTextBrowser>
#include <QVBoxLayout>

#include <pwb/platform_services/diagnostics_report.hpp>
#include <pwb/platform_services/settings_service.hpp>
#include <pwb/platform_services/theme_service.hpp>

#ifdef PWB_WITH_CONV_16
#include "factor_stats_dock.hpp"
#endif

#ifdef PWB_WITH_CONV_27
#include <qgsproject.h>
#include <qgsvectorlayer.h>

#include <pwb/tool_policy/layer_roles.hpp>
#include <pwb/ui/layer_properties.hpp>
#endif
#ifdef PWB_WITH_GEO3D_VIZ
#include "geo3d_dock.hpp"
#endif

// BEGIN VIZ-B
#ifdef PWB_WITH_VIZ_B
#include "viz_b_cross_well_dock.hpp"
#endif
// END VIZ-B

#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QSpinBox>
#include <QVBoxLayout>
#include <QDialog>
#include <QDialogButtonBox>
#include <QTimer>
#include <QEventLoop>

#include <pwb/application/adapters/volume_payload.hpp>
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#include <pwb/viz/seismic_volume.hpp>

// BEGIN VIZ-D — advanced seismic display install (menu affordances only;
// the display/pick logic lives in libs/seismic_viewer).
#include "viz_d_seismic_install.hpp"
// END VIZ-D
#endif

#include <qgsfeatureiterator.h>
#include <qgslayertreeview.h>
#include <qgsmapcanvas.h>
#include <qgsmapmouseevent.h>
#include <qgsmaptoolemitpoint.h>
#include <qgsmaptoolpan.h>
#include <qgsmaptoolzoom.h>
#include <qgsrasterlayer.h>
#include <qgsvectorlayer.h>
#include <qgsvertexmarker.h>

#ifdef PWB_WITH_DATA_INTEGRATION
#include <pwb/application/adapters/data_store.hpp>
#endif
#include <pwb/qgis/layout_service.hpp>
#ifdef PWB_WITH_CONV_29
#include <pwb/qgis/composition_layout_service.hpp>
#endif
#include <pwb/qgis/layer_adapter.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include "app_context.hpp"
#include "diagnostics.hpp"
#ifdef PWB_WITH_APP_SHELL
#include "app_shell.hpp"
#include <pwb/ui_shell/status_bar.hpp>
#endif

#ifdef PWB_WITH_CONV_01
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QSpinBox>
#include <QVBoxLayout>

#include <qgsjsonutils.h>
#include <qgsproject.h>
#include <qgsvectordataprovider.h>

#include <pwb/application/map_pipeline_runner.hpp>
#endif

#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_DATA_INTEGRATION)
#include <atomic>
#include <optional>
#include <thread>

#include <pwb/application/adapters/volume_payload.hpp>
#include <pwb/seismic_io/segy_reader.hpp>
#endif
#if defined(PWB_WITH_SEISMIC_SERVICE) && defined(PWB_WITH_DATA_INTEGRATION)
#include <QCoreApplication>

#include <pwb/seismic_io/segy_layout.hpp>
#endif

#ifdef PWB_WITH_WELL_LOG
#include "well_log_track_panel.hpp"
#include <pwb/viz/well_log_events.hpp>
#include <pwb/viz/well_log_host_widget.hpp>
#endif
#ifdef PWB_WITH_VIZ_A
#include "viz_a_install.hpp"
#endif

#ifdef PWB_WITH_GEO3D_VIZ
// VIZ-C: JobCenter* travels through a dynamic property; QVariant needs
// the metatype declared at global scope (outside namespace pwb::app).
Q_DECLARE_METATYPE(pwb::app::JobCenter*)
#endif

namespace pwb::app {

pwb::application::ProjectSession* MainWindow::session() const {
    return &context_.session();
}

namespace {
QString layerLabelFor(const pwb::application::DomainLayerFacts& facts) {
    if (!facts.role_label.empty()) {
        return QString::fromStdString(facts.role_label);
    }
    return QString::fromStdString(facts.layer_id);
}

#ifdef PWB_WITH_CONV_01
// The frozen 8-well porosity fixture of
// tests/test_geological_mapping_pipeline.py (sample_well_dataset): the well
// source behind the reserved "builtin.sample_wells" layer id.
pwb::domain::Json builtin_well_records() {
    const struct {
        const char* id;
        const char* name;
        double x;
        double y;
        double porosity;
    } wells[] = {
        {"W1", "井-1", 114.10, 22.50, 18.5},
        {"W2", "井-2", 114.25, 22.52, 22.3},
        {"W3", "井-3", 114.38, 22.48, 15.2},
        {"W4", "井-4", 114.15, 22.65, 24.1},
        {"W5", "井-5", 114.30, 22.68, 19.8},
        {"W6", "井-6", 114.42, 22.62, 12.4},
        {"W7", "井-7", 114.20, 22.80, 26.5},
        {"W8", "井-8", 114.35, 22.82, 21.0},
    };
    pwb::domain::Json records = pwb::domain::Json::array();
    for (const auto& well : wells) {
        records.push_back(pwb::domain::Json{
            {"well_id", well.id},
            {"name", well.name},
            {"x", well.x},
            {"y", well.y},
            {"孔隙度", well.porosity},
        });
    }
    return records;
}
#endif
}  // namespace


// Click-driven vertex mover built from public gui API: press near a vertex
// of the active (editing) layer grabs it, release commits one undoable
// move through EditController — no second undo stack, no mirror state.
class VertexMoveMapTool : public QgsMapToolEmitPoint {
public:
    VertexMoveMapTool(QgsMapCanvas* canvas, MainWindow* window)
        : QgsMapToolEmitPoint(canvas), window_(window) {
        setCursor(Qt::CrossCursor);
    }

    void canvasPressEvent(QgsMapMouseEvent* event) override {
        grabbed_ = nearestVertex(event->pos());
        if (!grabbed_.has_value()) return;
        marker_ = std::make_unique<QgsVertexMarker>(canvas());
        marker_->setIconType(QgsVertexMarker::ICON_CROSS);
        marker_->setColor(Qt::red);
        marker_->setIconSize(10);
        marker_->setCenter(QgsPointXY(grabbed_->x, grabbed_->y));
    }

    void canvasMoveEvent(QgsMapMouseEvent* event) override {
        if (marker_ != nullptr) marker_->setCenter(toMapCoordinates(event->pos()));
    }

    void canvasReleaseEvent(QgsMapMouseEvent* event) override {
        if (!grabbed_.has_value() || marker_ == nullptr) {
            marker_.reset();
            grabbed_.reset();
            return;
        }
        const Grab grab = *grabbed_;
        const QgsPointXY where = toMapCoordinates(event->pos());
        marker_.reset();
        grabbed_.reset();
        const std::string error = window_->session()->edit().move_vertex(
            grab.layer_id, static_cast<long long>(grab.fid), grab.vertex_index,
            where.x(), where.y());
        if (!error.empty()) {
            QMessageBox::warning(window_, QObject::tr("移动顶点"),
                                 QString::fromStdString(error));
        }
        window_->session()->map().refreshCanvases();
        // The undo/redo/dirty verdicts changed with the edit buffer.
        window_->refreshActionStates();
    }

private:
    struct Grab {
        std::string layer_id;
        QgsFeatureId fid = 0;
        int vertex_index = 0;
        double x = 0.0, y = 0.0;
    };

    std::optional<Grab> nearestVertex(const QPoint& pixel) {
        const QgsPointXY center = toMapCoordinates(pixel);
        const double tol = 12.0 * canvas()->mapSettings().mapUnitsPerPixel();
        double best = tol * tol;
        std::optional<Grab> best_grab;
        const auto layers = window_->session()->map().layerIdsTopFirst();
        for (const std::string& layer_id : layers) {
            QgsVectorLayer* layer =
                window_->session()->map().vectorLayerById(layer_id);
            if (layer == nullptr || !layer->isEditable()) continue;
            QgsFeatureIterator it = layer->getFeatures();
            QgsFeature feature;
            while (it.nextFeature(feature)) {
                if (!feature.hasGeometry()) continue;
                int at = 0, before = 0, after = 0; double dist = 0.0;
                const QgsPointXY vertex =
                    feature.geometry().closestVertex(center, at, before, after, dist);
                if (at < 0 || dist >= best) continue;
                best = dist;
                best_grab = Grab{layer_id, feature.id(), at, vertex.x(), vertex.y()};
            }
        }
        return best_grab;
    }

    MainWindow* window_;
    std::optional<Grab> grabbed_;
    std::unique_ptr<QgsVertexMarker> marker_;
};


MainWindow::MainWindow(AppContext& context, QWidget* parent,
                       QSettings* services_settings)
    : QMainWindow(parent), owned_context_(nullptr), context_(context) {
    init_shell(services_settings);
}

MainWindow::MainWindow(QWidget* parent, QSettings* services_settings)
    : QMainWindow(parent),
      owned_context_(std::make_unique<AppContext>()),
      context_(*owned_context_) {
    init_shell(services_settings);
}

void MainWindow::init_shell(QSettings* services_settings) {
#ifdef PWB_WITH_CONV_30
    // CONV-30 — the job runtime owns every background task; create it
    // first so the surfaces below can submit through it. The quit drain
    // (aboutToQuit → bounded scheduler drain) is installed here.
    job_center_ = std::make_unique<JobCenter>();
#endif
#if defined(PWB_WITH_SEISMIC_SERVICE) && defined(PWB_WITH_DATA_INTEGRATION)
    // Native tiled volume service: PWBVOL1 versions open lazily through the
    // tile cache; the budget honours PWB_SEISMIC_TILE_CACHE_BYTES.
    seismic_volume_service_ =
        std::make_unique<pwb::seismic_service::SeismicVolumeService>();
#endif
    dirty_close_responder_ = [this]() {
        return QMessageBox::question(
            this, tr("未提交的修改"),
            tr("当前编辑会话有未提交的修改。保存、放弃还是取消关闭？"),
            QMessageBox::Save | QMessageBox::Discard | QMessageBox::Cancel);
    };
    discard_confirm_responder_ = [this]() {
        return QMessageBox::question(
            this, tr("放弃编辑"), tr("确定放弃当前图层的全部未提交修改？"),
            QMessageBox::Yes | QMessageBox::No, QMessageBox::No);
    };
    buildUi();
    buildMenusAndToolbar();
    connectActions();
    setWindowTitle(tr("Paleo Workbench Platform (C++/QGIS)"));
    resize(1280, 800);

    // CONV-PS: platform services own the unified settings store, the theme
    // lifecycle and the window layout. Restore runs after the docks exist
    // (restoreState needs their objectNames) and before show().
    if (services_settings != nullptr) {
        services_settings_ = services_settings;  // injected: never owned
    } else {
        owned_services_settings_ = std::make_unique<QSettings>(
            pwb::platform_services::settings_organization(),
            pwb::platform_services::settings_application());
        services_settings_ = owned_services_settings_.get();
    }
    theme_service_ =
        std::make_unique<pwb::platform_services::ThemeService>(this);
    theme_service_->set_store(services_settings_);
    connect(theme_service_.get(),
            &pwb::platform_services::ThemeService::theme_changed, this,
            [this](const QString&, const QString&) {
                theme_service_->apply(*this);
                syncThemeMenuChecks();
            });
    theme_service_->load_persisted(*services_settings_);
    buildPlatformMenus();
    pwb::platform_services::restore_window_layout(*services_settings_, *this);
    // Apply the restored sheet once the widget tree is complete (and sync
    // the checkable theme/density actions to the restored state).
    theme_service_->apply(*this);
    syncThemeMenuChecks();
}

MainWindow::~MainWindow() {
#ifdef PWB_WITH_CONV_30
    // CONV-30 — stop job bodies at their next safe point and drain with a
    // bounded wait so no job can touch members during teardown (the
    // declared-last JobCenter member would otherwise die first anyway;
    // doing it here keeps the ordering explicit and testable).
    if (job_center_ != nullptr) job_center_->shutdown_workers(1000);
#endif
#ifdef PWB_WITH_APP_SHELL
    // Page workers stop before the session/canvas teardown (the composite
    // document's canvas is the session canvas — Python shutdown_workers
    // parity; idempotent).
    if (app_shell_ != nullptr) app_shell_->shutdown_workers();
#endif
    // Ordered teardown must run while every member the signal paths touch
    // (actions_, status label, canvas) is still alive: member destruction
    // would otherwise kill the action set before the session, and
    // MapSession::close() -> unsetMapTool -> mapToolSet -> refresh would
    // use the destroyed members (observed as a segfault in the integrated
    // build). ProjectSession::close()/MapSession::close() are idempotent
    // when closeEvent already ran.
    context_.session().close();
}

void MainWindow::buildUi() {
    canvas_ = context_.session().map().createCanvas(this);
#ifdef PWB_WITH_APP_SHELL
    // W5/UI-17 — the page-navigation shell hosts the composite document;
    // the session canvas is its central canvas (same widget, reparented —
    // the session's attachCanvas pointer stays valid).
    app_shell_ = new AppShell(this);
    app_shell_->install_canvas(canvas_);
    setCentralWidget(app_shell_);
#else
    setCentralWidget(canvas_);
#endif
    context_.session().attachCanvas(canvas_);

    auto* dock = new QDockWidget(tr("图层"), this);
    dock->setObjectName(QStringLiteral("layer-tree-dock"));
#ifdef PWB_WITH_CONV_27
    // Domain-aware tree panel: join-key active-layer sync (no row-index
    // mapping), native group/rename/context menu, edit indicators.
    layer_panel_ = new pwb::ui::LayerTreePanel(
        context_.session().map(), canvas_, [this](const std::string& id) {
            const auto it = facts_.find(id);
            return it == facts_.end()
                ? std::optional<pwb::application::DomainLayerFacts>{}
                : std::optional<pwb::application::DomainLayerFacts>(
                      it->second);
        }, this);
    dock->setWidget(layer_panel_);
    tree_ = layer_panel_->view();
#else
    tree_ = context_.session().map().createLayerTree(dock);
    dock->setWidget(tree_);
#endif
    addDockWidget(Qt::LeftDockWidgetArea, dock);

    status_label_ = new QLabel(QStringLiteral("ready"), this);
    statusBar()->addWidget(status_label_);
#ifdef PWB_WITH_WELL_LOG
    cursor_label_ = new QLabel(this);
    cursor_label_->hide(); // appears with the first crosshair event
    statusBar()->addPermanentWidget(cursor_label_);
#endif

#ifdef PWB_WITH_CONV_16
    // conv-16: read-only factor statistics HUD (FactorGrid.statistics).
    factor_dock_ = new FactorStatsDock(this);
    addDockWidget(Qt::RightDockWidgetArea, factor_dock_);
#endif

// BEGIN CONV-GEO3D
#ifdef PWB_WITH_GEO3D_VIZ
    // Native 3D geomodel viewer dock: Qt6 viewport + workspace controller
    // (no Python in the product chain). Well selections re-broadcast to
    // the 2D map seam via Geo3DDock::well_selected.
    geo3d_dock_ = new Geo3DDock(this);
    addDockWidget(Qt::RightDockWidgetArea, geo3d_dock_);
    connect(geo3d_dock_, &Geo3DDock::well_selected, this,
            [this](const QString& well) {
                statusBar()->showMessage(tr("3D 选中井: %1").arg(well), 5000);
            });
    // VIZ-C: expose the JobCenter so the dock's joint host (created
    // lazily on first use) can submit volume-load jobs.
    setProperty("pwb_job_center",
                QVariant::fromValue(static_cast<pwb::app::JobCenter*>(
                    job_center_.get())));
#endif
// END CONV-GEO3D

// BEGIN VIZ-B
#ifdef PWB_WITH_VIZ_B
    // Cross-well correlation & well-tie dock (line B): section canvas +
    // DTW propagation through the JobCenter + link editor/export
    // bindings + sidecar persistence. All logic lives in the dock.
    viz_b_dock_ = new pwb::app::VizBCrossWellDock(
        job_center_.get(), this);
    viz_b_dock_->setObjectName(QStringLiteral("viz-b-cross-well-dock"));
    addDockWidget(Qt::RightDockWidgetArea, viz_b_dock_);
    connect(viz_b_dock_, &pwb::app::VizBCrossWellDock::status_message,
            this, [this](const QString& message) {
                statusBar()->showMessage(message, 5000);
            });
#endif
// END VIZ-B

#ifdef PWB_WITH_WELL_LOG
    // C's WLE-backed well-log host in a dock (same Qt ABI, one process;
    // no Python). Same-session ownership: dies with the window.
    auto* well_log_dock = new QDockWidget(tr("测井"), this);
    well_log_dock->setObjectName(QStringLiteral("well-log-dock"));
    auto* well_log_host = new pwb::viz::WellLogHostWidget(well_log_dock);
    well_log_dock->setWidget(well_log_host);
    addDockWidget(Qt::RightDockWidgetArea, well_log_dock);

    // Native track settings (this branch): layout/template/export panel
    // bound to the host; interpretation events surface in the status bar.
    auto* track_panel_dock = new QDockWidget(tr("测井轨道"), this);
    track_panel_dock->setObjectName(QStringLiteral("well-log-track-panel"));
    auto* track_panel = new WellLogTrackPanel(track_panel_dock);
    track_panel_dock->setWidget(track_panel);
    addDockWidget(Qt::RightDockWidgetArea, track_panel_dock);
    track_panel->bind(well_log_host);
    well_log_host->set_cursor_callback(
        [this](const pwb::viz::WellLogCursorEvent& event) {
            if (!event.valid) {
                cursor_label_->hide();
                return;
            }
            cursor_label_->setText(tr("深度 %1 %2")
                                       .arg(event.depth)
                                       .arg(QString::fromStdString(event.unit)));
            cursor_label_->show();
        });
    well_log_host->set_interpretation_callback(
        [this](const pwb::viz::WellLogInterpretationEvent& event) {
            const QString label = QString::fromStdString(event.label);
            if (event.kind ==
                pwb::viz::WellLogInterpretationEvent::Kind::marker_hit) {
                status_label_->setText(tr("地层顶部: %1 @ %2")
                                           .arg(label)
                                           .arg(event.top));
            } else {
                status_label_->setText(tr("相带证据: %1 [%2, %3] %4")
                                           .arg(label)
                                           .arg(event.top)
                                           .arg(event.bottom)
                                           .arg(QString::fromStdString(event.unit)));
            }
        });
#if defined(PWB_WITH_VIZ_A) && defined(PWB_WITH_CONV_30)
    // BEGIN VIZ-A — production wiring (preview provider + background LAS
    // loads through the JobCenter). One call; the body lives in
    // viz_a_install.cpp.
    viz_a::install(this, job_center_.get());
#endif
    // END VIZ-A
#endif
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
    // D's slice host in a dock (moc-free widget like the WLE host).
    seismic_dock_ = new QDockWidget(tr("地震视图"), this);
    seismic_dock_->setObjectName(QStringLiteral("seismic-dock"));
    slice_widget_ = new pwb::seismic_viewer::SeismicSliceWidget(seismic_dock_);
    seismic_dock_->setWidget(slice_widget_);
    addDockWidget(Qt::RightDockWidgetArea, seismic_dock_);
#endif
// BEGIN VIZ-D — remember the advanced-display host for the menu install
// (the widget itself owns the VD/wiggle/polarity/clip/pick machinery).
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
    viz_d_seismic_host_ = slice_widget_;
#endif
// END VIZ-D

    // BEGIN VIZ-E — data page dock (asset selection → preview/chart →
    // export loop; the page composes ui_pages_data + viz_charts hosts).
#if defined(PWB_WITH_VIZ_E) && defined(PWB_WITH_CONV_30)
    viz_e_data_dock_ =
        pwb::viz_e::install_data_dock(this, job_center_.get());
#endif
    // END VIZ-E

    // Tools are canvas-parented; MapSession teardown unsets them first.
    pan_tool_ = new QgsMapToolPan(canvas_);
    zoom_in_tool_ = new QgsMapToolZoom(canvas_, false);
    zoom_out_tool_ = new QgsMapToolZoom(canvas_, true);
    vertex_tool_ = new VertexMoveMapTool(canvas_, this);
    canvas_->setMapTool(pan_tool_);
    context_.session().set_current_tool("pan");

    connect(canvas_, &QgsMapCanvas::mapToolSet, this,
            [this]() { onCanvasMapToolChanged(); });
#ifndef PWB_WITH_CONV_27
    connect(tree_->selectionModel(), &QItemSelectionModel::currentChanged, this,
            [this]() { onActiveLayerChanged(); });
#endif
#ifdef PWB_WITH_CONV_27
    install_conv27_surface();
#endif
#ifdef PWB_WITH_APP_SHELL
    wire_app_shell();
#endif
}

#ifdef PWB_WITH_APP_SHELL
void MainWindow::wire_app_shell() {
    // 主状态条入宿主原生槽位（Python dock_host=QMainWindow parity:
    // AppShell parks its StatusBar on the window's statusBar, stretch 1).
    statusBar()->addWidget(app_shell_->status_bar(), 1);

    connect(app_shell_, &AppShell::status_message, this,
            [this](const QString& message) {
                if (status_label_ != nullptr) status_label_->setText(message);
            });
    connect(app_shell_, &AppShell::about_requested, this,
            [this] { showAboutDialog(); });
#ifdef PWB_WITH_DATA_INTEGRATION
    connect(app_shell_, &AppShell::new_project_requested, this,
            [this] { newProjectDialog(); });
    connect(app_shell_, &AppShell::open_project_requested, this,
            [this] { openProjectDialog(); });
#endif
    connect(app_shell_, &AppShell::theme_requested, this,
            [this](const QString& value) {
                if (theme_service_ != nullptr) {
                    theme_service_->set_theme(
                        pwb::platform_services::theme_from_string(
                            value.toStdString()));
                }
            });
    connect(app_shell_, &AppShell::density_requested, this,
            [this](const QString& value) {
                if (theme_service_ == nullptr) return;
                if (value.isEmpty()) {
                    theme_service_->toggle_density();
                } else {
                    theme_service_->set_density(
                        pwb::platform_services::density_from_string(
                            value.toStdString()));
                }
            });
    // Deferred request surfaces (no production handler yet — recorded in
    // the integration ledger, never silently faked):
    //   save_project_requested / open_sample_project_requested /
    //   properties_requested / preview_settings_requested.
}
#endif

void MainWindow::buildMenusAndToolbar() {
    // Actions materialize from the policy vocabulary; labels/shortcuts are
    // presentation, enablement/visibility/checked stay policy-derived.
    struct Wire {
        const char* id;
        const char* text;
        QKeySequence shortcut;
    };
    const Wire wired[] = {
        {"reference_import", QT_TRANSLATE_NOOP("MainWindow", "打开矢量图层…"),
         QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_O)},
        {"layer_new", QT_TRANSLATE_NOOP("MainWindow", "打开栅格底图…"),
         QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_R)},
        {"pan", QT_TRANSLATE_NOOP("MainWindow", "平移"), QKeySequence()},
        {"zoom_in", QT_TRANSLATE_NOOP("MainWindow", "放大"), QKeySequence()},
        {"zoom_out", QT_TRANSLATE_NOOP("MainWindow", "缩小"), QKeySequence()},
        {"full_extent", QT_TRANSLATE_NOOP("MainWindow", "全图"), QKeySequence(Qt::Key_F)},
        {"refresh", QT_TRANSLATE_NOOP("MainWindow", "刷新"), QKeySequence(Qt::Key_F5)},
        {"toggle_editing", QT_TRANSLATE_NOOP("MainWindow", "开始/停止编辑"),
         QKeySequence(Qt::Key_F2)},
        {"vertex", QT_TRANSLATE_NOOP("MainWindow", "移动顶点"), QKeySequence(Qt::Key_V)},
        {"undo", QT_TRANSLATE_NOOP("MainWindow", "撤销"), QKeySequence::Undo},
        {"redo", QT_TRANSLATE_NOOP("MainWindow", "重做"), QKeySequence::Redo},
        {"save_edits", QT_TRANSLATE_NOOP("MainWindow", "提交编辑"),
         QKeySequence::Save},
        {"rollback", QT_TRANSLATE_NOOP("MainWindow", "放弃编辑"),
         QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_Z)},
        {"map_export", QT_TRANSLATE_NOOP("MainWindow", "导出布局…"),
         QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_P)},
#ifdef PWB_WITH_CONV_27
        {"select", QT_TRANSLATE_NOOP("MainWindow", "选择要素"),
         QKeySequence()},
        {"add_point", QT_TRANSLATE_NOOP("MainWindow", "添加点"),
         QKeySequence()},
        {"add_line", QT_TRANSLATE_NOOP("MainWindow", "添加线"),
         QKeySequence()},
        {"add_polygon", QT_TRANSLATE_NOOP("MainWindow", "添加面"),
         QKeySequence()},
        {"delete_selected", QT_TRANSLATE_NOOP("MainWindow", "删除所选"),
         QKeySequence(Qt::Key_Delete)},
#endif
#ifdef PWB_WITH_CONV_01
        {"factor_workbench", QT_TRANSLATE_NOOP("MainWindow", "地质因子图…"),
         QKeySequence(Qt::CTRL | Qt::Key_G)},
#endif
    };

    refreshActionStates();  // materializes one QAction per tool id
    for (const Wire& wire : wired) {
        QAction* action = actions_.action(wire.id);
        if (action == nullptr) continue;   // vocabulary drift: keep honest
        action->setText(tr(wire.text));
        if (!wire.shortcut.isEmpty()) action->setShortcut(wire.shortcut);
    }

    QMenu* file_menu = menuBar()->addMenu(tr("文件(&F)"));
#ifdef PWB_WITH_DATA_INTEGRATION
    file_menu->addAction(tr("新建工程…"), this,
                         &MainWindow::newProjectDialog,
                         QKeySequence::New);
    file_menu->addAction(tr("打开工程…"), this,
                         &MainWindow::openProjectDialog, QKeySequence::Open);
#endif
    file_menu->addAction(actions_.action("reference_import"));
    file_menu->addAction(actions_.action("layer_new"));
    file_menu->addSeparator();
    file_menu->addAction(actions_.action("map_export"));
    file_menu->addSeparator();
    // CONV-PS recent-projects MRU (populated after the settings store is
    // bound in the constructor).
    recent_projects_menu_ = file_menu->addMenu(tr("最近工程(&R)"));
    file_menu->addAction(tr("退出"), this, &MainWindow::close,
                         QKeySequence::Quit);

    QMenu* edit_menu = menuBar()->addMenu(tr("编辑(&E)"));
    edit_menu->addAction(actions_.action("toggle_editing"));
    edit_menu->addSeparator();
    edit_menu->addAction(actions_.action("vertex"));
    edit_menu->addAction(actions_.action("undo"));
    edit_menu->addAction(actions_.action("redo"));
    edit_menu->addSeparator();
    edit_menu->addAction(actions_.action("save_edits"));
    edit_menu->addAction(actions_.action("rollback"));

    QMenu* view_menu = menuBar()->addMenu(tr("视图(&V)"));
    view_menu->addAction(actions_.action("pan"));
    view_menu->addAction(actions_.action("zoom_in"));
    view_menu->addAction(actions_.action("zoom_out"));
    view_menu->addAction(actions_.action("full_extent"));
    view_menu->addSeparator();
    view_menu->addAction(actions_.action("refresh"));
#ifdef PWB_WITH_CONV_27
    view_menu->addSeparator();
    view_menu->addAction(tr("重置布局"), this, &MainWindow::resetLayoutState);
#endif

#if defined(PWB_WITH_SEISMIC_IO) || defined(PWB_WITH_SEISMIC_VIEWER)
    QMenu* seismic_menu = nullptr;
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_SEISMIC_ATTRIBUTES) \
    && defined(PWB_WITH_DATA_INTEGRATION)
    seismic_menu = menuBar()->addMenu(tr("地震(&S)"));
    seismic_menu->addAction(tr("计算属性…"), this,
                            &MainWindow::runAttributeDialog,
                            QKeySequence(Qt::CTRL | Qt::Key_U));
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
    seismic_menu->addAction(tr("打开体版本…"), this,
                            &MainWindow::openVolumeDialog);
#endif
#endif
// BEGIN VIZ-D — 地平线拾取 menu entries on the advanced seismic display.
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
    if (seismic_menu == nullptr) {
        seismic_menu = menuBar()->addMenu(tr("地震(&S)"));
    }
    if (viz_d_seismic_host_ != nullptr) {
        pwb::viz_d::add_seismic_horizon_menu_actions(*seismic_menu,
                                                     *viz_d_seismic_host_);
    }
#endif
// END VIZ-D
#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_DATA_INTEGRATION)
    if (seismic_menu == nullptr) {
        seismic_menu = menuBar()->addMenu(tr("地震(&S)"));
    }
    seismic_menu->addAction(tr("导入 SEG-Y…"), this,
                            &MainWindow::importSegyDialog);
#endif
#endif

#ifdef PWB_WITH_CONV_01
    QMenu* geology_menu = menuBar()->addMenu(tr("地质(&G)"));
    geology_menu->addAction(actions_.action("factor_workbench"));
#endif

    auto* toolbar = addToolBar(tr("地图工具"));
    toolbar->setObjectName(QStringLiteral("map-toolbar"));
    toolbar->addAction(actions_.action("reference_import"));
    toolbar->addAction(actions_.action("layer_new"));
    toolbar->addSeparator();
    toolbar->addAction(actions_.action("pan"));
    toolbar->addAction(actions_.action("zoom_in"));
    toolbar->addAction(actions_.action("zoom_out"));
    toolbar->addAction(actions_.action("full_extent"));
    toolbar->addSeparator();
    toolbar->addAction(actions_.action("toggle_editing"));
    toolbar->addAction(actions_.action("vertex"));
#ifdef PWB_WITH_CONV_27
    toolbar->addAction(actions_.action("select"));
    toolbar->addAction(actions_.action("add_point"));
    toolbar->addAction(actions_.action("add_line"));
    toolbar->addAction(actions_.action("add_polygon"));
    toolbar->addAction(actions_.action("delete_selected"));
    toolbar->addSeparator();
#endif
    toolbar->addAction(actions_.action("undo"));
    toolbar->addAction(actions_.action("redo"));
    toolbar->addAction(actions_.action("save_edits"));
    toolbar->addAction(actions_.action("rollback"));
    toolbar->addSeparator();
    toolbar->addAction(actions_.action("map_export"));
}

void MainWindow::connectActions() {
    auto wire = [this](const char* id, auto handler) {
        if (QAction* action = actions_.action(id)) {
            connect(action, &QAction::triggered, this, handler);
            wired_action_ids_.insert(id);
        }
    };
    wire("reference_import", &MainWindow::openVectorDialog);
    wire("layer_new", &MainWindow::openRasterDialog);
    wire("pan", &MainWindow::armPan);
    wire("zoom_in", &MainWindow::armZoomIn);
    wire("zoom_out", &MainWindow::armZoomOut);
    wire("full_extent", &MainWindow::zoomFullExtent);
    wire("refresh", &MainWindow::refreshMap);
    wire("toggle_editing", &MainWindow::toggleEditing);
    wire("vertex", &MainWindow::armVertexTool);
    wire("undo", &MainWindow::undoEdition);
    wire("redo", &MainWindow::redoEdition);
    wire("save_edits", &MainWindow::saveEdits);
    wire("rollback", &MainWindow::rollBackEdits);
    wire("map_export", &MainWindow::exportLayoutDialog);
#ifdef PWB_WITH_CONV_27
    wire("select", [this]() { edit_tools_->arm("select"); });
    wire("add_point", [this]() { edit_tools_->arm("add_point"); });
    wire("add_line", [this]() { edit_tools_->arm("add_line"); });
    wire("add_polygon", [this]() { edit_tools_->arm("add_polygon"); });
    wire("delete_selected", &MainWindow::deleteSelectedFeatures);
#endif
#ifdef PWB_WITH_CONV_01
    wire("factor_workbench", &MainWindow::geologicalFactorMapDialog);
#endif
}

void MainWindow::refreshActionStates() {
    const auto availability = pwb::tool_policy::evaluate_all(context_.session().snapshot());
    actions_.apply(availability);
    setStatusFromPolicy(availability);
#ifdef PWB_WITH_CONV_27
    // Edit tools retarget the canvas current layer on every active change.
    if (edit_tools_ != nullptr && context_.session().active_layer().has_value()) {
        edit_tools_->set_active_layer(context_.session().active_layer()->layer_id);
    }
    if (layer_panel_ != nullptr) layer_panel_->refresh_indicators();
    refresh_constraint_panel();
    // Readiness is a pure kernel pass over session state — keep it fresh
    // on layer/selection/edit changes, not only on stage switches.
    refresh_readiness();
#endif
}

void MainWindow::setStatusFromPolicy(
    const std::map<std::string, pwb::tool_policy::ToolAvailability>& availability) {
    int enabled = 0;
    for (const auto& [id, verdict] : availability) {
        (void)id;
        if (verdict.enabled) ++enabled;
    }
    if (status_label_ != nullptr) {
        status_label_->setText(tr("工具可用 %1/%2").arg(enabled).arg(availability.size()));
    }
}

// ------------------------------------------------------------ operations ----

QString MainWindow::openVectorLayer(const QString& path) {
    const QString layer_id = QFileInfo(path).completeBaseName();
    pwb::qgis::LayerBinding binding{
        layer_id.toStdString(), "", "", "vector"};
    std::string error;
    QgsVectorLayer* layer = context_.session().map().addVectorLayer(
        path.toStdString(), layer_id.toStdString(), binding, &error);
    if (layer == nullptr) return QString::fromStdString(error);
#ifdef PWB_WITH_CONV_27
    // Style sidecar written next to the layer's data file (QGIS QML
    // convention) — re-apply so styling survives reopen.
    pwb::ui::layer_style::apply_style_sidecar(layer, layer->source());
#endif

    pwb::application::DomainLayerFacts facts;
    facts.layer_id = layer_id.toStdString();
    facts.role = "facies_boundary";
    facts.role_label = layer_id.toStdString();
    facts.artifact_maturity = "draft";
    // Module-only authority: layers this shell opens itself are granted
    // write here; once B bindings exist the store becomes the authority.
    facts.write_granted = true;
    facts_[facts.layer_id] = facts;
    context_.session().set_active_layer(facts);
    canvas_->setExtent(layer->extent());
    refreshActionStates();
    return QString();
}

QString MainWindow::openRasterLayer(const QString& path) {
    const QString layer_id = QFileInfo(path).completeBaseName();
    pwb::qgis::LayerBinding binding{
        layer_id.toStdString(), "", "", "raster"};
    std::string error;
    QgsRasterLayer* layer = context_.session().map().addRasterLayer(
        path.toStdString(), layer_id.toStdString(), binding, &error);
    if (layer == nullptr) return QString::fromStdString(error);
    canvas_->setExtent(layer->extent());
    refreshActionStates();
    return QString();
}

void MainWindow::openVectorDialog() {
    const QString path = QFileDialog::getOpenFileName(
        this, tr("打开矢量图层"), QString(),
        tr("矢量数据 (*.gpkg *.geojson *.shp);;所有文件 (*)"));
    if (path.isEmpty()) return;
    const QString error = openVectorLayer(path);
    if (!error.isEmpty()) {
        QMessageBox::warning(this, tr("打开矢量图层"), error);
    }
}

void MainWindow::openRasterDialog() {
    const QString path = QFileDialog::getOpenFileName(
        this, tr("打开栅格底图"), QString(),
        tr("栅格数据 (*.tif *.tiff *.asc);;所有文件 (*)"));
    if (path.isEmpty()) return;
    const QString error = openRasterLayer(path);
    if (!error.isEmpty()) {
        QMessageBox::warning(this, tr("打开栅格底图"), error);
    }
}

#ifdef PWB_WITH_DATA_INTEGRATION
void MainWindow::openProjectDialog() {
    const QString path = QFileDialog::getOpenFileName(
        this, tr("打开工程"), QString(),
        tr("Paleo 工程 (*.paleo.json *.paleo);;所有文件 (*)"));
    if (path.isEmpty()) return;
    const QString error = openProject(path);
    if (!error.isEmpty()) {
        QMessageBox::warning(this, tr("打开工程"), error);
    }
}
#endif

#ifdef PWB_WITH_DATA_INTEGRATION
void MainWindow::newProjectDialog() {
    const QString dir = QFileDialog::getExistingDirectory(
        this, tr("新建工程 — 选择目录"));
    if (dir.isEmpty()) return;
    bool ok = false;
    const QString name = QInputDialog::getText(
        this, tr("新建工程"), tr("工程名称："), QLineEdit::Normal,
        tr("新工程"), &ok);
    if (!ok || name.isEmpty()) return;
    const QString error = newProject(dir, name);
    if (!error.isEmpty()) {
        QMessageBox::warning(this, tr("新建工程"), error);
    }
}

QString MainWindow::newProject(const QString& dir_path,
                               const QString& name) {
    if (context_.session().store() != nullptr) {
        return tr("已有工程打开（每窗口一个工程会话）");
    }
    // File-system-safe project name (also becomes the .paleo.json stem).
    std::string safe = name.toStdString();
    for (char& c : safe) {
        const bool ok_char = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
            || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-'
            || static_cast<unsigned char>(c) >= 0x80;  // keep CJK names
        if (!ok_char) c = '_';
    }
    if (safe.empty() || safe.front() == '.') safe = "project";
    std::error_code ec;
    const std::filesystem::path project_dir =
        std::filesystem::path(dir_path.toStdWString());
    std::filesystem::create_directories(project_dir, ec);
    if (ec) {
        return tr("无法创建目录：%1").arg(QString::fromStdString(ec.message()));
    }
    const std::filesystem::path project_file =
        project_dir / (safe + ".paleo.json");

    // Document via B's own factory (full default materialization, same as
    // the Python ProjectDocument.new).
    auto document = pwb::project::ProjectDocument::create_new(
        name.toStdString(), "");
    pwb::project::ProjectManager manager(project_file);
    auto saved = manager.save(document);
    if (!saved.is_ok()) {
        return QString::fromStdString("project save failed: "
                                       + saved.error().message);
    }

    // Empty catalog: open_read_write creates the schema (sqlite itself
    // never creates parent directories — make the metadata dir first).
    const std::filesystem::path catalog_file =
        pwb::project::catalog_sqlite_for(project_file);
    std::filesystem::create_directories(catalog_file.parent_path(), ec);
    if (ec) {
        return tr("无法创建 catalog 目录：%1").arg(
            QString::fromStdString(ec.message()));
    }
    pwb::catalog::CatalogRepository repository(catalog_file);
    auto writable = repository.open_read_write();
    if (!writable.is_ok()) {
        return QString::fromStdString("catalog init failed: "
                                       + writable.error().message);
    }

    // Seed the initial boundary asset with an empty GeoJSON version
    // through B's own run lifecycle (single-writer transaction; the
    // catalog rows never get hand-rolled from the platform).
    std::string open_error;
    auto store = pwb::application::PwbDataStore::open(project_file,
                                                      &open_error);
    if (store == nullptr) {
        return QString::fromStdString(open_error);
    }
    const std::filesystem::path staged_dir = project_dir / ".pwb-bootstrap";
    std::filesystem::create_directories(staged_dir, ec);
    const std::filesystem::path staged_geojson =
        staged_dir / "boundary-v1.geojson";
    {
        std::ofstream out(staged_geojson, std::ios::binary);
        out << "{\"type\":\"FeatureCollection\",\"features\":[]}";
        if (!out.good()) return tr("引导图层写入失败");
    }
    const pwb::domain::RunId run_id{std::string("run_bootstrap-0001")};
    pwb::data::RunRegistrationV1 registration;
    registration.run_id = run_id;
    registration.operation = "bootstrap";
    registration.generator = "pwb-platform";
    auto registered = store->coordinator().register_run(registration);
    if (!registered.is_ok()) {
        return QString::fromStdString("bootstrap register failed: "
                                       + registered.error().message);
    }
    pwb::data::PublishRequestV1 publish;
    publish.operation_id =
        pwb::domain::OperationId{std::string("pub_bootstrap-0001")};
    publish.run_id = run_id;
    publish.new_asset_name = "相带边界";
    publish.new_asset_type = "vector_boundary";
    publish.stage = pwb::domain::DataStage::Raw;
    pwb::data::StagedAssetV1 staged;
    staged.source_path = staged_geojson;
    staged.format = "GeoJSON";
    publish.products.push_back(std::move(staged));
    publish.result_metadata = pwb::domain::Json::object();
    auto published =
        store->coordinator().publish_run_result(publish, store->document());
    if (!published.is_ok()) {
        return QString::fromStdString("bootstrap publish failed: "
                                       + published.error().message);
    }
    (void)store->export_manifest();
    return openProject(QString::fromStdString(project_file.string()));
}

QString MainWindow::openProject(const QString& project_file) {
    if (context_.session().store() != nullptr) {
        return tr("已有工程打开（每窗口一个工程会话）");
    }
    std::string open_error;
    auto store = pwb::application::PwbDataStore::open(
        std::filesystem::path(project_file.toStdWString()), &open_error);
    if (store == nullptr) {
        return QString::fromStdString(open_error);
    }

    // B's startup contract: resume/roll back unfinished journals BEFORE
    // any new commit. Pending items stay blocking; surface them honestly.
    const pwb::data::RecoveryReportV1 recovery = store->recover();

    context_.session().set_store(store);
    context_.setProjectStore(store);

    // Materialize every bound GeoJSON layer as an explicit working copy —
    // the catalog payload file itself is read-only for the shell.
    auto snapshot = store->snapshot();
    if (!snapshot.is_ok()) {
        context_.session().set_store(nullptr);
        context_.setProjectStore(nullptr);
        return QString::fromStdString(snapshot.error().message);
    }
    std::map<std::string, const pwb::catalog::DataVersion*> versions;
    for (const auto& version : snapshot.value().catalog_versions) {
        versions[version.id.str()] = &version;
    }
    const std::filesystem::path project_dir =
        std::filesystem::path(project_file.toStdWString()).parent_path();
    const std::filesystem::path working_dir = project_dir / ".pwb-working";
    int opened = 0;
    int skipped = 0;
    std::string first_error;
    for (const pwb::workspace::LayerBinding& binding :
         snapshot.value().layer_bindings) {
        const auto it = versions.find(binding.source_version_id);
        // Vector payloads this shell can edit as working copies (staged
        // export is GeoJSON either way).
        if (it == versions.end() || it->second == nullptr || it->second->trashed
            || (it->second->format != "GeoJSON"
                && it->second->format != "GPKG")) {
            continue;
        }
        const std::filesystem::path payload =
            project_dir / it->second->path;
        std::error_code ec;
        if (!std::filesystem::exists(payload, ec)) {
            ++skipped;
            continue;
        }
        std::filesystem::create_directories(working_dir, ec);
        const std::filesystem::path working = working_dir
            / (binding.layer_id + payload.extension().string());
        std::filesystem::copy_file(
            payload, working, std::filesystem::copy_options::overwrite_existing,
            ec);
        if (ec) {
            if (first_error.empty()) {
                first_error = "working copy create failed for "
                    + binding.layer_id + ": " + ec.message();
            }
            ++skipped;
            continue;
        }
        pwb::qgis::LayerBinding qbinding{binding.layer_id,
                                         binding.source_asset_id,
                                         binding.source_version_id,
                                         "vector"};
        std::string add_error;
        QgsVectorLayer* layer = context_.session().map().addVectorLayer(
            working.string(), binding.layer_id, qbinding, &add_error);
#ifdef PWB_WITH_CONV_27
        if (layer != nullptr) {
            pwb::ui::layer_style::apply_style_sidecar(
                layer, layer->source());
        }
#endif
        if (layer == nullptr) {
            if (first_error.empty()) first_error = add_error;
            ++skipped;
            continue;
        }
        pwb::application::DomainLayerFacts facts;
        facts.layer_id = binding.layer_id;
        facts.role = binding.role.empty() ? "facies_boundary" : binding.role;
        facts.role_label = binding.layer_id;
        facts.artifact_maturity = "draft";
        // Working-copy grant: the bound catalog version authorizes edits on
        // the copy; the payload stays immutable.
        facts.write_granted = true;
        facts_[facts.layer_id] = facts;
        if (!context_.session().active_layer().has_value()) {
            context_.session().set_active_layer(facts);
            canvas_->setExtent(layer->extent());
        }
        ++opened;
    }
    refreshActionStates();
    QString summary = tr("工程已打开：%1 个绑定图层（%2 跳过）")
                          .arg(opened)
                          .arg(skipped);
    if (!recovery.pending.empty()) {
        summary += tr("；%1 个未决恢复项（阻塞冲突写入）")
                       .arg(recovery.pending.size());
    }
    if (!recovery.rolled_back.empty()) {
        summary += tr("；%1 个日志已回滚").arg(recovery.rolled_back.size());
    }
    statusBar()->showMessage(summary, 10000);
    if (!first_error.empty()) {
        return QString::fromStdString(first_error);
    }
    // Success: the project becomes the MRU head (native recent-projects).
    if (services_settings_ != nullptr) {
        pwb::platform_services::push_recent_project(*services_settings_,
                                                    project_file);
        refreshRecentProjects();
    }
// BEGIN VIZ-B
#ifdef PWB_WITH_VIZ_B
    if (viz_b_dock_ != nullptr) {
        // Flush + generation-bump + detach BEFORE switching: a pending
        // coalesced write must never land in the new project's sidecar,
        // and in-flight DTW results must drop on arrival.
        viz_b_dock_->handle_project_closed();
        viz_b_dock_->set_project_directory(
            QString::fromStdString(project_dir.string()));
        viz_b_dock_->restore_from_project();
    }
#endif
// END VIZ-B
    return QString();
}
#endif  // PWB_WITH_DATA_INTEGRATION

void MainWindow::armPan() {
    canvas_->setMapTool(pan_tool_);
}

void MainWindow::armZoomIn() {
    canvas_->setMapTool(zoom_in_tool_);
}

void MainWindow::armZoomOut() {
    canvas_->setMapTool(zoom_out_tool_);
}

void MainWindow::armVertexTool() {
    canvas_->setMapTool(vertex_tool_);
}

void MainWindow::zoomFullExtent() {
    context_.session().map().zoomToFullExtent(canvas_);
    refreshActionStates();
}

void MainWindow::refreshMap() {
    context_.session().map().refreshCanvases();
    refreshActionStates();
}

void MainWindow::toggleEditing() {
    const auto active = context_.session().active_layer();
    if (!active.has_value()) return;
    const std::string id = active->layer_id;
    if (context_.session().edit().editing(id)) {
        if (context_.session().edit().dirty(id)) {
            // Stop with pending edits goes through the same three-way
            // decision as dirty-close (no silent discard).
            const int choice = dirty_close_responder_();
            if (choice == QMessageBox::Cancel) return;
            if (choice == QMessageBox::Save) { saveEdits(); return; }
            rollBackEdits();
            return;
        }
        context_.session().edit().roll_back(id);
    } else {
        const std::string error = context_.session().edit().start_editing(id);
        if (!error.empty()) {
            QMessageBox::warning(this, tr("开始编辑"), QString::fromStdString(error));
        }
    }
    refreshActionStates();
}

void MainWindow::saveEdits() {
    const auto active = context_.session().active_layer();
    if (!active.has_value() || !context_.session().edit().editing(active->layer_id)) return;
    const std::filesystem::path staged_dir =
        std::filesystem::temp_directory_path() / "pwb-platform" / "staged";
    std::string error;
    const pwb::qgis::StagedAsset staged =
        context_.session().stage_commit(active->layer_id, staged_dir, &error);
    if (!error.empty()) {
        QMessageBox::warning(this, tr("提交编辑"),
            QString::fromStdString(error) + QStringLiteral("\n编辑已保留，可修复后重试。"));
        refreshActionStates();
        return;
    }
    statusBar()->showMessage(
        tr("已提交: %1 (sha256 %2…)")
            .arg(QString::fromStdString(staged.source_layer_id))
            .arg(QString::fromStdString(staged.sha256).left(12)),
        8000);
    refreshActionStates();
}

void MainWindow::rollBackEdits() {
    const auto active = context_.session().active_layer();
    if (!active.has_value()) return;
    if (context_.session().edit().dirty(active->layer_id)) {
        if (discard_confirm_responder_() != QMessageBox::Yes) return;
    }
    context_.session().edit().roll_back(active->layer_id);
    refreshActionStates();
}

void MainWindow::undoEdition() {
    const auto active = context_.session().active_layer();
    if (!active.has_value()) return;
    context_.session().edit().undo(active->layer_id);
    refreshActionStates();
}

void MainWindow::redoEdition() {
    const auto active = context_.session().active_layer();
    if (!active.has_value()) return;
    context_.session().edit().redo(active->layer_id);
    refreshActionStates();
}

#ifdef PWB_WITH_CONV_29
namespace {
// CONV-29: the platform's built-in export composition — an A4-landscape
// product page assembled from the live session state (map extent/CRS from
// the canvas, layers from the tree). It travels through the real native
// chain: composition JSON → layout_export kernel spec → shared spec
// executor → QgsLayout file + report.
std::string build_platform_composition() {
    pwb::domain::Json composition = pwb::domain::Json::object();
    composition["id"] = "comp_platform_export";
    composition["title"] = "平台导出构图";
    composition["paper_size"] = "A4";
    composition["orientation"] = "landscape";
    composition["width_mm"] = 297.0;
    composition["height_mm"] = 210.0;
    composition["dpi"] = 300.0;
    pwb::domain::Json elements = pwb::domain::Json::array();
    auto add_element = [&elements](const char* id, const char* type,
                                   double x, double y, double w, double h,
                                   long long z, pwb::domain::Json props) {
        pwb::domain::Json element = pwb::domain::Json::object();
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
    add_element("el_neatline", "neatline", 2.0, 2.0, 293.0, 206.0, 0,
                pwb::domain::Json::object());
    add_element("el_map", "main_map", 8.0, 16.0, 204.0, 164.0, 1,
                pwb::domain::Json::object());
    add_element("el_title", "title", 8.0, 3.0, 281.0, 10.0, 2,
                pwb::domain::Json::object(
                    {{"text", "古地理图"}, {"font_size", 14.0},
                     {"align", "center"}, {"color", "#000000"}}));
    add_element("el_legend", "legend", 218.0, 16.0, 71.0, 100.0, 3,
                pwb::domain::Json::object({{"items",
                                            pwb::domain::Json::array()}}));
    add_element("el_scale", "scale_bar", 8.0, 186.0, 44.0, 8.0, 4,
                pwb::domain::Json::object({{"units", ""}}));
    add_element("el_arrow", "north_arrow", 270.0, 186.0, 10.0, 15.0, 5,
                pwb::domain::Json::object());
    composition["elements"] = elements;
    composition["metadata"] = pwb::domain::Json::object();
    return composition.dump();
}
}  // namespace
#endif

void MainWindow::exportLayoutDialog() {
    const QString path = QFileDialog::getSaveFileName(
        this, tr("导出布局"), QString(),
        tr("PNG 图像 (*.png);;PDF 文档 (*.pdf);;SVG 矢量 (*.svg)"));
    if (path.isEmpty()) return;
    const QString suffix = QFileInfo(path).suffix().toLower();
#ifdef PWB_WITH_CONV_29
    // CONV-29: full native chain with pre-flight validation and screen/
    // export parity — no second layout authority, no Python.
    bool accepted = false;
    const double dpi = QInputDialog::getDouble(
        this, tr("导出布局"), tr("输出 DPI"), 300.0, 36.0, 1200.0, 0,
        &accepted);
    if (!accepted) return;

    const pwb::domain::Json canvas_state =
        pwb::domain::Json::parse(context_.session().map().canvas_state_json());
    const std::string composition = build_platform_composition();

    pwb::qgis::CompositionExportRequest request;
    request.format = suffix.toStdString();
    request.dpi = dpi;
    if (canvas_state.contains("extent")
        && canvas_state["extent"].is_array()
        && canvas_state["extent"].size() == 4) {
        request.has_extent = true;
        for (int i = 0; i < 4; ++i) {
            request.extent[i] = canvas_state["extent"][i].get<double>();
        }
    }
    request.crs = canvas_state.value("crs", std::string());

    pwb::qgis::CompositionLayoutService composition_layouts(context_.session().map());

    // Fail-closed pre-flight: hybrid/unmapped elements surface here,
    // itemized, before any page is written.
    const pwb::domain::Json validation =
        composition_layouts.validate_layout(composition, request);
    if (!validation.value("ok", false)) {
        QMessageBox::warning(
            this, tr("导出布局"),
            QString::fromStdString(validation.value(
                "failure", std::string("composition validation failed"))));
        return;
    }

    // Screen/export parity check (extent/CRS/layers/grid/legend).
    const pwb::domain::Json parity = composition_layouts.parity_report(
        context_.session().map().canvas_state_json(), composition, request);

    const pwb::domain::Json report = composition_layouts.export_layout(
        composition, std::filesystem::path(path.toStdWString()), request);
    if (!report.value("ok", false)) {
        QMessageBox::warning(
            this, tr("导出布局"),
            QString::fromStdString(
                report.value("failure", std::string("export failed"))));
        return;
    }
    QString status = tr("已导出: %1 (items=%2)")
                         .arg(path)
                         .arg(static_cast<qulonglong>(
                             report.value("items", static_cast<long long>(0))));
    const long long width_px =
        report.value("width_px", static_cast<long long>(0));
    if (width_px > 0) {
        status += tr(" %1×%2 px")
                      .arg(static_cast<qulonglong>(width_px))
                      .arg(static_cast<qulonglong>(report.value(
                          "height_px", static_cast<long long>(0))));
    }
    const pwb::domain::Json warnings = report.value(
        "warnings", pwb::domain::Json::array());
    if (warnings.is_array() && !warnings.empty()) {
        status += tr(" · 警告 %1 条").arg(static_cast<qulonglong>(warnings.size()));
    }
    if (!parity.value("equal", true)) {
        status += tr(" · 画布/导出存在差异");
    }
    statusBar()->showMessage(status, 8000);
#else
    pwb::qgis::LayoutService layouts(context_.session().map());
    pwb::qgis::LayoutSpec spec;
    const std::string error = layouts.export_layout(
        spec, std::filesystem::path(path.toStdWString()),
        suffix.toStdString(), 96.0);
    if (!error.empty()) {
        QMessageBox::warning(this, tr("导出布局"), QString::fromStdString(error));
    } else {
        statusBar()->showMessage(tr("已导出: %1").arg(path), 8000);
    }
#endif
}

#ifdef PWB_WITH_CONV_01
namespace {
// 地质因子图 re-runs regenerate the two product layers in place: drop the
// previous instance (join-key lookup, not the QGIS layer id) first.
void removeLayerById(QgsProject* project, const std::string& layer_id) {
    const auto layers = project->mapLayers();
    for (auto it = layers.constBegin(); it != layers.constEnd(); ++it) {
        if (pwb::qgis::layer_adapter::layer_id_of(it.value()) == layer_id) {
            project->removeMapLayer(it.key());
            return;
        }
    }
}
}  // namespace

QString MainWindow::collectFactorMapInputs(
    const QString& layer_id, const std::string& factor_name,
    pwb::domain::Json* records, std::string* crs) {
    // GUI-thread only: reads the QgsVectorLayer feature stream.
    if (layer_id == QStringLiteral("builtin.sample_wells")) {
        *records = builtin_well_records();
        *crs = "EPSG:4326";
        return QString();
    }
    QgsVectorLayer* layer =
        context_.session().map().vectorLayerById(layer_id.toStdString());
    if (layer == nullptr) {
        return QString::fromStdString("layer not found: "
                                      + layer_id.toStdString());
    }
    if (layer->geometryType() != Qgis::GeometryType::Point) {
        return QString::fromStdString("井点源必须是点图层："
                                      + layer_id.toStdString());
    }
    const QgsFields fields = layer->fields();
    int value_index = fields.indexOf(QString::fromStdString(factor_name));
    if (value_index < 0) value_index = fields.indexOf(QStringLiteral("value"));
    if (value_index < 0) {
        return QString::fromStdString("图层缺少因子取值字段（需要 "
                                      + factor_name
                                      + " 或 value 字段）："
                                      + layer_id.toStdString());
    }
    const int well_id_index = fields.indexOf(QStringLiteral("well_id"));
    const int name_index = fields.indexOf(QStringLiteral("name"));
    const int qc_index = fields.indexOf(QStringLiteral("qc_flag"));
    QgsFeatureIterator it = layer->getFeatures();
    QgsFeature feature;
    while (it.nextFeature(feature)) {
        if (!feature.hasGeometry()) continue;
        const QgsPointXY pt = feature.geometry().asPoint();
        pwb::domain::Json rec = pwb::domain::Json::object();
        rec["x"] = pt.x();
        rec["y"] = pt.y();
        if (well_id_index >= 0) {
            rec["well_id"] =
                feature.attribute(well_id_index).toString().toStdString();
        }
        if (name_index >= 0) {
            rec["name"] =
                feature.attribute(name_index).toString().toStdString();
        }
        if (qc_index >= 0) {
            rec["qc_flag"] =
                feature.attribute(qc_index).toString().toStdString();
        }
        bool numeric = false;
        const double value = feature.attribute(value_index).toDouble(&numeric);
        rec[factor_name] = numeric
            ? pwb::domain::Json(value)
            : pwb::domain::Json(
                  feature.attribute(value_index).toString().toStdString());
        records->push_back(std::move(rec));
    }
    *crs = layer->crs().authid().toStdString();
    return QString();
}

QString MainWindow::applyFactorMapOutcome(
    const pwb::application::MapPipelineOutcome& outcome,
    const std::string& factor_name, const std::string& crs) {
    // GUI-thread only: layers / canvas / facts registry.
    if (!outcome.ok) {
        // The kernel's validate() message verbatim (Python ValueError
        // wording is part of the contract).
        return QString::fromStdString(outcome.error);
    }

    // Idempotent re-run: regenerate the two product layers in place.
    const QString contour_id = QStringLiteral("factor.contour");
    const QString facies_id = QStringLiteral("factor.classification");
    removeLayerById(context_.session().map().project(), contour_id.toStdString());
    removeLayerById(context_.session().map().project(), facies_id.toStdString());
    facts_.erase(contour_id.toStdString());
    facts_.erase(facies_id.toStdString());

    const QString crs_param = QString::fromStdString(crs);
    const QString contour_uri =
        (crs_param.isEmpty() ? QStringLiteral("LineString?")
                             : QStringLiteral("LineString?crs=") + crs_param
                             + QStringLiteral("&"))
        + QStringLiteral(
              "field=level:double&field=label_text:string(64)"
              "&field=is_index_contour:integer&field=length:double"
              "&field=is_closed:integer&field=factor:string(64)"
              "&field=unit:string(16)");
    const QString facies_uri =
        (crs_param.isEmpty() ? QStringLiteral("Polygon?")
                             : QStringLiteral("Polygon?crs=") + crs_param
                             + QStringLiteral("&"))
        + QStringLiteral(
              "field=facies_id:integer&field=facies_name:string(64)"
              "&field=facies:string(64)&field=color:string(16)"
              "&field=area:double&field=area_unit:string(64)"
              "&field=area_percent:double&field=mean_value:double"
              "&field=area_approx_m2:double");

    auto add_product_layer = [&](const QString& layer_id,
                                 const QString& name, const QString& uri,
                                 const pwb::domain::Json& features,
                                 const char* role,
                                 QgsVectorLayer** out_layer) -> std::string {
        // Memory provider layer: MapSession::addVectorLayer pins the "ogr"
        // provider (file-backed payloads), so the in-memory product layers
        // are constructed directly and registered through the same
        // join-key adapter + project tree.
        auto* layer = new QgsVectorLayer(uri, name, QStringLiteral("memory"));
        if (!layer->isValid()) {
            const QString detail =
                layer->error().message(QgsErrorMessage::Text);
            delete layer;
            return "memory provider failed for '" + uri.toStdString()
                + "': " + detail.toStdString();
        }
        pwb::qgis::LayerBinding binding{layer_id.toStdString(), "", "",
                                        "vector"};
        pwb::qgis::layer_adapter::apply(layer, binding);
        const QString collection =
            QString::fromStdString(pwb::domain::Json{
                {"type", "FeatureCollection"}, {"features", features}}
                                       .dump());
        QgsFeatureList parsed = QgsJsonUtils::stringToFeatureList(
            collection, layer->fields(), nullptr);
        if (parsed.empty()) {
            delete layer;
            return "geojson features parse to nothing";
        }
        layer->dataProvider()->addFeatures(parsed);
        layer->updateExtents();
        context_.session().map().project()->addMapLayer(layer);
        layer->triggerRepaint();

        // Factor outputs are RAW-protected (workspace ROLE_RAW_PROTECTED):
        // registered with their science role, never edit-granted.
        pwb::application::DomainLayerFacts facts;
        facts.layer_id = layer_id.toStdString();
        facts.role = role;
        facts.role_label = name.toStdString();
        facts.artifact_maturity = "raw";
        facts.write_granted = false;
        facts_[facts.layer_id] = facts;
        if (out_layer != nullptr) *out_layer = layer;
        return "";
    };

    QgsVectorLayer* facies_layer = nullptr;
    std::string add_error = add_product_layer(
        contour_id, QString::fromStdString(factor_name) + tr(" 等值线"),
        contour_uri, outcome.contour_features, "factor_contour", nullptr);
    if (add_error.empty()) {
        add_error = add_product_layer(
            facies_id, QString::fromStdString(factor_name) + tr(" 相带"),
            facies_uri, outcome.polygon_features, "factor_classification",
            &facies_layer);
    }
    if (!add_error.empty()) {
        return QString::fromStdString(add_error);
    }

    if (facies_layer != nullptr && !facies_layer->extent().isNull()) {
        canvas_->setExtent(facies_layer->extent());
    }
    context_.session().map().refreshCanvases();
    refreshActionStates();
    statusBar()->showMessage(
        tr("地质因子图已生成：%1（%2 条等值线 / %3 个相带多边形）")
            .arg(QString::fromStdString(factor_name))
            .arg(outcome.contour_features.size())
            .arg(outcome.polygon_features.size()),
        10000);
    return QString();
}

QString MainWindow::runGeologicalFactorMap(
    const QString& layer_id, const std::string& factor_name,
    const std::string& method, int grid_n,
    const std::string& target_horizon) {
    // Sync path (tests / self-check): collect → compute → apply inline.
    pwb::domain::Json records = pwb::domain::Json::array();
    std::string crs;
    const QString collect_error =
        collectFactorMapInputs(layer_id, factor_name, &records, &crs);
    if (!collect_error.isEmpty()) return collect_error;

    pwb::application::MapPipelineRequest request;
    request.factor_name = factor_name;
    request.target_horizon = target_horizon;
    request.crs = crs;
    request.method = method;
    request.grid_n = grid_n;
    const pwb::application::MapPipelineOutcome outcome =
        pwb::application::run_map_pipeline(records, request);
    return applyFactorMapOutcome(outcome, factor_name, crs);
}

#ifdef PWB_WITH_CONV_30
void MainWindow::submitFactorMapJob(
    const QString& layer_id, const std::string& factor_name,
    const std::string& method, int grid_n,
    const std::string& target_horizon) {
    // CONV-30 — the kernel compute runs as a job (Qt-free, plain data in /
    // plain data out); collection stays on the GUI thread (QgsVectorLayer
    // iteration is not thread-safe) and so does layer application.
    pwb::domain::Json records = pwb::domain::Json::array();
    std::string crs;
    const QString collect_error =
        collectFactorMapInputs(layer_id, factor_name, &records, &crs);
    if (!collect_error.isEmpty()) {
        QMessageBox::warning(this, tr("地质因子图"), collect_error);
        return;
    }
    pwb::application::MapPipelineRequest request;
    request.factor_name = factor_name;
    request.target_horizon = target_horizon;
    request.crs = crs;
    request.method = method;
    request.grid_n = grid_n;

    auto* progress = new QProgressDialog(tr("地质因子图计算中…"), tr("取消"),
                                         0, 0, this);  // busy indicator
    progress->setWindowModality(Qt::NonModal);
    progress->setMinimumDuration(0);
    progress->setValue(1);

    auto& owner = job_center_->make_owner(this);
    QObject::connect(progress, &QProgressDialog::canceled, &owner,
                     &pwb::job::qtbridge::JobOwner::cancel);
    pwb::job::JobSpec spec;
    spec.kind = "background.compute";
    spec.title = "地质因子图";
    spec.run = [records, request](pwb::job::JobContext& ctx) -> std::any {
        // Cooperative cancel at the pipeline's own granularity: the kernel
        // is a blocking call, so the safe point is before it starts and
        // the sleep window around it.
        ctx.check_cancelled();
        return pwb::application::run_map_pipeline(records, request);
    };
    owner.start(
        job_center_->scheduler(), std::move(spec),
        [this, progress, factor_name,
         crs](const pwb::job::qtbridge::JobOutcome& job_outcome) {
            progress->deleteLater();
            if (job_outcome.state == pwb::job::JobState::cancelled) {
                statusBar()->showMessage(tr("地质因子图已取消。"), 8000);
                return;
            }
            const auto* outcome =
                std::any_cast<pwb::application::MapPipelineOutcome>(
                    &job_outcome.result);
            if (outcome == nullptr) {
                QMessageBox::warning(this, tr("地质因子图"), tr("未知结果"));
                return;
            }
            const QString apply_error =
                applyFactorMapOutcome(*outcome, factor_name, crs);
            if (!apply_error.isEmpty()) {
                QMessageBox::warning(this, tr("地质因子图"),
                                     tr("地质编图失败：%1").arg(apply_error));
            }
        });
}
#endif

void MainWindow::geologicalFactorMapDialog() {
    QDialog dialog(this);
    dialog.setWindowTitle(tr("地质因子图"));
    auto* wells = new QComboBox(&dialog);
    wells->addItem(tr("内置示例井点（8 井 · 孔隙度）"),
                   QStringLiteral("builtin.sample_wells"));
    for (const std::string& id : context_.session().map().layerIdsTopFirst()) {
        QgsVectorLayer* layer = context_.session().map().vectorLayerById(id);
        if (layer == nullptr
            || layer->geometryType() != Qgis::GeometryType::Point) {
            continue;
        }
        wells->addItem(layer->name(), QString::fromStdString(id));
    }
    auto* factor = new QComboBox(&dialog);
    for (const char* name :
         {"砂岩厚度", "地层厚度", "孔隙度", "渗透率", "TOC", "古水深", "砂地比"}) {
        factor->addItem(QString::fromUtf8(name));
    }
    factor->setCurrentIndex(2);   // 孔隙度 (locale-independent default)
    auto* horizon = new QComboBox(&dialog);
    for (const char* h : {"T1", "T2", "T3", "E1s", "E2s", "E3s", "K1q"}) {
        horizon->addItem(QString::fromUtf8(h));
    }
    auto* method = new QComboBox(&dialog);
    method->addItem(tr("反距离加权 (IDW)"), QStringLiteral("idw"));
    // The C++ kernel is the numpy grid-OLS Ordinary Kriging fallback; the
    // geoviz WLS engine is a different estimator and is not ported (M6).
    method->addItem(tr("克里金插值 (numpy 回退估算)"),
                    QStringLiteral("kriging"));
    auto* grid_n = new QSpinBox(&dialog);
    grid_n->setRange(20, 300);
    grid_n->setSingleStep(10);
    grid_n->setValue(50);

    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    auto* form = new QFormLayout;
    form->addRow(tr("井点图层"), wells);
    form->addRow(tr("因素"), factor);
    form->addRow(tr("目的层段"), horizon);
    form->addRow(tr("插值方法"), method);
    form->addRow(tr("网格数"), grid_n);
    auto* layout = new QVBoxLayout(&dialog);
    layout->addLayout(form);
    layout->addWidget(buttons);
    if (dialog.exec() != QDialog::Accepted) return;

#ifdef PWB_WITH_CONV_30
    // CONV-30 — compute on the job runtime (non-modal + cancellable);
    // collection stays on this (GUI) thread, layer application is applied
    // from the completion delivery.
    submitFactorMapJob(wells->currentData().toString(),
                       factor->currentText().toStdString(),
                       method->currentData().toString().toStdString(),
                       grid_n->value(),
                       horizon->currentText().toStdString());
#else
    const QString result = runGeologicalFactorMap(
        wells->currentData().toString(), factor->currentText().toStdString(),
        method->currentData().toString().toStdString(), grid_n->value(),
        horizon->currentText().toStdString());
    if (!result.isEmpty()) {
        QMessageBox::warning(this, tr("地质因子图"),
                             tr("地质编图失败：%1").arg(result));
    }
#endif
}
#endif

// ------------------------------------------------------------ reactions ----

void MainWindow::onCanvasMapToolChanged() {
    const QgsMapTool* tool = canvas_->mapTool();
    std::string tool_id = "unknown";
    if (tool == pan_tool_) tool_id = "pan";
    else if (tool == zoom_in_tool_) tool_id = "zoom_in";
    else if (tool == zoom_out_tool_) tool_id = "zoom_out";
    else if (tool == vertex_tool_) tool_id = "vertex";
#ifdef PWB_WITH_CONV_27
    else if (edit_tools_ != nullptr
             && pwb::ui::EditToolController::handles_tool(
                 edit_tools_->tool_id_of(tool))) {
        tool_id = edit_tools_->tool_id_of(tool);
    }
#endif
    context_.session().set_current_tool(tool_id);
    refreshActionStates();
}

void MainWindow::onActiveLayerChanged() {
    const QModelIndex current = tree_->currentIndex();
    if (!current.isValid()) return;
    // Map the tree row back to a domain layer id via the join key.
    const auto layers = context_.session().map().layerIdsTopFirst();
    const int row = current.row();
    if (row < 0 || static_cast<size_t>(row) >= layers.size()) return;
    const std::string layer_id = layers[static_cast<size_t>(row)];
    const auto it = facts_.find(layer_id);
    if (it == facts_.end()) return;
    context_.session().set_active_layer(it->second);
    refreshActionStates();
}

// ---------------------------------------------------------------- close ----

bool MainWindow::anyDirtyEditSession() const {
    const auto active = context_.session().active_layer();
    return active.has_value() && context_.session().edit().editing(active->layer_id)
        && context_.session().edit().dirty(active->layer_id);
}

void MainWindow::closeEvent(QCloseEvent* event) {
    if (anyDirtyEditSession()) {
        const int choice = dirty_close_responder_();
        if (choice == QMessageBox::Cancel) {
            event->ignore();
            return;
        }
        if (choice == QMessageBox::Save) {
            const auto active = context_.session().active_layer();
            const std::filesystem::path staged_dir =
                std::filesystem::temp_directory_path() / "pwb-platform" / "staged";
            std::string error;
            context_.session().stage_commit(active->layer_id, staged_dir, &error);
            if (!error.empty()) {
                // Failed save must not destroy the edits: cancel the close.
                // (Non-modal: a blocking dialog here is untestable offscreen;
                // the open window itself carries the message.)
                statusBar()->showMessage(
                    tr("保存失败，关闭已取消: %1").arg(QString::fromStdString(error)),
                    10000);
                event->ignore();
                return;
            }
        } else {
            const auto active = context_.session().active_layer();
            if (active.has_value()) context_.session().edit().roll_back(active->layer_id);
        }
    }
#ifdef PWB_WITH_CONV_27
    // UI layout only; business state lives in the store/catalog round.
    // A pending reset must NOT be overwritten by this close — and the
    // CONV-PS store below must skip the write for the same reason (its
    // restore runs after layout_store_'s at startup, so it would
    // otherwise resurrect the pre-reset layout).
    const bool layout_reset_pending = layout_reset_pending_;
    if (layout_store_ != nullptr && !layout_reset_pending) {
        layout_store_->save(*this);
    }
#else
    const bool layout_reset_pending = false;
#endif
    // Persist the window layout on the confirmed close path only: the
    // window is still visible here, so save_window_layout accepts it
    // (a cancelled close must not rewrite the store).
    if (services_settings_ != nullptr && !layout_reset_pending) {
        pwb::platform_services::save_window_layout(*services_settings_, *this);
    }
// BEGIN VIZ-B
#ifdef PWB_WITH_VIZ_B
    if (viz_b_dock_ != nullptr) {
        // After the cancel gate: a cancelled close must not have flushed.
        viz_b_dock_->handle_project_closed();  // flush + drop late results
    }
#endif
// END VIZ-B
#ifdef PWB_WITH_CONV_30
    // CONV-30 — window close while a task runs: bounded cancel+wait for
    // every owned job (AppShell.shutdown_workers parity); a job that
    // refuses to cancel detaches to the process-lifetime keeper and keeps
    // running without the window (its GUI deliveries are dropped).
    if (job_center_ != nullptr) job_center_->shutdown_workers(400);
#endif
    // Contract teardown order: session (edit -> canvas detach -> layers ->
    // project) before widget children die with the window.
    context_.session().close();
    QMainWindow::closeEvent(event);
}

// ------------------------------------------- CONV-PS platform services ----

void MainWindow::buildPlatformMenus() {
    // ---- 设置 menu: theme, density, diagnostics (production entry points,
    // mirroring the workstation app-bar View menu of the Python shell).
    QMenu* settings_menu = menuBar()->addMenu(tr("设置(&S)"));
    QMenu* theme_menu = settings_menu->addMenu(tr("主题"));

    const struct {
        const char* value;
        const char* label;
    } themes[] = {
        {"light", "浅色"},
        {"dark", "深色"},
        {"high_contrast", "高对比度"},
    };
    auto* theme_group = new QActionGroup(this);
    for (int i = 0; i < 3; ++i) {
        QAction* action =
            theme_menu->addAction(tr(themes[i].label));
        action->setCheckable(true);
        action->setData(QString::fromLatin1(themes[i].value));
        theme_group->addAction(action);
        theme_actions_[i] = action;
        connect(action, &QAction::triggered, this, [this, action]() {
            theme_service_->set_theme(
                pwb::platform_services::theme_from_string(
                    action->data().toString().toStdString()));
        });
    }
    density_action_ = settings_menu->addAction(tr("紧凑密度"));
    density_action_->setCheckable(true);
    connect(density_action_, &QAction::triggered, this, [this]() {
        theme_service_->set_density(
            density_action_->isChecked()
                ? pwb::platform_services::Density::Compact
                : pwb::platform_services::Density::Comfortable);
    });
    syncThemeMenuChecks();
    refreshRecentProjects();

    settings_menu->addSeparator();
    settings_menu->addAction(tr("诊断信息…"), this,
                             &MainWindow::showDiagnosticsDialog);

    // ---- 帮助 menu (app.py _on_about parity + the native probe report).
    QMenu* help_menu = menuBar()->addMenu(tr("帮助(&H)"));
    help_menu->addAction(tr("关于…"), this, &MainWindow::showAboutDialog);
    help_menu->addAction(tr("诊断信息…"), this,
                         &MainWindow::showDiagnosticsDialog);
}

void MainWindow::syncThemeMenuChecks() {
    if (theme_service_ == nullptr) return;
    const QString current = QString::fromStdString(
        pwb::platform_services::to_string(theme_service_->theme()));
    for (QAction* action : theme_actions_) {
        if (action != nullptr) {
            action->setChecked(action->data().toString() == current);
        }
    }
    if (density_action_ != nullptr) {
        density_action_->setChecked(theme_service_->density()
                                    == pwb::platform_services::Density::Compact);
    }
}

void MainWindow::refreshRecentProjects() {
    if (recent_projects_menu_ == nullptr) return;
    recent_projects_menu_->clear();
    if (services_settings_ == nullptr) return;
    const QStringList projects =
        pwb::platform_services::load_recent_projects(*services_settings_);
    if (projects.isEmpty()) {
        QAction* empty = recent_projects_menu_->addAction(tr("(暂无最近工程)"));
        empty->setEnabled(false);
        return;
    }
    for (const QString& project : projects) {
        QAction* action = recent_projects_menu_->addAction(project);
        connect(action, &QAction::triggered, this,
                [this, project]() { openRecentProject(project); });
    }
    recent_projects_menu_->addSeparator();
    recent_projects_menu_->addAction(
        tr("清除最近工程"), this, [this]() {
            pwb::platform_services::clear_recent_projects(*services_settings_);
            refreshRecentProjects();
        });
}

void MainWindow::openRecentProject(const QString& project_file) {
#ifdef PWB_WITH_DATA_INTEGRATION
    // openProject's success path already heads the MRU and refreshes the
    // menu — here only the failure needs surfacing.
    const QString error = openProject(project_file);
    if (!error.isEmpty()) {
        QMessageBox::warning(this, tr("打开工程失败"), error);
    }
#else
    // Honest degraded state: this build has no data stack, so projects
    // cannot be opened from the MRU (same contract as openProjectDialog).
    Q_UNUSED(project_file);
    QMessageBox::information(this, tr("最近工程"),
                             tr("当前构建未包含数据栈，无法打开工程。"));
#endif
}

void MainWindow::showAboutDialog() {
    // app.py _on_about text at parity, plus the native identity line.
    QMessageBox::about(
        this, tr("关于"),
        tr("智能岩相古地理重建系统\n"
           "Paleogeography Workbench\n\n"
           "数据管理 · 沉积相预测 · 古地理编图 · 三维地质建模\n\n")
            + QString::fromStdString(pwb::platform_services::version_line()));
}

void MainWindow::showDiagnosticsDialog() {
    const QString report = QString::fromStdString(
        pwb::platform_services::environment_report_text());
    QDialog dialog(this);
    dialog.setWindowTitle(tr("诊断信息"));
    dialog.resize(720, 520);
    auto* layout = new QVBoxLayout(&dialog);
    auto* view = new QTextBrowser(&dialog);
    view->setPlainText(report);
    view->setReadOnly(true);
    layout->addWidget(view);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Save | QDialogButtonBox::Close, &dialog);
    auto* copy_button =
        buttons->addButton(tr("复制"), QDialogButtonBox::ActionRole);
    QObject::connect(copy_button, &QPushButton::clicked, &dialog,
                     [view]() { QApplication::clipboard()->setText(view->toPlainText()); });
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    connect(buttons->button(QDialogButtonBox::Save), &QPushButton::clicked,
            &dialog, [this, view, &dialog]() {
                const QString path = QFileDialog::getSaveFileName(
                    &dialog, tr("保存诊断报告"), QStringLiteral("pwb-diagnostics.txt"));
                if (path.isEmpty()) return;
                QFile file(path);
                if (file.open(QIODevice::WriteOnly | QIODevice::Text)) {
                    file.write(view->toPlainText().toUtf8());
                }
            });
    layout->addWidget(buttons);
    dialog.exec();
}

// ------------------------------------------------------------ fixtures ----

QString MainWindow::loadFixtures(const QString& vector_uri,
                                 const QString& raster_uri) {
    const pwb::qgis::LayerBinding vector_binding{
        "fixture.facies_boundary", "asset-fixture-1", "version-1", "vector"};
    std::string error;
    pwb::qgis::MapSession& map = context_.session().map();
    if (map.addVectorLayer(vector_uri.toStdString(), tr("相带边界").toStdString(),
                           vector_binding, &error) == nullptr) {
        return QString::fromStdString(error);
    }
    if (!raster_uri.isEmpty()) {
        const pwb::qgis::LayerBinding raster_binding{
            "fixture.base_raster", "asset-fixture-2", "version-1", "raster"};
        if (map.addRasterLayer(raster_uri.toStdString(),
                               tr("基础底图").toStdString(), raster_binding,
                               &error) == nullptr) {
            return QString::fromStdString(error);
        }
    }
    pwb::application::DomainLayerFacts facts;
    facts.layer_id = "fixture.facies_boundary";
    facts.role = "facies_boundary";
    facts.role_label = QStringLiteral("相带边界").toStdString();
    facts.write_granted = true;
    facts.artifact_maturity = "draft";
    facts_[facts.layer_id] = facts;
    context_.session().set_active_layer(facts);
    map.setDestinationCrs("EPSG:4326", &error);
    if (!error.empty()) return QString::fromStdString(error);
    map.zoomToFullExtent(canvas_);
    refreshActionStates();
    return QString();
}

#ifdef PWB_WITH_WELL_LOG
QString MainWindow::loadLasIntoDock(const QString& las_path) {
    // The host widget carries no Q_OBJECT: reach it through its dock
    // (object-named) instead of findChild on the type.
    QDockWidget* dock = findChild<QDockWidget*>("well-log-dock");
    auto* host = static_cast<pwb::viz::WellLogHostWidget*>(
        dock != nullptr ? dock->widget() : nullptr);
    if (host == nullptr) return QStringLiteral("unavailable");
    QString error;
    if (!host->load_las(las_path, &error)) {
        return error.isEmpty() ? QStringLiteral("load failed") : error;
    }
    return QString();
}
#endif

QString MainWindow::commitActiveLayer(const std::filesystem::path& staged_dir) {
    const auto active = context_.session().active_layer();
    if (!active.has_value()) return QStringLiteral("no active layer");
    std::string error;
    context_.session().stage_commit(active->layer_id, staged_dir, &error);
    return QString::fromStdString(error);
}

#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
std::vector<std::string> MainWindow::volumeVersionIds() const {
    std::vector<std::string> ids;
    if (context_.projectStore() == nullptr) return ids;
    auto snapshot = context_.projectStore()->snapshot();
    if (!snapshot.is_ok()) return ids;
    for (const auto& version : snapshot.value().catalog_versions) {
        if (version.format == "PWBVOL1" && !version.trashed) {
            ids.push_back(version.id.str());
        }
    }
    return ids;
}

QString MainWindow::openVolumeVersion(const std::string& version_id) {
    if (context_.projectStore() == nullptr) return tr("未打开工程");
    auto snapshot = context_.projectStore()->snapshot();
    if (!snapshot.is_ok()) {
        return QString::fromStdString(snapshot.error().message);
    }
    const std::filesystem::path project_dir =
        context_.projectStore()->project_file().parent_path();
    for (const auto& version : snapshot.value().catalog_versions) {
        if (version.id.str() != version_id || version.format != "PWBVOL1") {
            continue;
        }
        const std::filesystem::path payload_path =
            project_dir / version.path;
#if defined(PWB_WITH_SEISMIC_SERVICE)
        // Native tiled service: metadata-only inspect, samples stream in
        // through the tile cache — no full-volume copy.
        if (seismic_volume_service_ != nullptr) {
            std::string open_error;
            auto opened = seismic_volume_service_->open_pwbvol(
                payload_path, &open_error);
            if (opened.volume == nullptr) {
                return QString::fromStdString(open_error);
            }
            slice_widget_->set_volume(
                opened.volume, pwb::seismic_viewer::VolumeIdentity{version_id, 0},
                ++slice_revision_);
            seismic_dock_->show();
            seismic_dock_->raise();
            statusBar()->showMessage(
                opened.descriptor.bin_grid.has_value()
                    ? tr("体版本已载入：%1（空间已标定；CRS 未绑定）")
                          .arg(QString::fromStdString(version_id))
                    : tr("体版本已载入：%1（无 bin-grid 标定）")
                          .arg(QString::fromStdString(version_id)),
                8000);
            return QString();
        }
#endif
        pwb::application::VolumePayload payload;
        const std::string read_error =
            pwb::application::read_volume_payload(payload_path, &payload);
        if (!read_error.empty()) {
            return QString::fromStdString(read_error);
        }
        pwb::viz::VolumeGeometryV1 geometry;
        geometry.shape = {static_cast<std::int64_t>(payload.header.ni),
                          static_cast<std::int64_t>(payload.header.nc),
                          static_cast<std::int64_t>(payload.header.ns)};
        geometry.strides = {0, 0, 0};
        geometry.origin = {payload.header.inline_start,
                           payload.header.crossline_start,
                           payload.header.sample_start};
        geometry.step = {payload.header.inline_step,
                         payload.header.crossline_step,
                         payload.header.sample_step};
        geometry.unit = payload.header.sample_unit;
        auto volume = std::shared_ptr<pwb::viz::ISeismicVolume>(
            pwb::viz::make_owning_volume(geometry,
                                         std::move(payload.samples))
                .release());
        slice_widget_->set_volume(
            volume, pwb::seismic_viewer::VolumeIdentity{version_id, 0},
            ++slice_revision_);
        seismic_dock_->show();
        seismic_dock_->raise();
        statusBar()->showMessage(
            tr("体版本已载入：%1").arg(QString::fromStdString(version_id)),
            8000);
        return QString();
    }
    return tr("catalog 中未找到该体版本：%1").arg(
        QString::fromStdString(version_id));
}
#endif

#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
std::string MainWindow::runAttribute(
    const std::string& algorithm_id,
    const std::map<std::string, std::string>& params,
    const std::string& input_version_id, std::string* error) {
    return context_.attributeRunner().submit(context_.projectStore(), algorithm_id, params,
                                     input_version_id, error);
}

pwb::application::AlgorithmRunner::Outcome MainWindow::attributeOutcome(
    const std::string& request_id) {
    return context_.attributeRunner().outcome(request_id);
}

void MainWindow::runAttributeDialog() {
    if (context_.projectStore() == nullptr) {
        QMessageBox::information(this, tr("计算属性"), tr("请先打开工程。"));
        return;
    }
    const std::vector<std::string> versions = volumeVersionIds();
    if (versions.empty()) {
        QMessageBox::information(
            this, tr("计算属性"),
            tr("当前工程没有 PWBVOL1 体版本（先导入/计算一个体）。"));
        return;
    }

    QDialog dialog(this);
    dialog.setWindowTitle(tr("计算地震属性"));
    auto* algorithm = new QComboBox(&dialog);
    for (const auto& info : context_.attributeRunner().algorithms()) {
        algorithm->addItem(QString::fromStdString(info.display_name),
                           QString::fromStdString(info.algorithm_id));
    }
    auto* input = new QComboBox(&dialog);
    for (const std::string& id : versions) {
        input->addItem(QString::fromStdString(id),
                       QString::fromStdString(id));
    }
    auto* window = new QSpinBox(&dialog);
    window->setRange(0, 4096);
    window->setValue(21);
    auto* sample_interval = new QDoubleSpinBox(&dialog);
    sample_interval->setDecimals(6);
    sample_interval->setMinimum(0.000001);
    sample_interval->setValue(0.002);
    sample_interval->setSuffix(tr(" s"));
    auto* spacing = new QDoubleSpinBox(&dialog);
    spacing->setDecimals(3);
    spacing->setMinimum(0.001);
    spacing->setValue(1.0);
    spacing->setSuffix(tr(" m"));
    auto* curvature_window = new QSpinBox(&dialog);
    curvature_window->setRange(0, 4096);
    curvature_window->setValue(3);  // production KERNELS default
    curvature_window->setPrefix(tr("半窗 "));

    auto* form = new QFormLayout;
    form->addRow(tr("算法"), algorithm);
    form->addRow(tr("输入体版本"), input);
    form->addRow(tr("窗口（RMS）"), window);
    form->addRow(tr("采样间隔（瞬时频率 / 倾角 dt / 甜度）"),
                 sample_interval);
    form->addRow(tr("道间距（倾角 dx）"), spacing);
    form->addRow(tr("平滑半窗（曲率）"), curvature_window);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    auto* layout = new QVBoxLayout(&dialog);
    layout->addLayout(form);
    layout->addWidget(buttons);
    if (dialog.exec() != QDialog::Accepted) return;

    const std::string algorithm_id =
        algorithm->currentData().toString().toStdString();
    const std::string input_version =
        input->currentData().toString().toStdString();
    std::map<std::string, std::string> params;
    if (algorithm_id == "seismic.rms_amplitude") {
        params["window"] = std::to_string(window->value());
    } else if (algorithm_id == "seismic.instantaneous_frequency"
               || algorithm_id == "seismic.sweetness") {
        params["sample_interval"] = std::to_string(sample_interval->value());
    } else if (algorithm_id == "seismic.dip_il"
               || algorithm_id == "seismic.dip_xl"
               || algorithm_id == "seismic.dip_azimuth") {
        params["dt"] = std::to_string(sample_interval->value());
        params["dx_il"] = std::to_string(spacing->value());
        params["dx_xl"] = std::to_string(spacing->value());
    } else if (algorithm_id == "seismic.curvature_mean") {
        params["win_il"] = std::to_string(curvature_window->value());
        params["win_xl"] = std::to_string(curvature_window->value());
        params["win_t"] = std::to_string(curvature_window->value());
    }

    std::string error;
    const std::string request_id =
        runAttribute(algorithm_id, params, input_version, &error);
    if (request_id.empty()) {
        QMessageBox::warning(this, tr("计算属性"),
                             QString::fromStdString(error));
        return;
    }

#ifdef PWB_WITH_CONV_30
    // CONV-30 — non-modal supervision on the job runtime: the compute
    // itself stays on the TaskRuntime lane (publication semantics), while
    // progress/cancel/close-quit lifecycle moves to the scheduler. Cancel
    // propagates cooperatively into the run.
    superviseAttributeRun(request_id);
    return;
#else
    // M1: modal progress for the (small) fixture-scale volumes; large
    // volumes get a non-modal progress surface later.
    QTimer timer(&dialog);
    timer.setInterval(50);
    QEventLoop loop;
    QObject::connect(&timer, &QTimer::timeout, &loop, [&]() {
        const std::string status = attributeOutcome(request_id).status;
        if (status == "queued" || status == "running"
            || status == "publishing") {
            return;
        }
        loop.quit();
    });
    timer.start();
    loop.exec();
    const auto outcome = attributeOutcome(request_id);
    if (outcome.status != "succeeded") {
        QMessageBox::warning(
            this, tr("计算属性"),
            tr("运行失败：%1\n%2")
                .arg(QString::fromStdString(outcome.error_code))
                .arg(QString::fromStdString(outcome.error)));
        return;
    }
#if defined(PWB_WITH_SEISMIC_VIEWER)
    const QString view_error =
        openVolumeVersion(outcome.version_id);
    if (!view_error.isEmpty()) {
        QMessageBox::warning(this, tr("计算属性"), view_error);
        return;
    }
#endif
    statusBar()->showMessage(
        tr("属性已发布：%1（运行 %2）")
            .arg(QString::fromStdString(outcome.version_id))
            .arg(QString::fromStdString(outcome.run_id)),
        10000);
#endif
}

#if defined(PWB_WITH_CONV_30) && defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
void MainWindow::superviseAttributeRun(const std::string& request_id) {
    auto* progress = new QProgressDialog(tr("计算地震属性…"), tr("取消"),
                                         0, 100, this);
    progress->setWindowModality(Qt::NonModal);
    progress->setMinimumDuration(0);
    progress->setValue(1);
    auto& owner = job_center_->make_owner(this);
    // Dialog cancel reaches the run from BOTH paths: the job token (when
    // the supervision job is already running) and the runner directly
    // (when the job is still QUEUED behind another lane and a queued
    // cancel would drop it before it ever forwarded the cancel).
    QObject::connect(
        progress, &QProgressDialog::canceled, this,
        [this, request_id] {
            context_.attributeRunner().cancel(request_id);
        });
    QObject::connect(progress, &QProgressDialog::canceled, &owner,
                     &pwb::job::qtbridge::JobOwner::cancel);
    const auto alive = job_center_->alive();
    pwb::job::JobSpec spec;
    spec.kind = "seismic.attribute";
    spec.title = "地震属性计算";
    spec.run = [this, request_id, alive](pwb::job::JobContext& ctx)
        -> std::any {
        bool cancel_sent = false;
        for (;;) {
            // Teardown escape: alive clears before the runner member dies,
            // so this loop can exit without touching `this` again.
            if (!alive->load()) return {};
            // Cooperative cancel propagation: the supervision token flips
            // the underlying run's TaskHandle; the run then unwinds its
            // publication exactly like an explicit cancel.
            if (ctx.token().is_cancelled() && !cancel_sent) {
                cancel_sent = true;
                context_.attributeRunner().cancel(request_id);
            }
            const auto outcome = attributeOutcome(request_id);
            if (outcome.status == "queued") {
                ctx.report_progress(0.05, std::nullopt, "排队中");
            } else if (outcome.status == "running") {
                ctx.report_progress(0.5, std::nullopt, "计算中");
            } else if (outcome.status == "publishing") {
                ctx.report_progress(0.95, std::nullopt, "发布中");
            } else {
                break;  // terminal
            }
            ctx.sleep_interruptible(0.05);
        }
        return attributeOutcome(request_id);
    };
    owner.start(
        job_center_->scheduler(), std::move(spec),
        [this, progress](const pwb::job::qtbridge::JobOutcome& job_outcome) {
            progress->deleteLater();
            if (job_outcome.state == pwb::job::JobState::cancelled) {
                statusBar()->showMessage(tr("属性计算已取消。"), 8000);
                return;
            }
            const pwb::application::AlgorithmRunner::Outcome* outcome =
                std::any_cast<pwb::application::AlgorithmRunner::Outcome>(
                    &job_outcome.result);
            if (outcome == nullptr || outcome->status != "succeeded") {
                QMessageBox::warning(
                    this, tr("计算属性"),
                    tr("运行失败：%1\n%2")
                        .arg(outcome != nullptr
                                 ? QString::fromStdString(outcome->error_code)
                                 : tr("未知"))
                        .arg(outcome != nullptr
                                 ? QString::fromStdString(outcome->error)
                                 : QString()));
                return;
            }
#if defined(PWB_WITH_SEISMIC_VIEWER)
            const QString view_error =
                openVolumeVersion(outcome->version_id);
            if (!view_error.isEmpty()) {
                QMessageBox::warning(this, tr("计算属性"), view_error);
                return;
            }
#endif
            statusBar()->showMessage(
                tr("属性已发布：%1（运行 %2）")
                    .arg(QString::fromStdString(outcome->version_id))
                    .arg(QString::fromStdString(outcome->run_id)),
                10000);
        },
        [progress](double ratio, const QString& message) {
            progress->setLabelText(message);
            progress->setValue(
                std::max(1, static_cast<int>(ratio * 100.0)));
        });
}
#endif
#endif  // PWB_WITH_SEISMIC_ATTRIBUTES && PWB_WITH_DATA_INTEGRATION (attributes section)

#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_DATA_INTEGRATION)
namespace {
// ONE process-level import id sequence for every entry point (public API
// and dialog): staged file names, run ids and operation ids share the
// namespace, so two independent counters could silently reuse the same
// staged path and overwrite a published version's payload.
std::string next_segy_import_id() {
    static std::uint64_t counter = 0;
    return "segy-import-" + std::to_string(counter++);
}

// Stages the imported volume as a PWBVOL1 payload file. Pure file I/O —
// safe on any thread (#1380: the job's worker runs this half).
std::filesystem::path stage_segy_import_payload(
    const std::filesystem::path& project_dir, const QString& path,
    const std::string& import_id, pwb::seismic_io::SegyVolume volume,
    std::string* error) {
    pwb::application::VolumePayload payload;
    payload.header.ni = static_cast<std::uint32_t>(volume.ni);
    payload.header.nc = static_cast<std::uint32_t>(volume.nc);
    payload.header.ns = static_cast<std::uint32_t>(volume.ns);
    payload.header.inline_start = volume.iline_start;
    payload.header.crossline_start = volume.xline_start;
    payload.header.sample_start = 0.0;
    payload.header.inline_step = volume.iline_step;
    payload.header.crossline_step = volume.xline_step;
    payload.header.sample_step = volume.dt_ms;
    payload.header.sample_unit = volume.unit;
    payload.header.value_unit = "amplitude";
    payload.header.algorithm_id = "import.segy";
    payload.header.algorithm_version = "1.0.0";
    payload.header.build_identity = "pwb-platform";
    payload.header.request_id = import_id;
    payload.samples = std::move(volume.samples);

    const std::filesystem::path staged_dir = project_dir / ".pwb-imports";
    std::error_code ec;
    std::filesystem::create_directories(staged_dir, ec);
    const std::filesystem::path staged_path =
        staged_dir / (import_id + ".pwbvol");
    const std::string write_error =
        pwb::application::write_volume_payload(payload, staged_path);
    if (!write_error.empty()) {
        if (error != nullptr) *error = write_error;
        return {};
    }
    return staged_path;
}

// Publishes an already-staged import through B's run lifecycle (register ->
// publish -> manifest). GUI thread only since #1380: the store is now
// serialized internally, but publishing on the GUI thread keeps the
// documented lease and avoids racing window teardown from a detached job.
std::string publish_staged_segy_import(
    pwb::application::PwbDataStore& store, const QString& path,
    const std::string& import_id, const std::filesystem::path& staged_path,
    std::string* error) {
    const pwb::domain::RunId run_id{std::string("run_") + import_id};
    pwb::data::RunRegistrationV1 registration;
    registration.run_id = run_id;
    registration.operation = "import.segy";
    registration.generator = "pwb-platform";
    registration.parameters = pwb::domain::Json::object();
    registration.parameters["source_file"] = path.toStdString();
    auto registered = store.coordinator().register_run(registration);
    if (!registered.is_ok()) {
        if (error != nullptr) {
            *error = "register_run failed: " + registered.error().message;
        }
        return "";
    }
    pwb::data::PublishRequestV1 publish;
    publish.operation_id =
        pwb::domain::OperationId{std::string("pub_") + import_id};
    publish.run_id = run_id;
    publish.new_asset_name =
        "地震数据 " + std::filesystem::path(path.toStdWString())
                           .stem()
                           .string();
    publish.new_asset_type = "seismic_volume";
    publish.stage = pwb::domain::DataStage::Raw;
    pwb::data::StagedAssetV1 staged;
    staged.source_path = staged_path;
    staged.format = "PWBVOL1";
    publish.products.push_back(std::move(staged));
    publish.result_metadata = pwb::domain::Json::object();
    publish.result_metadata["payload_format"] = "PWBVOL1";
    publish.result_metadata["source_format"] = "SEG-Y";
    auto published =
        store.coordinator().publish_run_result(publish, store.document());
    if (!published.is_ok()) {
        if (error != nullptr) {
            *error = "publish failed: " + published.error().message;
        }
        return "";
    }
    (void)store.export_manifest();
    return published.value().new_version_id.str();
}
}  // namespace

std::string MainWindow::importSegy(const QString& path, std::string* error) {
    // Sync path (self-check / tests): no cancellation, no progress.
    return importSegyProgressed(
        path, error, [] { return false; }, [](double, const QString&) {});
}

std::string MainWindow::importSegy(const QString& path, std::string* error,
                                   pwb::seismic_io::CancelFlag cancel) {
    // Cancellable sync path (threaded import): the flag reaches the
    // intra-read safe points through importSegyProgressed's bridge.
    return importSegyProgressed(
        path, error, [cancel] { return cancel.cancelled(); },
        [](double, const QString&) {});
}

std::string MainWindow::importSegyProgressed(
    const QString& path, std::string* error,
    const std::function<bool()>& cancelled,
    const std::function<void(double, const QString&)>& progress) {
    if (context_.projectStore() == nullptr) {
        if (error != nullptr) *error = "未打开工程（SEG-Y 导入需要工程目录）";
        return "";
    }
    const std::string import_id = next_segy_import_id();

    progress(0.05, tr("读取 SEG-Y…"));
    if (cancelled()) return "";
    // CONV-30 + CONV-SEISMIC: the reader honours a CancelFlag between
    // traces; bridge the caller's poll-based cancellation into it so both
    // paths cancel inside the read, not just at phase boundaries.
    pwb::seismic_io::CancelFlag flag;
    std::atomic<bool> read_done{false};
    std::thread bridge([&flag, &read_done, &cancelled] {
        while (!read_done.load(std::memory_order_relaxed)) {
            if (cancelled()) {
                flag.cancel();
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
    });
    auto volume = pwb::seismic_io::read_segy(
        std::filesystem::path(path.toStdWString()), error, flag);
    read_done.store(true, std::memory_order_relaxed);
    bridge.join();
    if (!volume.has_value()) return "";
    if (cancelled()) return "";
    progress(0.45, tr("写入 PWBVOL1 载荷…"));
    const std::filesystem::path staged_path = stage_segy_import_payload(
        context_.projectStore()->project_file().parent_path(), path,
        import_id, std::move(volume.value()), error);
    if (staged_path.empty()) return "";
    progress(0.7, tr("发布到工程目录…"));
    const std::string version = publish_staged_segy_import(
        *context_.projectStore(), path, import_id, staged_path, error);
    if (!version.empty()) progress(0.95, tr("完成"));
    return version;
}
#endif

#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_DATA_INTEGRATION)

void MainWindow::importSegyDialog() {
    const QString path = QFileDialog::getOpenFileName(
        this, tr("导入 SEG-Y"), QString(),
        tr("SEG-Y 数据 (*.sgy *.segy);;所有文件 (*)"));
    if (path.isEmpty()) return;
    if (context_.projectStore() == nullptr) {
        QMessageBox::warning(this, tr("导入 SEG-Y"),
                             tr("未打开工程（SEG-Y 导入需要工程目录）。"));
        return;
    }

    // Declared ahead of the branch macros: the CONV-30 job path returns
    // early (it opens the viewer in its finished callback), while the
    // service/sync branches assign it here — the trailing viewer/status
    // block must compile in every configuration.
    std::string version_id;
#ifdef PWB_WITH_CONV_30
    // CONV-30 — the import runs as a job: non-modal progress, cooperative
    // cancel, close/quit safe.
    submitSegyJob(path);
    return;
#elif defined(PWB_WITH_SEISMIC_SERVICE)
    // Threaded import: the heavy SEG-Y read runs on a worker thread with a
    // cooperative cancel flag; staging + catalog publication stay on the
    // GUI thread.
    auto cancel = pwb::seismic_io::CancelFlag();
    QProgressDialog progress(tr("正在读取 SEG-Y…"), tr("取消"), 0, 0, this);
    progress.setWindowTitle(tr("导入 SEG-Y"));
    progress.setWindowModality(Qt::WindowModal);
    progress.setMinimumDuration(0);
    std::optional<pwb::seismic_io::SegyVolume> volume;
    std::string read_error;
    std::atomic<bool> done{false};
    std::thread worker([&]() {
        volume = pwb::seismic_io::read_segy(
            std::filesystem::path(path.toStdWString()), &read_error, cancel);
        done.store(true);
    });
    while (!done.load()) {
        QCoreApplication::processEvents(QEventLoop::WaitForMoreEvents, 50);
        if (progress.wasCanceled()) {
            cancel.cancel();
        }
    }
    worker.join();
    progress.reset();
    if (!volume.has_value()) {
        // Cancellation is a normal cooperative outcome, not an error: the
        // user pressed the button, so return silently.
        if (read_error != "cancelled") {
            QMessageBox::warning(this, tr("导入 SEG-Y"),
                                 QString::fromStdString(read_error));
        }
        return;
    }
    const std::string import_id = next_segy_import_id();
    std::string publish_error;
    const std::filesystem::path staged_path = stage_segy_import_payload(
        context_.projectStore()->project_file().parent_path(), path,
        import_id, std::move(volume.value()), &publish_error);
    if (!staged_path.empty()) {
        version_id = publish_staged_segy_import(
            *context_.projectStore(), path, import_id, staged_path,
            &publish_error);
    }
    if (version_id.empty()) {
        QMessageBox::warning(this, tr("导入 SEG-Y"),
                             QString::fromStdString(publish_error));
        return;
    }
#else
    std::string error;
    version_id = importSegy(path, &error);
    if (version_id.empty()) {
        QMessageBox::warning(this, tr("导入 SEG-Y"),
                             QString::fromStdString(error));
        return;
    }
#endif
#if defined(PWB_WITH_SEISMIC_VIEWER) && !defined(PWB_WITH_CONV_30)
    // BEGIN VIZ-D build fix (pre-existing at f0af9d4e): the CONV-30 job path
    // opens the viewer itself when the import job completes
    // (importSegyProgressed); this fall-through only compiles for the
    // synchronous branches above that declared `version_id` — without the
    // !CONV_30 guard the CONV_30+VIEWER+IO+DATA configuration fails to
    // compile on an undeclared identifier.
    const QString view_error = openVolumeVersion(version_id);
    if (!view_error.isEmpty()) {
        QMessageBox::warning(this, tr("导入 SEG-Y"), view_error);
        return;
    }
#endif
#ifndef PWB_WITH_CONV_30
    // Job path: the completion callback owns the status message.
    statusBar()->showMessage(
        tr("SEG-Y 已导入：%1").arg(QString::fromStdString(version_id)),
        10000);
#endif
}
// END VIZ-D build fix

#ifdef PWB_WITH_CONV_30
// Type-erased job result of one SEG-Y import (carried in JobOutcome).
struct SegyImportResult {
    std::string version_id;
    std::string error;
    // Worker half output (#1380): the staged payload file is fully written
    // off the GUI thread; only catalog publication remains for the GUI
    // finished callback.
    std::string import_id;
    std::string staged_path;
};

void MainWindow::submitSegyJob(const QString& path) {
    auto* progress = new QProgressDialog(tr("导入 SEG-Y…"), tr("取消"),
                                         0, 100, this);
    progress->setWindowModality(Qt::NonModal);
    progress->setMinimumDuration(0);
    progress->setValue(1);  // visible immediately (indeterminate phases)
    auto& owner = job_center_->make_owner(this);
    // Dialog cancel and window/app teardown both land in the job token.
    QObject::connect(progress, &QProgressDialog::canceled, &owner,
                     &pwb::job::qtbridge::JobOwner::cancel);
    const auto alive = job_center_->alive();
    // #1380: capture the store the import belongs to (never resolve it on
    // the worker after a project switch — that would publish into the wrong
    // project). The shared_ptr also keeps the store alive if the project is
    // closed while the job runs.
    const std::shared_ptr<pwb::application::PwbDataStore> store =
        context_.projectStore();
    const std::string import_id = next_segy_import_id();
    const std::filesystem::path source_path(path.toStdWString());
    const std::filesystem::path project_dir =
        store != nullptr ? store->project_file().parent_path()
                         : std::filesystem::path{};
    pwb::job::JobSpec spec;
    spec.kind = "background.io";
    spec.title = "SEG-Y 导入";
    // collect(GUI) happened above; compute(worker) is read + stage only —
    // no MainWindow members, no store calls (#1380: catalog writes stay on
    // the GUI thread); apply(GUI) publishes in the finished callback.
    spec.run = [store, project_dir, source_path, import_id, alive, path](
                   pwb::job::JobContext& ctx) -> std::any {
        SegyImportResult result;
        result.import_id = import_id;
        if (store == nullptr) {
            result.error = "未打开工程（SEG-Y 导入需要工程目录）";
            return result;
        }
        ctx.report_progress(0.05, std::nullopt, "读取 SEG-Y…");
        pwb::seismic_io::CancelFlag flag;
        std::atomic<bool> read_done{false};
        const auto cancelled = [&ctx, alive] {
            return ctx.token().is_cancelled() || !alive->load();
        };
        std::thread bridge([&flag, &read_done, &cancelled] {
            while (!read_done.load(std::memory_order_relaxed)) {
                if (cancelled()) {
                    flag.cancel();
                    break;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(5));
            }
        });
        auto volume = pwb::seismic_io::read_segy(source_path, &result.error,
                                                 flag);
        read_done.store(true, std::memory_order_relaxed);
        bridge.join();
        if (!volume.has_value() || cancelled()) return result;
        ctx.report_progress(0.45, std::nullopt, "写入 PWBVOL1 载荷…");
        const std::filesystem::path staged = stage_segy_import_payload(
            project_dir, path, import_id, std::move(volume.value()),
            &result.error);
        if (staged.empty()) return result;
        result.staged_path = staged.generic_string();
        return result;
    };
    owner.start(
        job_center_->scheduler(), std::move(spec),
        [this, progress, store, path](
            const pwb::job::qtbridge::JobOutcome& outcome) {
            progress->deleteLater();
            if (outcome.state == pwb::job::JobState::cancelled) {
                // Partial artifacts stay on disk (crash-safe contract).
                statusBar()->showMessage(tr("SEG-Y 导入已取消。"), 8000);
                return;
            }
            const auto* result =
                std::any_cast<SegyImportResult>(&outcome.result);
            if (result == nullptr || result->staged_path.empty()) {
                const std::string detail =
                    result != nullptr && !result->error.empty()
                        ? result->error
                        : outcome.error;
                QMessageBox::warning(
                    this, tr("导入 SEG-Y"),
                    QString::fromStdString(
                        detail.empty() ? std::string("unknown failure")
                                       : detail));
                return;
            }
            // apply(GUI): catalog publication on the GUI thread, into the
            // project the import was submitted for.
            std::string publish_error;
            std::string version_id;
            if (store != nullptr) {
                version_id = publish_staged_segy_import(
                    *store, path, result->import_id,
                    std::filesystem::path(result->staged_path),
                    &publish_error);
            } else {
                publish_error = "工程已关闭，无法发布导入结果";
            }
            if (version_id.empty()) {
                QMessageBox::warning(
                    this, tr("导入 SEG-Y"),
                    QString::fromStdString(
                        publish_error.empty()
                            ? std::string("unknown failure")
                            : publish_error));
                return;
            }
#if defined(PWB_WITH_SEISMIC_VIEWER)
            const QString view_error = openVolumeVersion(version_id);
            if (!view_error.isEmpty()) {
                QMessageBox::warning(this, tr("导入 SEG-Y"), view_error);
                return;
            }
#endif
            statusBar()->showMessage(
                tr("SEG-Y 已导入：%1")
                    .arg(QString::fromStdString(version_id)),
                10000);
        },
        [progress](double ratio, const QString& message) {
            progress->setLabelText(message);
            progress->setValue(
                std::max(1, static_cast<int>(ratio * 100.0)));
        });
}
#endif
#endif

#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
void MainWindow::openVolumeDialog() {
    if (context_.projectStore() == nullptr) {
        QMessageBox::information(this, tr("打开体版本"), tr("请先打开工程。"));
        return;
    }
    const std::vector<std::string> versions = volumeVersionIds();
    if (versions.empty()) {
        QMessageBox::information(
            this, tr("打开体版本"),
            tr("当前工程没有 PWBVOL1 体版本（导入 SEG-Y 或先计算一个属性）。"));
        return;
    }
    QDialog dialog(this);
    dialog.setWindowTitle(tr("打开体版本"));
    auto* combo = new QComboBox(&dialog);
    for (const std::string& id : versions) {
        combo->addItem(QString::fromStdString(id),
                       QString::fromStdString(id));
    }
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    auto* layout = new QVBoxLayout(&dialog);
    auto* form = new QFormLayout;
    form->addRow(tr("体版本"), combo);
    layout->addLayout(form);
    layout->addWidget(buttons);
    if (dialog.exec() != QDialog::Accepted) return;
    const QString error = openVolumeVersion(
        combo->currentData().toString().toStdString());
    if (!error.isEmpty()) {
        QMessageBox::warning(this, tr("打开体版本"), error);
    }
}
#endif

#ifdef PWB_WITH_CONV_16
void MainWindow::showFactorStatistics(
    const QString& factor_name, const pwb::mapping::GridStatistics& stats) {
    if (factor_dock_ == nullptr) return;
    factor_dock_->setStatistics(factor_name, stats);
    factor_dock_->show();
    factor_dock_->raise();
}
#endif

#ifdef PWB_WITH_CONV_27
namespace {
// Polygon-bearing output roles: factor products (CONV-01) and integrated
// interpretation count as "initial facies present" evidence for stage 1.
// Vocabulary constants come from layer_roles.hpp (single role registry).
bool facies_polygon_role(const std::string& role) {
    using namespace pwb::tool_policy::layer_role;
    return role == kFactorClassification || role == kIntegratedFacies
        || role == kInitialFaciesDraft || role == kFaciesBoundary;
}
}  // namespace

void MainWindow::install_conv27_surface() {
    // Stage dock: three-stage workflow switcher + readiness checklist.
    stage_dock_ = new pwb::ui::StageDock(this);
    addDockWidget(Qt::LeftDockWidgetArea, stage_dock_);
    connect(stage_dock_, &pwb::ui::StageDock::stage_change_requested, this,
            [this](const QString& value) {
                applyStageValue(value.toStdString());
            });

    // Constraint stage summary panel (read-side navigation).
    constraint_dock_ = new pwb::ui::ConstraintPanel(
        [this](const std::string& id) {
            const auto it = facts_.find(id);
            return it == facts_.end()
                ? std::optional<pwb::application::DomainLayerFacts>{}
                : std::optional<pwb::application::DomainLayerFacts>(
                      it->second);
        }, this);
    addDockWidget(Qt::RightDockWidgetArea, constraint_dock_);
    connect(constraint_dock_, &pwb::ui::ConstraintPanel::activate_layer_requested,
            this, [this](const QString& layer_id) {
                const auto it = facts_.find(layer_id.toStdString());
                if (it == facts_.end()) return;
                context_.session().set_active_layer(it->second);
                if (layer_panel_ != nullptr) {
                    layer_panel_->set_active_layer(it->first);
                }
                refreshActionStates();
            });

    // Edit tools: QGIS select + digitize, applied through the one edit
    // authority.
    edit_tools_ = new pwb::ui::EditToolController(canvas_, &context_.session(),
                                                  this);
    connect(edit_tools_, &pwb::ui::EditToolController::feature_committed,
            this, [this](const QString&) { refreshActionStates(); });
    connect(edit_tools_, &pwb::ui::EditToolController::edit_error, this,
            [this](const QString& message) {
                // Non-modal: a blocking dialog here wedges offscreen hosts
                // (and interrupt-driven capture); the status bar carries
                // the message instead.
                qWarning("edit tool error: %s", message.toUtf8().constData());
                statusBar()->showMessage(message, 10000);
            });

    // Layer tree panel signals (join-key domain ids).
    connect(layer_panel_, &pwb::ui::LayerTreePanel::active_layer_changed, this,
            &MainWindow::onActiveLayerIdChanged);
    connect(layer_panel_,
            &pwb::ui::LayerTreePanel::layer_properties_requested, this,
            [this](const QString&) { openActiveLayerProperties(); });

    // Live selection/edit state drives the enablement matrix: wire the
    // QGIS authorities (per-layer signals) to the one refresh path.
    connect(context_.session().map().project(), &QgsProject::layersAdded, this,
            [this](const QList<QgsMapLayer*>& layers) {
              for (QgsMapLayer* layer : layers) {
                auto* vector_layer = qobject_cast<QgsVectorLayer*>(layer);
                if (vector_layer == nullptr) continue;
                // layersAdded fires once per layer, so these connect once
                // (UniqueConnection is not valid for functor slots — it
                // asserts in debug builds).
                connect(vector_layer, &QgsVectorLayer::selectionChanged,
                        this, [this]() { refreshActionStates(); });
                connect(vector_layer, &QgsVectorLayer::editingStarted,
                        this, [this]() { refreshActionStates(); });
                connect(vector_layer, &QgsVectorLayer::editingStopped,
                        this, [this]() { refreshActionStates(); });
              }
            });

    // Layout persistence: restore a same-version layout if present.
    layout_store_ = std::make_unique<pwb::ui::WorkbenchLayout>();
    layout_store_->restore(*this);

    // Default the session to stage 1 and show its readiness.
    applyStageValue("facies_calibration");
}

void MainWindow::onActiveLayerIdChanged(const QString& layer_id) {
    const auto it = facts_.find(layer_id.toStdString());
    if (it == facts_.end()) return;
    context_.session().set_active_layer(it->second);
    refreshActionStates();
}

void MainWindow::applyStageValue(const std::string& value) {
    const auto stage = pwb::tool_policy::stage_from_value(value);
    if (!stage.has_value()) return;
    // Canonicalize: the session string feeds the evaluator's stage
    // whitelist comparisons, which speak canonical values only.
    context_.session().set_mapping_stage(pwb::tool_policy::stage_value(*stage));
    if (stage_dock_ != nullptr) stage_dock_->set_current_stage(*stage);
    refreshActionStates();
    refresh_readiness();
}

pwb::ui::ReadinessInputs MainWindow::readiness_inputs() const {
    pwb::ui::ReadinessInputs in;
    // CRS straight from the map authority.
    in.project_crs = context_.session().map().project()->crs().authid().toStdString();
    // Horizon: the store document's stratigraphy section when open.
    // NOTE (#1380 audit, review B): this GUI-side document() read is
    // unsynchronized against worker publishes that carry rebind_layer
    // (they mutate the document under the coordinator lock). No current
    // publish path sets rebind_layer, so today the GUI is the sole
    // writer; adding one requires routing this read through a locked
    // projection first.
#ifdef PWB_WITH_DATA_INTEGRATION
    if (context_.projectStore() != nullptr) {
        const pwb::project::ProjectDocument& document =
            context_.projectStore()->document();
        const pwb::domain::Json* stratigraphy =
            document.find_section("stratigraphy");
        if (stratigraphy != nullptr && stratigraphy->contains("target_horizon")) {
            const pwb::domain::Json& horizon =
                (*stratigraphy)["target_horizon"];
            if (horizon.is_string()) {
                in.target_horizon = horizon.get<std::string>();
            }
        }
        const pwb::domain::Json* workarea =
            document.find_section("workarea");
        if (workarea != nullptr && workarea->contains("boundary")) {
            const pwb::domain::Json& boundary = (*workarea)["boundary"];
            if (boundary.is_array()) {
                for (const auto& vertex : boundary) {
                    if (vertex.is_array() && vertex.size() >= 2
                        && vertex[0].is_number() && vertex[1].is_number()) {
                        ++in.workarea_boundary_vertices;
                    }
                }
            }
        }
    }
#endif  // PWB_WITH_DATA_INTEGRATION
    // Layer-derived facts from the live session (join-key iteration).
    for (const std::string& layer_id : context_.session().map().layerIdsTopFirst()) {
        const auto it = facts_.find(layer_id);
        const std::string role =
            it != facts_.end() ? it->second.role : std::string();
        QgsVectorLayer* layer =
            context_.session().map().vectorLayerById(layer_id);
        if (layer == nullptr) continue;
        if (facies_polygon_role(role)) {
            // Python counts Polygon/MultiPolygon FEATURES (not layers):
            // filter by geometry type; skip unknown counts (-1).
            if (layer->geometryType() == Qgis::GeometryType::Polygon
                && layer->featureCount() > 0) {
                in.facies_polygon_count +=
                    static_cast<int>(layer->featureCount());
                in.facies_polygons_loaded = true;
            }
        }
        // One factor run = one task: the pipeline emits a contour layer
        // per run (classification/grid layers are its siblings).
        if (role == pwb::tool_policy::layer_role::kFactorContour) {
            ++in.factor_tasks_complete;
            ++in.factor_tasks_total;
        }
        if (role == pwb::tool_policy::layer_role::kInitialFaciesDraft
            && layer->featureCount() > 0) {
            ++in.facies_draft_layers;
        }
        if (role == pwb::tool_policy::layer_role::kIntegratedFacies
            || role == pwb::tool_policy::layer_role::kIntegratedBoundary) {
            ++in.integrated_draft_layers;
        }
        if (pwb::tool_policy::layer_role::is_line_role(role)) {
            QgsFeatureIterator feat = layer->getFeatures();
            QgsFeature feature;
            while (feat.nextFeature(feature)) {
                if (!feature.hasGeometry()) continue;
                if (feature.geometry().type()
                    == Qgis::GeometryType::Line) {
                    ++in.constraint_lines;
                }
            }
        }
    }
    return in;
}

void MainWindow::refresh_readiness() {
    if (stage_dock_ == nullptr) return;
    const pwb::ui::ReadinessInputs inputs = readiness_inputs();
    for (const pwb::tool_policy::MappingStage stage :
         pwb::tool_policy::kStageOrder) {
        stage_dock_->set_readiness(
            stage, pwb::ui::evaluate_stage_readiness(stage, inputs));
    }
}

void MainWindow::refresh_constraint_panel() {
    if (constraint_dock_ != nullptr) constraint_dock_->refresh(context_.session());
}

void MainWindow::deleteSelectedFeatures() {
    const auto active = context_.session().active_layer();
    if (!active.has_value()) return;
    int deleted = 0;
    const std::string error =
        context_.session().edit().delete_selected(active->layer_id, &deleted);
    if (!error.empty()) {
        QMessageBox::warning(this, tr("删除所选"),
                             QString::fromStdString(error));
        return;
    }
    context_.session().map().refreshCanvases();
    statusBar()->showMessage(tr("已删除 %1 个要素").arg(deleted), 6000);
    refreshActionStates();
}

void MainWindow::openActiveLayerProperties() {
    const auto active = context_.session().active_layer();
    if (!active.has_value()) return;
    QgsVectorLayer* layer =
        context_.session().map().vectorLayerById(active->layer_id);
    if (layer == nullptr) return;
    // Native QGIS renderer dialog applies on OK.
    pwb::ui::layer_style::open_renderer_properties(layer, canvas_, this);
    // Persist the configured style next to the layer's data file so it
    // survives reopen (QML sidecar, the QGIS convention).
    pwb::ui::layer_style::save_style_sidecar(
        layer, layer->source());
    refreshActionStates();
}

void MainWindow::saveLayoutState() {
    if (layout_store_ != nullptr) layout_store_->save(*this);
    statusBar()->showMessage(tr("布局已保存"), 4000);
}

void MainWindow::resetLayoutState() {
    if (layout_store_ != nullptr) layout_store_->reset();
    layout_reset_pending_ = true;
    // The CONV-PS store restores AFTER layout_store_ at startup, so its
    // layout keys must go too or the pre-reset layout wins the next launch.
    if (services_settings_ != nullptr) {
        services_settings_->remove(
            pwb::platform_services::LayoutKeys::window_state);
        services_settings_->remove(
            pwb::platform_services::LayoutKeys::window_geometry);
        services_settings_->remove(
            pwb::platform_services::LayoutKeys::state_version);
    }
    statusBar()->showMessage(tr("布局已重置（下次启动恢复默认）"), 6000);
}
#endif

}  // namespace pwb::app
