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

#ifdef PWB_WITH_APP_SHELL
#include <pwb/ui_widgets/icon_factory.hpp>
#endif

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
#include <pwb/job_runtime/thread_join_guard.hpp>
#endif
// END CONV-30

// BEGIN VIZ-E — data/preview page assembly (plan P-A + V6).
#if defined(PWB_WITH_VIZ_E) && defined(PWB_WITH_CONV_30)
#include "viz_e_install.hpp"
#endif
// END VIZ-E
// BEGIN CLOSURE-PREVIEW (task 04) — unified data page / parse registry /
// preview dispatch closure (superset guard of the VIZ-E closure).
#if defined(PWB_WITH_CLOSURE_PREVIEW)
#include "closure_preview_install.hpp"
#endif
// END CLOSURE-PREVIEW

// BEGIN CLOSURE-REVIEW — line 09: the 审核治理/可验证发布 install (the
// review page's real IReviewActions backend over the AppContext store).
#ifdef PWB_WITH_CLOSURE_REVIEW
#include "closure_review_install.hpp"
#endif
// END CLOSURE-REVIEW

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

#ifdef PWB_WITH_STAGE_FLOW
#include <pwb/ui_stageflow/qt/stage_flow_controller.hpp>
#endif

#ifdef PWB_WITH_CONV_27
#include <qgsproject.h>
#include <qgsvectorlayer.h>

#include <pwb/tool_policy/layer_roles.hpp>
#include <pwb/ui/layer_properties.hpp>
#endif
#ifdef PWB_WITH_GEO3D_VIZ
#include "geo3d_dock.hpp"
#include "closure_joint3d_install.hpp"
#ifdef PWB_WITH_UI_WELLSEIS
#include "joint_analysis_install.hpp"
#include "viz_c_joint_host.hpp"
#endif
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

#if defined(PWB_WITH_SEISMIC_VIEWER)
// M3 (P0-1/P0-4): the workspace bottom + validation comparison panes are
// SeismicSliceWidget views routed from the ONE catalog open path (a second
// VIEW of the same volume authority, never a second loader).
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#endif

#include <qgsfeatureiterator.h>
#include <qgslayertreeview.h>
#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
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
#include <pwb/qgis/layer_factory.hpp>
#include <pwb/qgis/map_project_store.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/project/paths.hpp>
#include <pwb/workspace/state_ops.hpp>

#include "app_context.hpp"
#include "diagnostics.hpp"
#ifdef PWB_WITH_QGIS_BROWSER
#include "qgis_data_workspace_install.hpp"
#endif
#ifdef PWB_WITH_APP_SHELL
#include "app_shell.hpp"
#include "workspace_compose.hpp"
#include "ribbon_command_install.hpp"
#include "m5_validation_install.hpp"
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_composite/layer_manager_panel.hpp>
#if defined(PWB_WITH_CLOSURE_MAPPING)
#include "m5_compose_install.hpp"
#endif
#include "m5_data_install.hpp"

#if __has_include(<pwb/closure_science/qt/page_binding.hpp>)
#include <pwb/closure_science/qt/page_binding.hpp>
#endif
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/dock_registry.hpp>
#include <pwb/ui_shell/layout_presets.hpp>
#include <pwb/ui_shell/status_bar.hpp>
// M2 (UI-18) — the ribbon chrome: QAT binds the governed ToolActionSet
// save/undo/redo actions (the SAME QAction objects the menus/shortcuts
// reuse — D4, no parallel actions).
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
// cpp-close-12 — palette tool-details come from the canonical explain()
// formatter (UI-12 domain); no second state table in this shell.
#include <pwb/ui_workstation/action_help.hpp>
// Ribbon file-menu 面板/布局 submenus drive the dock host directly.
#include <pwb/ui_workstation/workstation_frame.hpp>
#endif
#include "shell_project_actions.hpp"
#include <QStandardPaths>
#ifdef PWB_WITH_UI_PAGES_PREVIEW_QT
// UI-15's modal container for the shared UI-07 settings editor — reused
// verbatim; this shell adds only the store lifetime and the open() call.
#include <pwb/ui_canvas/qt/preview_settings_dialog.hpp>
#include <pwb/ui_pages_preview/qt/preview_settings_store.hpp>
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
#ifdef PWB_WITH_WELL_PRESENTERS
#include "well_presenter_install.hpp"
#include <QDebug>
#endif

// BEGIN CLOSURE-MAPPING
#ifdef PWB_WITH_CLOSURE_MAPPING
#include "closure_mapping_install.hpp"
#ifdef PWB_WITH_WORKFLOW_WIRING
#include "workflow_install.hpp"
#endif
#endif
// END CLOSURE-MAPPING

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
    // cpp-close-12 — 工程属性 default surface (tests inject a responder).
    properties_responder_ = [this](const QString& text) {
        QMessageBox::information(this, tr("工程属性"), text);
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
#ifdef PWB_WITH_APP_SHELL
    // M2 (D7): the ribbon mode + workspace persist on the same unified
    // (PaleoWorkbench, Workstation) store. The shell was constructed
    // BEFORE the settings store was bound (buildUi order), so its restore
    // runs here — after the bind, before show().
    if (app_shell_ != nullptr) app_shell_->restore_ribbon_state();
#endif
    // Apply the restored sheet once the widget tree is complete (and sync
    // the checkable theme/density actions to the restored state).
    theme_service_->apply(*this);
    syncThemeMenuChecks();
}

MainWindow::~MainWindow() {
#ifdef PWB_WITH_STAGE_FLOW
    // The process-global command registry must not keep this window's
    // closures after destruction (a palette evaluate on another window
    // would dereference a dead this). Unregister HERE — in the body,
    // while stage_flow_command_ids_ is still alive (a destroyed-signal
    // hook runs in ~QObject, after member destruction).
    for (const std::string& id : stage_flow_command_ids_) {
        pwb::ui_shell::command_registry().unregister(id);
    }
    stage_flow_command_ids_.clear();
#endif
#ifdef PWB_WITH_APP_SHELL
    // M4 (UI-18): the ribbon command set is per-window too — same dangling-
    // closure contract as the stage-flow seeds above.
    for (const std::string& id : ribbon_command_ids_) {
        pwb::ui_shell::command_registry().unregister(id);
    }
    ribbon_command_ids_.clear();
#endif
#ifdef PWB_WITH_CONV_30
    // Joint host FIRST (review R2): its prep owner can have a pending
    // terminal-aware reissue (#1471) — after the JobCenter sweep resets
    // the owners, such a chain could still submit a fresh prep job
    // mid-teardown. VizCJointHost::shutdown sets shutdown_done_ (no
    // post-shutdown resurrection) and drains its own owners, bounded.
#if defined(PWB_WITH_GEO3D_VIZ) && defined(PWB_WITH_UI_WELLSEIS)
    if (geo3d_dock_ != nullptr &&
        geo3d_dock_->existing_joint_host() != nullptr) {
        geo3d_dock_->existing_joint_host()->shutdown(1000);
    }
#endif
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
    // M6: named identity — the shell hosts MULTIPLE QgsMapCanvas instances
    // (session canvas, validation compare canvas, mapping-page previews);
    // lookups by type+order are fragile, the session canvas is named.
    canvas_->setObjectName(QStringLiteral("session-map-canvas"));
#ifdef PWB_WITH_GEO3D_VIZ
    // 06 closure: the Geo3D dock (and its joint host) must exist BEFORE
    // the AppShell builds its pages — the joint page receives the real
    // host at construction (widget vs placeholder is a ctor decision).
    // The JobCenter property lives on the DOCK because that is where
    // Geo3DDock::joint_host() reads it (previously set on the window,
    // which the dock never saw — the product host could not be created).
    geo3d_dock_ = new Geo3DDock(this);
  #ifdef PWB_WITH_CONV_30
    geo3d_dock_->setProperty(
        "pwb_job_center",
        QVariant::fromValue(static_cast<pwb::app::JobCenter*>(
            job_center_.get())));
  #endif
#endif
#ifdef PWB_WITH_APP_SHELL
    // W5/UI-17 — the page-navigation shell hosts the composite document;
    // the session canvas is its central canvas (same widget, reparented —
    // the session's attachCanvas pointer stays valid).
#if defined(PWB_WITH_GEO3D_VIZ) && defined(PWB_WITH_UI_WELLSEIS)
    app_shell_ = new AppShell(this, geo3d_dock_->joint_host());
#else
    app_shell_ = new AppShell(this);
#endif
    app_shell_->install_canvas(canvas_);
    setCentralWidget(app_shell_);
// BEGIN CLOSURE-REVIEW
#ifdef PWB_WITH_CLOSURE_REVIEW
    pwb::app::closure_review::install_review_actions(app_shell_,
                                                     &context_);
#endif
// END CLOSURE-REVIEW
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
#if defined(PWB_WITH_APP_SHELL) && defined(PWB_WITH_CONV_27)
    app_shell_->adopt_layer_tree_dock(dock);
    connect(app_shell_->composite()->layer_manager,
            &pwb::ui_composite::LayerManagerPanel::active_layer_changed,
            this, [this](const QVariant& layer_id) {
                if (layer_panel_ != nullptr && layer_id.isValid()) {
                    layer_panel_->set_active_layer(
                        layer_id.toString().toStdString());
                }
            });
#endif
#ifdef PWB_WITH_QGIS_BROWSER
    // QGIS-native generic data browser (data-management convergence seam;
    // the domain data page stays a well/lineage view — see
    // qgis_data_workspace_install.hpp).
    pwb::app::qgis_data_workspace::install_data_browser(*this);
#endif

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
    // The dock itself was created at the top of buildUi (06 closure: it
    // must precede the AppShell so the joint page receives the real
    // host). Only the dock placement and its 2D-map seam stay here.
    addDockWidget(Qt::RightDockWidgetArea, geo3d_dock_);
    connect(geo3d_dock_, &Geo3DDock::well_selected, this,
            [this](const QString& well) {
                statusBar()->showMessage(tr("3D 选中井: %1").arg(well), 5000);
            });
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
// BEGIN PWB-V14-THREE-STAGE — selection-bus sink target (dock raise).
#ifdef PWB_WITH_STAGE_FLOW
    stage_flow_well_log_dock_ = well_log_dock;
#endif
// END PWB-V14-THREE-STAGE

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
            // Transient message, NOT status_label_: the persistent label
            // is rewritten by every refreshActionStates pass (工具可用
            // N/M), which used to erase the readout within a tick
            // (#1451).
            QString text;
            if (event.kind ==
                pwb::viz::WellLogInterpretationEvent::Kind::marker_hit) {
                text = tr("地层顶部: %1 @ %2").arg(label).arg(event.top);
            } else {
                text = tr("相带证据: %1 [%2, %3] %4")
                           .arg(label)
                           .arg(event.top)
                           .arg(event.bottom)
                           .arg(QString::fromStdString(event.unit));
            }
            statusBar()->showMessage(text, 6000);
        });
#if defined(PWB_WITH_VIZ_A) && defined(PWB_WITH_CONV_30)
    // BEGIN VIZ-A — production wiring (preview provider + background LAS
    // loads through the JobCenter). One call; the body lives in
    // viz_a_install.cpp.
    viz_a::install(this, job_center_.get());
#endif
    // END VIZ-A
#endif
// BEGIN 05 — well/time-depth external presenters into the viz-e data page
// registry (05→04 contract; body lives in well_presenter_install.cpp).
#if defined(PWB_WITH_WELL_PRESENTERS)
    if (!well_presenters::install()) {
        qWarning() << "well presenters: duplicate kind registration "
                      "(wiring bug — first registration kept)";
    }
#endif
// END 05
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
    // BEGIN CLOSURE-PREVIEW (task 04) — one data page per window: with the
    // AppShell the composed page ADOPTS the hub's management workspace
    // (the dock was the duplicate selection entry); the reduced shell
    // keeps the dock mount.
#  if defined(PWB_WITH_CLOSURE_PREVIEW) && defined(PWB_WITH_APP_SHELL)
    closure_preview::install(
        pwb::closure_preview::Install{
            this, app_shell_, job_center_.get(),
            [this]() -> std::shared_ptr<pwb::application::PwbDataStore> {
                return context_.projectStore();
            }});
#  else
    viz_e_data_dock_ =
        pwb::viz_e::install_data_dock(this, job_center_.get());
#  endif
    // END CLOSURE-PREVIEW
#endif
    // END VIZ-E
// BEGIN JOINT-ANALYSIS (geoviz final closure) — the 井震联合 3D page's
// analysis hooks (stratal demo/.dat, RGB fusion overlay, crossplot,
// FLAC3D/Abaqus export, advisor, joint-analysis sidecar persistence).
// Every kernel already existed natively; this is the product wiring the
// empty-hook fallbacks ("未接入") were waiting for.
#ifdef PWB_WITH_JOINT_ANALYSIS
    if (geo3d_dock_ != nullptr && app_shell_ != nullptr &&
        app_shell_->geomodel_page() != nullptr && job_center_ != nullptr) {
        pwb::app::joint_analysis::JointAnalysisInstall joint_deps;
        joint_deps.page = app_shell_->geomodel_page();
        joint_deps.host = geo3d_dock_->joint_host();
        joint_deps.scene_objects =
            &geo3d_dock_->viewport()->scene_manager();
        joint_deps.jobs = job_center_.get();
        joint_deps.dialog_parent = this;
        joint_deps.project_directory = [this] {
            return joint_project_directory_;
        };
        joint_deps.project_document = [this] {
            const auto store = context_.projectStore();
            return store ? store->document().root() : pwb::domain::Json::object();
        };
#ifdef PWB_WITH_VIZ_B
        // Real LAS curves for the joint auto-tie (copied on the GUI
        // thread by the hook before the tie job starts). Without VIZ-B
        // the hook keeps its honest "no logs" refusal.
        joint_deps.well_logs = [this] {
            return viz_b_dock_ != nullptr
                       ? viz_b_dock_->well_columns()
                       : std::vector<pwb::viz::cross_well::WellColumnData>{};
        };
#endif
        pwb::app::joint_analysis::install(joint_deps);
    }
#endif
// END JOINT-ANALYSIS

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
// BEGIN CLOSURE-MAPPING — 08-line product install (mapping-page adopt set
// + preparation page + document bank). Requires the AppShell composition.
#ifdef PWB_WITH_CLOSURE_MAPPING
    if (app_shell_ != nullptr) {
        pwb::app::closure_mapping::Install closure_install;
        closure_install.window = this;
        closure_install.shell = app_shell_;
        closure_install.store_getter = [this]()
            -> std::shared_ptr<pwb::application::PwbDataStore> {
            return context_.projectStore();
        };
#ifdef PWB_WITH_CONV_29
        closure_install.layout_export = [this](const std::string& composition,
                const std::string& path, const std::string& format, double dpi) {
            auto& map = context_.session().map();
            const auto state = pwb::domain::Json::parse(map.canvas_state_json());
            pwb::qgis::CompositionExportRequest request;
            request.format = format;
            request.dpi = dpi;
            request.force_vector = format == "svg" || format == "pdf";
            request.crs = state.value("crs", std::string());
            if (state.contains("extent") && state["extent"].is_array() && state["extent"].size() == 4) {
                request.has_extent = true;
                for (int i = 0; i < 4; ++i) request.extent[i] = state["extent"][i].get<double>();
            }
            pwb::qgis::CompositionLayoutService service(map);
            return service.export_layout(composition, std::filesystem::u8path(path), request);
        };
#endif
        pwb::app::closure_mapping::install(closure_install);
    }
#endif
// END CLOSURE-MAPPING
// BEGIN PWB-V14-THREE-STAGE — three-stage workbench install: stage bar
// mount + controller seams + production commands + task-center
// providers + selection bus. Last so every adopted surface exists.
#ifdef PWB_WITH_STAGE_FLOW
    installStageFlow();
#endif
// END PWB-V14-THREE-STAGE
// BEGIN UI-14 WORKFLOW-WIRING — the composition root: WorkflowController
// with every seam bound to the real services/pages + the per-project
// catalog closure + stage-action/shelf routing. Last: it consumes the
// preparation page, document bank and factor grid store the mapping
// closure installed.
#ifdef PWB_WITH_WORKFLOW_WIRING
    if (app_shell_ != nullptr && job_center_ != nullptr) {
        pwb::app::workflow_wiring::install(
            this, app_shell_, &context_, job_center_.get());
    }
#endif
// END UI-14 WORKFLOW-WIRING
// BEGIN UI-18 M3 — five-workspace composition (P0): fills the science-host
// per-stage bottom stack (ws1 两联 / ws2 连井+制备 / ws3 参考带) and the
// validation page pane. After every closure install so every adopted
// surface exists; per-slice guards keep reduced builds honest.
#ifdef PWB_WITH_APP_SHELL
    if (app_shell_ != nullptr) {
        workspace_compose::compose({this, app_shell_, &context_,
                                    job_center_.get()});
    }
#endif
// END UI-18 M3
// BEGIN UI-18 M4 — the ribbon command band: 58 placeholder ids become real
// CommandRegistry commands (or honest disabled entries), then the ribbon
// binds governed QActions + the session-aware evaluator.
#ifdef PWB_WITH_APP_SHELL
    if (app_shell_ != nullptr) {
        ribbon_commands::install({this, app_shell_, &context_,
                                  job_center_.get(), &ribbon_command_ids_});
        wire_ribbon_commands();
    }
#endif
// END UI-18 M4
// BEGIN UI-18 M5 — the validation workspace gaps: 解释 vs 预测对比视图 +
// 问题级人工复核状态机 (compiled where ClosureReview is linked).
#if defined(PWB_WITH_M5_VALIDATION)
    if (app_shell_ != nullptr) {
        m5_validation::install({this, app_shell_, &context_});
    }
#endif
// END UI-18 M5
// BEGIN UI-18 M5-2 — 版式轻量页 + 上下文 Ribbon 组（编图切片构建）。
#if defined(PWB_WITH_CLOSURE_MAPPING)
    if (app_shell_ != nullptr) {
        m5_compose::install({this, app_shell_, &context_});
    }
#endif
// END UI-18 M5-2
// BEGIN UI-18 M5-3 — 数据管理属性/血缘装配 + hub 轴解散（页面住进工作区）。
#ifdef PWB_WITH_APP_SHELL
    if (app_shell_ != nullptr) {
        m5_data::install({this, app_shell_, &context_});
    }
#endif
// END UI-18 M5-3
#ifdef PWB_WITH_APP_SHELL
    if (app_shell_ != nullptr) {
        // qt_ribbon_native parity: the AppShell's own dock surfaces
        // (nav/inspector/tasks…) replace the legacy window-level dock
        // chrome — every MainWindow-direct dock starts hidden; stage
        // profiles (window.* keys) and menu actions raise the ones a
        // surface needs. A persisted saveState still wins over this
        // default (restore runs later in the ctor).
        const auto legacy_docks = findChildren<QDockWidget*>(
            QString(), Qt::FindDirectChildrenOnly);
        for (auto* legacy : legacy_docks) {
            legacy->hide();
        }
    }
#endif
}

#ifdef PWB_WITH_APP_SHELL
void MainWindow::wire_app_shell() {
    // 主状态条入宿主原生槽位（Python dock_host=QMainWindow parity:
    // AppShell parks its StatusBar on the window's statusBar, stretch 1).
    statusBar()->addWidget(app_shell_->status_bar(), 1);

    // M2 (UI-18) — ribbon host wiring:
    //  * QAT save/undo/redo bind the governed ToolActionSet actions (the
    //    same objects the edit menu/toolbar consume — D4 single source).
    //  * Persistence resolves the services store LAZILY per call: buildUi
    //    runs before the constructor binds services_settings_, and tests
    //    inject their own store — both stay honest.
    if (app_shell_->ribbon() != nullptr) {
        pwb::ui_ribbon::qt::RibbonBar::QuickAccessActions qat;
        qat.save = governedAction(QStringLiteral("save_edits"));
        qat.undo = governedAction(QStringLiteral("undo"));
        qat.redo = governedAction(QStringLiteral("redo"));
        app_shell_->ribbon()->set_quick_access_actions(qat);
    }
    app_shell_->set_ribbon_persistence(
        [this](const std::string& key) -> std::optional<std::string> {
            if (services_settings_ == nullptr) return std::nullopt;
            const QVariant value = services_settings_->value(
                QString::fromStdString("ribbon/" + key));
            if (!value.isValid()) return std::nullopt;
            return value.toString().toStdString();
        },
        [this](const std::string& key, const std::string& value) {
            if (services_settings_ == nullptr) return;
            services_settings_->setValue(
                QString::fromStdString("ribbon/" + key),
                QString::fromStdString(value));
        });
    connect(app_shell_, &AppShell::exit_requested, this,
            [this] { close(); });

// BEGIN CLOSURE-SCIENCE (line 03) — production science/prediction page
// binding: the well-log + seismic prediction pages receive the
// catalog-backed inference hooks (real ONNX runtime, catalog runs +
// result versions, task journal, project-identity guard). Parented to the
// shell — no AppShell member changes. Lease: 03-line.json
// named_block_leases; assembled under PWB_BUILD_CLOSURE_SCIENCE by 12.
#if defined(PWB_WITH_CLOSURE_SCIENCE) && defined(PWB_WITH_DATA_INTEGRATION)
    pwb::closure_science::qt::attach_prediction_pages(
        *app_shell_->well_log_page(), *app_shell_->seismic_page(),
        [this]() -> std::filesystem::path {
            auto store = context_.projectStore();
            if (store == nullptr) return std::filesystem::path();
            return store->project_file();
        },
        app_shell_);
#endif
// END CLOSURE-SCIENCE

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
    // BEGIN CPP-CLOSE-12 — the UI-17 deferred request surfaces get their
    // production handlers (shell_project_actions integration slice).
    connect(app_shell_, &AppShell::save_project_requested, this,
            [this] { saveProjectRequested(); });
    connect(app_shell_, &AppShell::open_sample_project_requested, this,
            [this] { openSampleProjectRequested(); });
    connect(app_shell_, &AppShell::properties_requested, this,
            [this] { showProjectProperties(); });
    // END CPP-CLOSE-12
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
    // BEGIN CPP-CLOSE-12 — CommandPalette providers (the remaining UI-17
    // deferred injections). The context derives from the live session
    // snapshot each popup; tool details come from the canonical
    // ui_workstation explain() formatter (no second state table here).
    if (app_shell_->command_palette() != nullptr) {
        app_shell_->command_palette()->set_context_provider(
            [this]() -> const pwb::ui_shell::CommandContext* {
                const pwb::tool_policy::ToolContextSnapshot snapshot =
                    context_.session().snapshot();
                palette_context_ = pwb::ui_shell::CommandContext();
                palette_context_.write_granted = snapshot.write_granted;
                palette_context_.mapping_stage = snapshot.mapping_stage;
                return &palette_context_;
            });
        app_shell_->command_palette()->set_tool_details_provider(
            [this](const std::string& tool_id,
                   const pwb::ui_shell::CommandContext&) -> QString {
                return QString::fromStdString(pwb::ui_workstation::
                                                  format_details(
                                                      pwb::ui_workstation::
                                                          explain(
                                                              tool_id,
                                                              context_
                                                                  .session()
                                                                  .snapshot())));
            });
    }
    // END CPP-CLOSE-12
#ifdef PWB_WITH_UI_PAGES_PREVIEW_QT
    connect(app_shell_, &AppShell::preview_settings_requested, this,
            [this] { showPreviewSettingsRequested(); });
#endif
}
#endif

#ifdef PWB_WITH_APP_SHELL
void MainWindow::wire_ribbon_commands() {
    if (app_shell_ == nullptr || app_shell_->ribbon() == nullptr) return;
    auto* ribbon = app_shell_->ribbon();

    // -- governed QAction bindings (D4: the SAME QAction objects the
    // menus/shortcuts reuse — bound buttons follow policy enablement).
    ribbon->set_command_action(QStringLiteral("map.select"),
                               governedAction(QStringLiteral("select")));
    ribbon->set_command_action(QStringLiteral("map.edit_facies"),
                               governedAction(
                                   QStringLiteral("toggle_editing")));
    ribbon->set_command_action(QStringLiteral("map.export"),
                               governedAction(QStringLiteral("map_export")));

    // -- D8 disabled-reason channel: the registry verdict under the LIVE
    // session snapshot (no project / no write / stage gates / busy all
    // surface as concrete Chinese reasons through the ribbon tooltips).
    ribbon->set_command_evaluator(
        [this](const std::string& command_id) -> pwb::ui_ribbon::CommandState {
            auto& registry = pwb::ui_shell::command_registry();
            if (registry.get(command_id) == nullptr) return {true, ""};
            const pwb::tool_policy::ToolContextSnapshot snapshot =
                context_.session().snapshot();
            palette_context_ = pwb::ui_shell::CommandContext();
            palette_context_.write_granted = snapshot.write_granted;
            palette_context_.mapping_stage = snapshot.mapping_stage;
            const auto verdict = registry.evaluate(command_id, &palette_context_);
            return {verdict.enabled, verdict.reason};
        });

    // -- the full file menu (R:20): same handlers as the native 文件 menu,
    // MRU rides the same settings store (refreshRecentProjects fills both).
    // No shortcuts here on purpose: the native menu bar carries the
    // canonical key bindings (Ctrl+N/O/Q…) — a second binding would make
    // them ambiguous; the ribbon file button is a mouse surface.
    auto* file = new QMenu(app_shell_);
#ifdef PWB_WITH_DATA_INTEGRATION
    file->addAction(tr("新建工程…"), this, [this] { newProjectDialog(); });
    file->addAction(tr("打开工程…"), this, [this] { openProjectDialog(); });
    file->addAction(tr("保存工程"), this, [this] { saveProjectRequested(); });
    file->addAction(tr("打开样例工程"), this,
                    [this] { openSampleProjectRequested(); });
    file->addSeparator();
    file->addAction(tr("工程属性…"), this,
                    [this] { showProjectProperties(); });
    file->addSeparator();
#endif
    ribbon_recent_menu_ = new QMenu(tr("最近工程(&R)"), file);
    file->addMenu(ribbon_recent_menu_);
    file->addSeparator();
    // 面板开关 + 布局预设 — 低频命令收敛进文件菜单（R:20）。dock 勾选态
    // 随 dock visibilityChanged 双向同步。
    if (auto* ws = app_shell_->workstation()) {
        auto* panels = file->addMenu(tr("面板(&P)"));
        for (const auto& desc :
             pwb::ui_shell::workstation_dock_registry().descriptors()) {
            auto* dock = ws->dock(desc.dock_id);
            if (dock == nullptr) continue;
            auto* toggle = panels->addAction(
                QString::fromStdString(desc.title));
            toggle->setCheckable(true);
            toggle->setChecked(dock->isVisible());
            const std::string dock_id = desc.dock_id;
            connect(toggle, &QAction::triggered, this,
                    [ws, dock_id](bool on) {
                        ws->set_dock_visible(dock_id, on);
                    });
            connect(dock, &QDockWidget::visibilityChanged, toggle,
                    &QAction::setChecked);
        }
        auto* layouts = file->addMenu(tr("布局(&L)"));
        for (const auto& [preset_id, label] :
             pwb::ui_shell::preset_labels()) {
            layouts->addAction(QString::fromStdString(label), this,
                               [ws, preset_id] {
                                   ws->apply_layout_preset(preset_id);
                               });
        }
        file->addSeparator();
    }
    file->addAction(tr("退出"), this, [this] { close(); });
    ribbon->set_file_menu(file);
    ribbon_file_menu_ = file;
    refreshRecentProjects();
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
#ifdef PWB_WITH_APP_SHELL
    // QAT 再绑定：wire_app_shell 的绑定跑在 actions_ 物化之前
    // （buildUi 先于本函数），当时拿到 nullptr → QAT 按钮被隐藏。
    // 动作存在后重绑 —— 同一 QAction 对象（D4 单一来源）。
    if (app_shell_ != nullptr && app_shell_->ribbon() != nullptr) {
        pwb::ui_ribbon::qt::RibbonBar::QuickAccessActions qat;
        qat.save = governedAction(QStringLiteral("save_edits"));
        qat.undo = governedAction(QStringLiteral("undo"));
        qat.redo = governedAction(QStringLiteral("redo"));
        app_shell_->ribbon()->set_quick_access_actions(qat);
    }
#endif
    for (const Wire& wire : wired) {
        QAction* action = actions_.action(wire.id);
        if (action == nullptr) continue;   // vocabulary drift: keep honest
        action->setText(tr(wire.text));
        if (!wire.shortcut.isEmpty()) action->setShortcut(wire.shortcut);
    }

#ifdef PWB_WITH_APP_SHELL
    const struct {
        const char* id;
        const char* icon;
    } map_icons[] = {
        {"reference_import", "tree-add-layer"},
        {"layer_new", "tree-add-layer"},
        {"pan", "pan"},
        {"zoom_in", "zoom_in"},
        {"zoom_out", "zoom_out"},
        {"full_extent", "full_extent"},
        {"refresh", "refresh"},
        {"toggle_editing", "toggle_editing"},
        {"vertex", "vertex"},
        {"undo", "undo"},
        {"redo", "redo"},
        {"save_edits", "save_edits"},
        {"rollback", "rollback"},
#ifdef PWB_WITH_CONV_27
        {"select", "select"},
        {"add_point", "add_point"},
        {"add_line", "add_line"},
        {"add_polygon", "add_polygon"},
        {"delete_selected", "delete_selected"},
#endif
    };
    for (const auto& entry : map_icons) {
        if (QAction* action = actions_.action(entry.id)) {
            action->setIcon(pwb::ui_widgets::tinted_map_icon(
                QString::fromUtf8(entry.icon)));
        }
    }
    if (app_shell_ != nullptr && app_shell_->composite() != nullptr) {
        std::vector<QAction*> map_actions = {
            actions_.action("reference_import"),
            actions_.action("layer_new"),
            nullptr,
            actions_.action("pan"),
            actions_.action("zoom_in"),
            actions_.action("zoom_out"),
            actions_.action("full_extent"),
            actions_.action("refresh"),
            nullptr,
            actions_.action("toggle_editing"),
#ifdef PWB_WITH_CONV_27
            actions_.action("select"),
            actions_.action("add_point"),
            actions_.action("add_line"),
            actions_.action("add_polygon"),
            actions_.action("vertex"),
            actions_.action("delete_selected"),
#endif
            nullptr,
            actions_.action("undo"),
            actions_.action("redo"),
            actions_.action("save_edits"),
            actions_.action("rollback"),
        };
        app_shell_->composite()->set_map_actions(map_actions);
    }
#endif

    QMenu* file_menu = menuBar()->addMenu(tr("文件(&F)"));
#ifdef PWB_WITH_DATA_INTEGRATION
    file_menu->addAction(tr("新建工程…"), this,
                         &MainWindow::newProjectDialog,
                         QKeySequence::New);
    file_menu->addAction(tr("打开工程…"), this,
                         &MainWindow::openProjectDialog, QKeySequence::Open);
    // BEGIN CPP-CLOSE-12 — 工程保存/样例工程/属性 menu parity with the
    // app-bar surfaces (no shortcut: Ctrl+S stays 提交编辑 in this shell).
    file_menu->addAction(tr("保存工程"), this,
                         [this] { saveProjectRequested(); });
    file_menu->addAction(tr("打开样例工程"), this,
                         [this] { openSampleProjectRequested(); });
    file_menu->addAction(tr("工程属性…"), this,
                         [this] { showProjectProperties(); });
    // END CPP-CLOSE-12
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
#ifdef PWB_WITH_CONV_27
    // M4 (R:20): the retired 地图工具 toolbar's edit tools live here now —
    // the same governed QActions (also bound into the ws3 ribbon band), no
    // command lost, no parallel actions.
    edit_menu->addSeparator();
    edit_menu->addAction(actions_.action("select"));
    edit_menu->addAction(actions_.action("add_point"));
    edit_menu->addAction(actions_.action("add_line"));
    edit_menu->addAction(actions_.action("add_polygon"));
    edit_menu->addAction(actions_.action("delete_selected"));
#endif
    edit_menu->addSeparator();
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
// BEGIN CLOSURE-SEISMIC (07) — dock-side menu entries: slice export +
// view-state persistence for this dock's SeismicSliceWidget (actions forward
// to the widget API). These ride the VIZ-D guard on purpose: the menus only
// need Pwb::SeismicViewer (no closure-page service deps). The hub-2
// prediction page's viewer keeps its own widget-level API via
// closure_seismic_install — menu parity there is a recorded limitation.
    if (viz_d_seismic_host_ != nullptr) {
        pwb::viz_d::add_seismic_export_menu_actions(*seismic_menu,
                                                    *viz_d_seismic_host_);
        pwb::viz_d::add_seismic_view_state_menu_actions(*seismic_menu,
                                                        *viz_d_seismic_host_);
    }
// END CLOSURE-SEISMIC
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

    // M4 (R:20): the 地图工具 toolbar RETIRES — every action it carried
    // stays reachable through the menus (view/edit/file above) and the
    // ws3 ribbon band (the same governed QActions via set_command_action).
    // Nothing removed, nothing re-implemented.
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

QString MainWindow::openDataFile(const QString& path) {
    // Provider-driven admission: the registry names every sublayer inside
    // the URI (GeoPackage tables, sub-datasets, …) with the provider's
    // own key; failures come back from the provider, never fabricated.
    std::string query_error;
    const std::vector<pwb::qgis::layer_factory::ProposedSublayer> sublayers =
        pwb::qgis::layer_factory::query_sublayers(path.toStdString(),
                                                  &query_error);
    if (sublayers.empty()) {
        return QString::fromStdString(query_error);
    }
    const QString base = QFileInfo(path).completeBaseName();
    int added = 0;
    std::string first_error;
    for (const pwb::qgis::layer_factory::ProposedSublayer& sublayer :
         sublayers) {
        const QString name = sublayers.size() == 1
                                 ? base
                                 : base + QLatin1String(" · ")
                                       + QString::fromStdString(
                                           sublayer.name);
        pwb::qgis::LayerBinding binding{name.toStdString(), "", "",
                                        sublayer.kind};
        std::string add_error;
        QgsMapLayer* layer = pwb::qgis::layer_factory::add_sublayer(
            context_.session().map(), sublayer, binding, &add_error);
        if (layer == nullptr) {
            if (first_error.empty()) first_error = add_error;
            continue;
        }
        if (auto* vector = qobject_cast<QgsVectorLayer*>(layer)) {
#ifdef PWB_WITH_CONV_27
            pwb::ui::layer_style::apply_style_sidecar(vector,
                                                      vector->source());
#endif
            // Module-only authority until a store binding exists (same
            // grant rule as openVectorLayer).
            pwb::application::DomainLayerFacts facts;
            facts.layer_id = name.toStdString();
            facts.role = "facies_boundary";
            facts.role_label = name.toStdString();
            facts.artifact_maturity = "draft";
            facts.write_granted = true;
            facts_[facts.layer_id] = facts;
            if (!context_.session().active_layer().has_value()) {
                context_.session().set_active_layer(facts);
                canvas_->setExtent(vector->extent());
            }
        } else if (!context_.session().active_layer().has_value()) {
            canvas_->setExtent(layer->extent());
        }
        ++added;
    }
    if (added == 0) {
        return QString::fromStdString(
            first_error.empty() ? "no layers could be added from " +
                                       path.toStdString()
                                : first_error);
    }
    if (!first_error.empty()) {
        // Partial success: surface what did not come in (same honesty
        // rule as openProject's per-layer failures), don't fail the whole
        // open over the layers that DID load.
        statusBar()->showMessage(
            tr("已加载 %1 层，但部分子层失败：%2")
                .arg(added)
                .arg(QString::fromStdString(first_error)),
            12000);
    }
    refreshActionStates();
    return QString();
}

void MainWindow::openVectorDialog() {
    const QString path = QFileDialog::getOpenFileName(
        this, tr("打开矢量图层"), QString(),
        QString::fromStdString(pwb::qgis::layer_factory::vector_file_filter()));
    if (path.isEmpty()) return;
    const QString error = openDataFile(path);
    if (!error.isEmpty()) {
        QMessageBox::warning(this, tr("打开矢量图层"), error);
    }
}

void MainWindow::openRasterDialog() {
    const QString path = QFileDialog::getOpenFileName(
        this, tr("打开栅格底图"), QString(),
        QString::fromStdString(pwb::qgis::layer_factory::raster_file_filter()));
    if (path.isEmpty()) return;
    const QString error = openDataFile(path);
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
#endif  // PWB_WITH_DATA_INTEGRATION
// (V14-THREE-STAGE-UX: this #endif was missing — the region stayed open
// and swallowed everything below, so noteDomainLayerFacts and the
// preview-settings definition compiled ONLY in data-integration builds.)

// --------------------------------------- cpp-close-12 shell actions ----
// The AppShell app-bar request surfaces (UI-17 deferred list) — the
// document-level bodies live in shell_project_actions.cpp; these handlers
// only add the window-level presentation (status bar / dialogs / sample
// project location policy).
#ifdef PWB_WITH_DATA_INTEGRATION
void MainWindow::saveProjectRequested() {
    QString saved_to;
    const QString error =
        shell_project_actions::save_open_project(*this, &saved_to);
    if (!error.isEmpty()) {
        // Same presentation contract as the other project dialogs: the
        // message carries the failure, the document stays untouched.
        QMessageBox::warning(this, tr("保存工程"), error);
        return;
    }
    statusBar()->showMessage(tr("工程已保存：%1").arg(saved_to), 10000);
}

void MainWindow::openSampleProjectRequested() {
    // Sample location policy: PALEO_SAMPLE_PROJECT_DIR overrides; default
    // is a per-user app-data location so the bootstrap is repeatable and
    // never writes into a repository checkout.
    const QByteArray override_dir = qgetenv("PALEO_SAMPLE_PROJECT_DIR");
    const QString sample_dir = !override_dir.isEmpty()
        ? QString::fromLocal8Bit(override_dir)
        : QStandardPaths::writableLocation(
              QStandardPaths::AppDataLocation);
    const QString error =
        shell_project_actions::bootstrap_sample_project(*this, sample_dir);
    if (!error.isEmpty()) {
        QMessageBox::warning(this, tr("打开样例工程"), error);
        return;
    }
    statusBar()->showMessage(tr("样例工程已就绪：%1").arg(sample_dir),
                             10000);
}

void MainWindow::showProjectProperties() {
    properties_responder_(
        shell_project_actions::project_properties_text(*this));
}
#endif  // PWB_WITH_DATA_INTEGRATION

void MainWindow::noteDomainLayerFacts(
    const pwb::application::DomainLayerFacts& facts) {
    facts_[facts.layer_id] = facts;
    // openProject parity: the first materialized layer becomes the active
    // session layer and frames the canvas (tool-policy gating and the
    // palette context derive from this state).
    if (!context_.session().active_layer().has_value()) {
        context_.session().set_active_layer(facts);
        if (QgsVectorLayer* layer =
                context_.session().map().vectorLayerById(facts.layer_id);
            layer != nullptr) {
            canvas_->setExtent(layer->extent());
        }
    }
    refreshActionStates();
}

#ifdef PWB_WITH_UI_PAGES_PREVIEW_QT
void MainWindow::showPreviewSettingsRequested() {
    // Store cached on the window (Python controller caches the dialog);
    // the UI-15 container is recreated per request with the current store
    // state and deletes on close. open(): window-modal without blocking
    // the GUI thread turn (offscreen-testable).
    if (preview_settings_store_ == nullptr) {
        preview_settings_store_ =
            std::make_unique<pwb::ui_pages_preview::PreviewSettingsStore>(
                services_settings_);
    }
    auto* dialog =
        new pwb::ui_canvas::PreviewSettingsDialog(this,
                                                  preview_settings_store_
                                                      .get());
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->set_settings(preview_settings_store_->load());
    dialog->open();
}
#endif  // PWB_WITH_UI_PAGES_PREVIEW_QT

// Declaration is data-integration-gated in the header (PwbDataStore
// surface); the definition matches (V14-THREE-STAGE-UX rebalance of the
// previously-dangling newProjectDialog region).
#ifdef PWB_WITH_DATA_INTEGRATION
QString MainWindow::newProject(const QString& dir_path,
                               const QString& name) {
    if (context_.session().store() != nullptr) {
        // Close-then-open parity with openProject (#1447).
        const QString close_error = closeProject();
        if (!close_error.isEmpty()) return close_error;
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
#endif  // PWB_WITH_DATA_INTEGRATION (newProject definition)

// Same closure as its declaration (the store/recovery types are
// data-integration surfaces).
#ifdef PWB_WITH_DATA_INTEGRATION
QString MainWindow::openProject(const QString& project_file) {
    if (context_.session().store() != nullptr) {
        // Close-then-open (#1447): switching projects stays in this
        // window — the dirty protection runs inside closeProject and a
        // cancelled/dirty-blocked close surfaces its own message.
        const QString close_error = closeProject();
        if (!close_error.isEmpty()) return close_error;
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
// BEGIN CLOSURE-MAPPING — rebind the preparation page + mapping document
// bank to the freshly opened project.
#ifdef PWB_WITH_CLOSURE_MAPPING
    pwb::app::closure_mapping::notify_project_changed(this);
#endif
// END CLOSURE-MAPPING
// BEGIN UI-14 WORKFLOW-WIRING — reopen the catalog rails + rebind the
// controller against the freshly opened project (after the mapping
// closure so the shared catalog instance already exists).
#ifdef PWB_WITH_WORKFLOW_WIRING
    pwb::app::workflow_wiring::notify_project_changed(this);
#endif
// END UI-14 WORKFLOW-WIRING
#ifdef PWB_WITH_APP_SHELL
    // Unbound project-gated commands (data.import / predict.run /
    // factor.compute / verify.run …) evaluate availability only when the
    // ribbon is asked to — after a project opens they stayed disabled with
    // the "需要先打开工程" tooltip until an unrelated context-group
    // injection happened to refresh them (review R2).
    if (app_shell_ != nullptr && app_shell_->ribbon() != nullptr) {
        app_shell_->ribbon()->refresh_command_availability();
    }
#endif

    // Materialize every bound GeoJSON layer as an explicit working copy —
    // the catalog payload file itself is read-only for the shell.
    auto snapshot = store->snapshot();
    if (!snapshot.is_ok()) {
        context_.session().set_store(nullptr);
        context_.setProjectStore(nullptr);
#ifdef PWB_WITH_CLOSURE_MAPPING
        pwb::app::closure_mapping::notify_project_changed(this);
#endif
#ifdef PWB_WITH_WORKFLOW_WIRING
        pwb::app::workflow_wiring::notify_project_changed(this);
#endif
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

    // One binding → one staged working copy: the legacy open path, and the
    // fallback for layers a .qgs restore could not bring back valid.
    // (The catalog payload file itself is read-only for the shell.)
    const auto stage_working_copy =
        [&](const pwb::workspace::LayerBinding& binding,
            std::filesystem::path* working_out) {
            const auto it = versions.find(binding.source_version_id);
            // Vector payloads this shell can edit as working copies
            // (staged export is GeoJSON either way).
            if (it == versions.end() || it->second == nullptr
                || it->second->trashed
                || (it->second->format != "GeoJSON"
                    && it->second->format != "GPKG")) {
                return false;
            }
            const std::filesystem::path payload =
                project_dir / it->second->path;
            std::error_code ec;
            if (!std::filesystem::exists(payload, ec)) {
                return false;
            }
            std::filesystem::create_directories(working_dir, ec);
            const std::filesystem::path working = working_dir
                / (binding.layer_id + payload.extension().string());
            std::filesystem::copy_file(
                payload, working,
                std::filesystem::copy_options::overwrite_existing, ec);
            if (ec) {
                if (first_error.empty()) {
                    first_error = "working copy create failed for "
                        + binding.layer_id + ": " + ec.message();
                }
                return false;
            }
            if (working_out != nullptr) *working_out = working;
            return true;
        };
    const auto materialize_binding =
        [&](const pwb::workspace::LayerBinding& binding) {
            std::filesystem::path working;
            if (!stage_working_copy(binding, &working)) return false;
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
                return false;
            }
            return true;
        };

    // QGIS-native open (data-management convergence): when the document
    // hands GIS state to the sibling .qgs file, QgsProject::read restores
    // layers/tree/CRS/style/view in one step — including the pwb/* join
    // keys, which ride along as layer custom properties. The Paleo
    // document only keeps the pointer plus the domain semantics.
    bool restored_from_qgs = false;
    pwb::domain::DiagnosticList workspace_diagnostics;
    const pwb::project::ProjectDocument& open_document = store->document();
    const pwb::workspace::MappingWorkspaceState workspace_state =
        pwb::workspace::MappingWorkspaceState::from_json(
            open_document.mapping_workspace(), workspace_diagnostics);
    if (!workspace_state.qgis_project_file.empty()) {
        const auto resolved = pwb::project::resolve_project_path(
            workspace_state.qgis_project_file, store->project_file());
        std::error_code exists_ec;
        if (resolved.is_ok()
            && std::filesystem::exists(
                   std::filesystem::path(resolved.value()), exists_ec)) {
            const pwb::qgis::map_project_store::RestoreReport restore =
                pwb::qgis::map_project_store::load(
                    context_.session().map(), resolved.value());
            if (restore.ok) {
                restored_from_qgs = true;
                for (const std::string& warning : restore.warnings) {
                    if (first_error.empty()) first_error = warning;
                }
            } else {
                // Honest degradation: fall back to binding materialization
                // below, but surface why the native restore was refused.
                if (first_error.empty()) first_error = restore.error;
            }
        }
        // A missing .qgs file likewise falls through to the legacy path —
        // the catalog bindings still describe every layer.
    }

    if (restored_from_qgs) {
        // Domain facts follow the BOUND restored layers only (join keys
        // persisted in the project XML; roles/maturity from the
        // memberships) — the same population rule as the legacy path.
        // Unbound layers (browser-opened rasters, science product
        // mirrors) stay out of the facts table exactly as before the
        // convergence; restored memory-provider shells carry no features
        // and are honestly reported below (QGIS persists their schema
        // only).
        for (const std::string& layer_id :
             context_.session().map().layerIdsTopFirst()) {
            QgsMapLayer* layer =
                context_.session().map().layerById(layer_id);
            if (layer == nullptr) continue;
            const pwb::workspace::LayerBinding* binding =
                pwb::workspace::membership(workspace_state, layer_id);
            if (binding == nullptr) {
                if (layer->providerType() == QLatin1String("memory")) {
                    if (first_error.empty()) {
                        first_error =
                            "memory layer '" + layer_id
                            + "' restored schema-only (features are not "
                              "persisted by the QGIS project format)";
                    }
                }
                continue;
            }
            pwb::application::DomainLayerFacts facts;
            facts.layer_id = layer_id;
            facts.role = !binding->role.empty() ? binding->role
                                                : "facies_boundary";
            facts.role_label = layer->name().toStdString();
            const auto maturity =
                workspace_state.artifact_maturity.find(layer_id);
            facts.artifact_maturity =
                maturity != workspace_state.artifact_maturity.end()
                    ? maturity->second
                    : "draft";
            // Same grant rule as both existing paths: the shell grants
            // writes on the layers it hosts (bound copies honor the
            // catalog's optimistic lock at commit time).
            facts.write_granted = true;
            facts_[layer_id] = facts;
            if (layer->isValid()) ++opened;
        }
        // Bindings whose layer did not come back (or came back invalid —
        // e.g. a deleted working copy) re-materialize from the catalog.
        // A restored-but-invalid shell keeps its tree node: the fresh
        // working copy is adopted as its new source (position/style
        // survive); an absent shell is added as a plain new layer.
        for (const pwb::workspace::LayerBinding& binding :
             snapshot.value().layer_bindings) {
            QgsMapLayer* layer =
                context_.session().map().layerById(binding.layer_id);
            if (layer != nullptr && layer->isValid()) continue;
            std::filesystem::path working;
            if (!stage_working_copy(binding, &working)) {
                ++skipped;  // absent shell or unrestorable payload
                continue;  // invalid shells stay + get surfaced (below)
            }
            if (layer != nullptr) {
                layer->setDataSource(
                    QString::fromStdString(working.string()),
                    QString::fromStdString(binding.layer_id), "ogr");
                if (layer->isValid()) {
                    pwb::qgis::LayerBinding qbinding{
                        binding.layer_id, binding.source_asset_id,
                        binding.source_version_id, "vector"};
                    pwb::qgis::layer_adapter::apply(layer, qbinding);
#ifdef PWB_WITH_CONV_27
                    pwb::ui::layer_style::apply_style_sidecar(
                        qobject_cast<QgsVectorLayer*>(layer),
                        layer->source());
#endif
                    ++opened;
                } else {
                    // Still broken after the re-point: honest skip, the
                    // provider error reaches the status surface.
                    ++skipped;
                }
            } else if (materialize_binding(binding)) {
                ++opened;
            } else {
                ++skipped;
            }
        }
        if (!context_.session().active_layer().has_value()) {
            // Tree-order first bound live layer (same shape as the legacy
            // path's first-materialized-layer default).
            for (const std::string& layer_id :
                 context_.session().map().layerIdsTopFirst()) {
                const auto it = facts_.find(layer_id);
                if (it != facts_.end()
                    && context_.session().map().layerById(layer_id) != nullptr) {
                    context_.session().set_active_layer(it->second);
                    break;
                }
            }
        }
    } else {
        for (const pwb::workspace::LayerBinding& binding :
             snapshot.value().layer_bindings) {
            if (!materialize_binding(binding)) {
                ++skipped;
                continue;
            }
            pwb::application::DomainLayerFacts facts;
            facts.layer_id = binding.layer_id;
            facts.role = binding.role.empty() ? "facies_boundary"
                                              : binding.role;
            facts.role_label = binding.layer_id;
            facts.artifact_maturity = "draft";
            // Working-copy grant: the bound catalog version authorizes
            // edits on the copy; the payload stays immutable.
            facts.write_granted = true;
            facts_[facts.layer_id] = facts;
            QgsMapLayer* layer =
                context_.session().map().layerById(binding.layer_id);
            if (!context_.session().active_layer().has_value()
                && layer != nullptr) {
                context_.session().set_active_layer(facts);
                canvas_->setExtent(layer->extent());
            }
            ++opened;
        }
    }
// BEGIN V14-QGIS-CONTROL
#ifdef PWB_WITH_CONV_27
    // Desired-tree reconcile + stage-view restore over the opened
    // project's live workspace state (QGIS stays the runtime authority;
    // the domain state is the persistence/semantics authority).
    applyLayerControlForOpen(restored_from_qgs);
#endif
// END V14-QGIS-CONTROL
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
    // A single-layer working-copy failure is PARTIAL: the store is bound
    // and most layers are live, so the rebind/restore tail below must
    // still run (the old early-return left a half-initialized session
    // that, with no close-project path, only a process restart could
    // recover from) (#1447). The failure is surfaced, not swallowed.
    if (!first_error.empty()) {
        statusBar()->showMessage(
            tr("工程已打开，但部分图层加载失败：%1")
                .arg(QString::fromStdString(first_error)),
            15000);
    }
    // Success: the project becomes the MRU head (native recent-projects).
    if (services_settings_ != nullptr) {
        pwb::platform_services::push_recent_project(*services_settings_,
                                                    project_file);
        refreshRecentProjects();
    }
// BEGIN PWB-V14-THREE-STAGE — the mapping stage follows the project
// document (mapping_workspace.current_stage; lenient fallback) and the
// selection bus rebinds to the fresh project token.
#ifdef PWB_WITH_STAGE_FLOW
    restoreStageFromProject();
#endif
// END PWB-V14-THREE-STAGE
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
// BEGIN JOINT-ANALYSIS flush/restore (same sidecar discipline as VIZ-B:
// flush the OLD project before rebinding directories — including the
// joint host's own QSettings scene state so click-added fences survive a
// window close, which previously only flushed on volume load/switch).
#if defined(PWB_WITH_GEO3D_VIZ)
    if (geo3d_dock_ != nullptr) {
        const QString geo3d_persist_error =
            geo3d_dock_->persist_project_workspace();
        if (!geo3d_persist_error.isEmpty()) {
            // #1457: a sidecar save failure on the switch path must be
            // visible — the old project's workspace state was NOT saved.
            statusBar()->showMessage(geo3d_persist_error, 10000);
        }
#ifdef PWB_WITH_UI_WELLSEIS
        if (geo3d_dock_->joint_host() != nullptr) {
            geo3d_dock_->joint_host()->save_state();
        }
#endif
    }
#endif
#ifdef PWB_WITH_JOINT_ANALYSIS
    if (app_shell_ != nullptr && app_shell_->geomodel_page() != nullptr) {
        app_shell_->geomodel_page()->save_joint_analysis_to_project();
    }
#endif
// END JOINT-ANALYSIS flush
// BEGIN CLOSURE-PREVIEW (task 04) — the data page re-reads the catalog
// from the CURRENT store (rows replaced, selection cleared on switch).
#if defined(PWB_WITH_CLOSURE_PREVIEW)
    pwb::closure_preview::notify_project_store_changed();
#endif
// END CLOSURE-PREVIEW
// BEGIN CLOSURE-JOINT3D
#if defined(PWB_WITH_GEO3D_VIZ) && defined(PWB_WITH_UI_WELLSEIS) && \
    defined(PWB_WITH_SEISMIC_SERVICE)
    if (geo3d_dock_ != nullptr && geo3d_dock_->joint_host() != nullptr &&
        seismic_volume_service_ != nullptr) {
        // 06 closure: the joint 3D host binds THIS project's real assets
        // (volume through the JobCenter; wells/TD parsed from catalog
        // entries). State (fences/slices) is project-scoped, so a switch
        // restores the new project's own scene.
        const pwb::app::closure_joint3d::BindOutcome bound =
            pwb::app::closure_joint3d::bind_project_assets(
                *geo3d_dock_->joint_host(), snapshot.value(), project_dir,
                project_file.toStdString());
        if (!bound.message.empty()) {
            statusBar()->showMessage(
                tr("联合3D：%1").arg(QString::fromStdString(bound.message)),
                8000);
        }
    }
#endif
// END CLOSURE-JOINT3D
// BEGIN JOINT-ANALYSIS restore — geo3d seven-key workspace sidecar +
// joint-analysis state sidecar for the NEW project.
#if defined(PWB_WITH_GEO3D_VIZ)
    if (geo3d_dock_ != nullptr) {
        geo3d_dock_->set_project_directory(
            QString::fromStdString(project_dir.string()));
        geo3d_dock_->restore_project_workspace();
    }
#endif
#ifdef PWB_WITH_JOINT_ANALYSIS
    if (app_shell_ != nullptr && app_shell_->geomodel_page() != nullptr) {
        joint_project_directory_ =
            QString::fromStdString(project_dir.string());
        auto* joint_page = app_shell_->geomodel_page();
        joint_page->set_project_path(joint_project_directory_);
        joint_project_slice_ = pwb::ui_wellseis::ProjectSlice{};
        joint_project_slice_.project_root = project_dir.string();
        joint_page->set_project(
            &joint_project_slice_,
            pwb::app::joint_analysis::load_stored(joint_project_directory_));
    }
#endif
// END JOINT-ANALYSIS restore
// BEGIN CLOSURE-REVIEW — the review page re-binds to the live document
// (project_bound + reports/documents/artifacts refresh). Placed on the
// SUCCESS tail only: every earlier failure return leaves the page in its
// pre-open state instead of a stale bound state.
#ifdef PWB_WITH_CLOSURE_REVIEW
    pwb::app::closure_review::notify_project_store_changed(app_shell_,
                                                           &context_);
#endif
// END CLOSURE-REVIEW
    return QString();
}
#endif  // PWB_WITH_DATA_INTEGRATION (openProject definition)

// Same closure as its declaration (store/recovery types are
// data-integration surfaces).
#ifdef PWB_WITH_DATA_INTEGRATION
QString MainWindow::closeProject() {
    if (context_.session().store() == nullptr) {
        return QString();  // idempotent: no project open
    }
    // Dirty protection — the SAME three-way decision as window close,
    // over every open edit session (not just the active layer).
    if (anyDirtyEditSession()) {
        const int choice = dirty_close_responder_();
        if (choice == QMessageBox::Cancel) {
            return tr("已取消关闭工程");
        }
        if (choice == QMessageBox::Save) {
            const std::filesystem::path staged_dir =
                std::filesystem::temp_directory_path() / "pwb-platform"
                                                       / "staged";
            const QString commit_error =
                commitAllDirtyLayers(staged_dir);
            if (!commit_error.isEmpty()) {
                return tr("保存失败（%1），工程未关闭").arg(commit_error);
            }
            // The document write: the staged edits only cover layer
            // payloads — the project document (constraint registrations,
            // workspace state, stratigraphy) needs its own save or the
            // close silently discards everything not yet flushed
            // (#1453).
            QString saved_to;
            const QString save_error =
                shell_project_actions::save_open_project(*this, &saved_to);
            if (!save_error.isEmpty()) {
                return tr("文档保存失败（%1），工程未关闭")
                    .arg(save_error);
            }
        } else {
            for (const std::string& layer_id :
                 context_.session().edit().editing_layer_ids()) {
                if (context_.session().edit().dirty(layer_id)) {
                    context_.session().edit().roll_back(layer_id);
                }
            }
        }
    }
// BEGIN VIZ-B
#ifdef PWB_WITH_VIZ_B
    if (viz_b_dock_ != nullptr) {
        viz_b_dock_->handle_project_closed();  // flush + drop late results
    }
#endif
// END VIZ-B
    // Roll back any surviving (clean) edit sessions, then drop every
    // layer from the map: the next open materializes the new project's
    // own bindings (no ghost layers across projects).
    for (const std::string& layer_id :
         context_.session().edit().editing_layer_ids()) {
        context_.session().edit().roll_back(layer_id);
    }
    if (QgsProject* project = context_.session().map().project()) {
        project->removeAllMapLayers();
    }
    context_.session().set_store(nullptr);
    context_.setProjectStore(nullptr);
    facts_.clear();
#ifdef PWB_WITH_APP_SHELL
    // Mirror of the open path (review R2): project-gated availability must
    // drop again once the project is closed, not stay stale-enabled.
    if (app_shell_ != nullptr && app_shell_->ribbon() != nullptr) {
        app_shell_->ribbon()->refresh_command_availability();
    }
#endif
// BEGIN CLOSURE-MAPPING
#ifdef PWB_WITH_CLOSURE_MAPPING
    pwb::app::closure_mapping::notify_project_changed(this);
#endif
// END CLOSURE-MAPPING
#if defined(PWB_WITH_CLOSURE_PREVIEW)
    pwb::closure_preview::notify_project_store_changed();
#endif
#ifdef PWB_WITH_CLOSURE_REVIEW
    pwb::app::closure_review::notify_project_store_changed(app_shell_,
                                                           &context_);
#endif
    refreshActionStates();
#ifdef PWB_WITH_CONV_27
    refresh_readiness();
#endif
    statusBar()->showMessage(tr("工程已关闭"), 8000);
    return QString();
}
#endif  // PWB_WITH_DATA_INTEGRATION (closeProject definition)

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
    // ALL open edit sessions, not just the active layer — switching the
    // active layer never stops another layer's session, and a dirty
    // non-active buffer used to be silently discarded here (#1447).
    for (const std::string& layer_id :
         context_.session().edit().editing_layer_ids()) {
        if (context_.session().edit().dirty(layer_id)) return true;
    }
    return false;
}

void MainWindow::closeEvent(QCloseEvent* event) {
    if (anyDirtyEditSession()) {
        const int choice = dirty_close_responder_();
        if (choice == QMessageBox::Cancel) {
            event->ignore();
            return;
        }
        if (choice == QMessageBox::Save) {
            // Commit EVERY dirty layer (the same three-way decision the
            // toggle path gives one layer); any failure cancels the close
            // so no edit is destroyed (#1447).
            const std::filesystem::path staged_dir =
                std::filesystem::temp_directory_path() / "pwb-platform" / "staged";
            for (const std::string& layer_id :
                 context_.session().edit().editing_layer_ids()) {
                if (!context_.session().edit().dirty(layer_id)) continue;
                std::string error;
                context_.session().stage_commit(layer_id, staged_dir, &error);
                if (!error.empty()) {
                    // Failed save must not destroy the edits: cancel the
                    // close. (Non-modal: a blocking dialog here is
                    // untestable offscreen; the open window carries it.)
                    statusBar()->showMessage(
                        tr("保存失败（%1），关闭已取消")
                            .arg(QString::fromStdString(error)),
                        10000);
                    event->ignore();
                    return;
                }
            }
            // The staged commits only cover layer payloads — the project
            // document (constraint registrations, workspace state,
            // stratigraphy) needs its own save or quitting silently
            // discards everything not yet flushed (same family as the
            // #1453 closeProject fix, which closeEvent never got).
#ifdef PWB_WITH_DATA_INTEGRATION
            {
                QString saved_to;
                const QString save_error =
                    shell_project_actions::save_open_project(*this, &saved_to);
                if (!save_error.isEmpty()) {
                    statusBar()->showMessage(
                        tr("文档保存失败（%1），关闭已取消").arg(save_error),
                        10000);
                    event->ignore();
                    return;
                }
            }
#endif
        } else {
            for (const std::string& layer_id :
                 context_.session().edit().editing_layer_ids()) {
                if (context_.session().edit().dirty(layer_id)) {
                    context_.session().edit().roll_back(layer_id);
                }
            }
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
// BEGIN JOINT-ANALYSIS close flush (same cancel-gate discipline).
#if defined(PWB_WITH_GEO3D_VIZ)
    if (geo3d_dock_ != nullptr) {
        const QString geo3d_persist_error =
            geo3d_dock_->persist_project_workspace();
        if (!geo3d_persist_error.isEmpty()) {
            // #1457: the window is about to die — the last visible
            // surface carries the failure (the state was not saved).
            statusBar()->showMessage(geo3d_persist_error, 10000);
        }
#ifdef PWB_WITH_UI_WELLSEIS
        if (geo3d_dock_->joint_host() != nullptr) {
            geo3d_dock_->joint_host()->save_state();
        }
#endif
    }
#endif
#ifdef PWB_WITH_JOINT_ANALYSIS
    if (app_shell_ != nullptr && app_shell_->geomodel_page() != nullptr) {
        app_shell_->geomodel_page()->save_joint_analysis_to_project();
    }
#endif
// END JOINT-ANALYSIS close flush
#ifdef PWB_WITH_CONV_30
    // CONV-30 — window close while a task runs: bounded cancel+wait for
    // every owned job (AppShell.shutdown_workers parity); a job that
    // refuses to cancel detaches to the process-lifetime keeper and keeps
    // running without the window (its GUI deliveries are dropped).
    // Joint host first (review R2): a pending #1471 reissue chain must
    // not resurrect a prep job after the owners were swept.
#if defined(PWB_WITH_GEO3D_VIZ) && defined(PWB_WITH_UI_WELLSEIS)
    if (geo3d_dock_ != nullptr &&
        geo3d_dock_->existing_joint_host() != nullptr) {
        geo3d_dock_->existing_joint_host()->shutdown(1000);
    }
#endif
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

#ifdef PWB_WITH_APP_SHELL
    converge_menus_into_ribbon();
#endif
}

#ifdef PWB_WITH_APP_SHELL
void MainWindow::converge_menus_into_ribbon() {
    if (ribbon_file_menu_ == nullptr || menuBar() == nullptr) return;
    auto* file = ribbon_file_menu_;
    QAction* exit_action =
        file->actions().isEmpty() ? nullptr : file->actions().last();
    // 退休菜单栏的顶层菜单（文件 除外——其项已在 Ribbon 文件菜单，
    // 且无快捷键的版本走同一槽函数）作为子菜单并入，低频命令不丢。
    for (QAction* top : menuBar()->actions()) {
        QMenu* menu = top->menu();
        if (menu == nullptr || menu->title() == tr("文件(&F)")) continue;
        file->insertMenu(exit_action, menu);
    }
    file->insertSeparator(exit_action);
    // 快捷键保全：带快捷键的动作挂到窗口本身 —— 菜单栏隐藏后 Qt 仍会
    // 派发 WindowContext 快捷键（挂在隐藏菜单/菜单栏上的动作不计）。
    for (QMenu* menu : findChildren<QMenu*>()) {
        for (QAction* action : menu->actions()) {
            if (action->menu() == nullptr && !action->shortcut().isEmpty()) {
                addAction(action);
            }
        }
    }
    menuBar()->hide();
}
#endif

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
    // M4 (R:20): both the native 文件 menu and the ribbon file button carry
    // the same MRU — one data source (the settings store), two views.
    const QStringList projects =
        services_settings_ == nullptr
            ? QStringList()
            : pwb::platform_services::load_recent_projects(*services_settings_);
    auto fill = [this, &projects](QMenu* menu) {
        if (menu == nullptr) return;
        menu->clear();
        if (projects.isEmpty()) {
            QAction* empty = menu->addAction(tr("(暂无最近工程)"));
            empty->setEnabled(false);
            return;
        }
        for (const QString& project : projects) {
            QAction* action = menu->addAction(project);
            connect(action, &QAction::triggered, this,
                    [this, project]() { openRecentProject(project); });
        }
        menu->addSeparator();
        menu->addAction(tr("清除最近工程"), this, [this]() {
            if (services_settings_ != nullptr) {
                pwb::platform_services::clear_recent_projects(
                    *services_settings_);
            }
            refreshRecentProjects();
        });
    };
    fill(recent_projects_menu_);
#ifdef PWB_WITH_APP_SHELL
    // M4: the ribbon file button carries the same MRU (one data source,
    // two views). Absent in reduced builds (no ribbon, no member).
    fill(ribbon_recent_menu_);
#endif
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
                if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
                    QMessageBox::warning(&dialog, tr("保存失败"),
                                         tr("无法写入文件"));
                    return;
                }
                // #1387: fail-closed — report short write / flush failure
                // instead of pretending the report was saved.
                const QByteArray bytes = view->toPlainText().toUtf8();
                if (file.write(bytes) != bytes.size() || !file.flush()) {
                    QMessageBox::warning(&dialog, tr("保存失败"),
                                         tr("无法写入文件"));
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
    // M3 (P0-1): the same LAS loads into the ws1 bottom 测井轨道 pane —
    // one file authority, a second VIEW of it (a pane failure is reported
    // on the status bar, never silently swallowed). The host is
    // moc-free — resolve through its QWidget identity + object name.
#ifdef PWB_WITH_APP_SHELL
    if (app_shell_ != nullptr) {
        QWidget* found = app_shell_->findChild<QWidget*>(
            QStringLiteral("WorkspaceWellPane"));
        auto* pane = static_cast<pwb::viz::WellLogHostWidget*>(
            found != nullptr && found != host ? found : nullptr);
        if (pane != nullptr) {
            QString pane_error;
            if (!pane->load_las(las_path, &pane_error)) {
                statusBar()->showMessage(
                    tr("底部测井窗格载入失败：%1")
                        .arg(pane_error.isEmpty() ? QStringLiteral("未知错误")
                                                  : pane_error),
                    8000);
            }
        }
    }
#endif  // PWB_WITH_APP_SHELL
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

QString MainWindow::commitAllDirtyLayers(
    const std::filesystem::path& staged_dir) {
    for (const std::string& layer_id :
         context_.session().edit().editing_layer_ids()) {
        if (!context_.session().edit().dirty(layer_id)) continue;
        std::string error;
        context_.session().stage_commit(layer_id, staged_dir, &error);
        if (!error.empty()) {
            // Keep the edits staged and stop on the first failure — the
            // caller must not save or close on this message.
            return QString::fromStdString(error);
        }
        // The commit rebinds the DOCUMENT membership to the new catalog
        // version; the live layer's join key must follow, or the next
        // .qgs save would pin a stale version id onto the layer.
        if (pwb::application::PwbDataStore* store =
                context_.projectStore().get()) {
            const pwb::workspace::LayerBinding* binding =
                store->binding_for(layer_id);
            QgsMapLayer* layer =
                context_.session().map().layerById(layer_id);
            if (binding != nullptr && layer != nullptr
                && !binding->source_version_id.empty()) {
                pwb::qgis::layer_adapter::apply(
                    layer,
                    pwb::qgis::LayerBinding{binding->layer_id,
                                            binding->source_asset_id,
                                            binding->source_version_id,
                                            "vector"});
            }
        }
    }
    return QString();
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

void MainWindow::routeVolumeToWorkspacePanes(
    const std::shared_ptr<pwb::viz::ISeismicVolume>& volume,
    const std::string& version_id) {
#ifdef PWB_WITH_APP_SHELL
    if (app_shell_ == nullptr || volume == nullptr) return;
    for (const char* name :
         {"WorkspaceSeismicPane", "ValidationSeismicPane"}) {
        // The slice widget is moc-free (Q_OBJECT assert) — resolve the
        // pane through its QWidget identity + object name, then cast.
        QWidget* found =
            app_shell_->findChild<QWidget*>(QString::fromLatin1(name));
        auto* pane =
            found != nullptr
                ? static_cast<pwb::seismic_viewer::SeismicSliceWidget*>(found)
                : nullptr;
        if (pane != nullptr && pane != slice_widget_) {
            pane->set_volume(volume,
                             pwb::seismic_viewer::VolumeIdentity{version_id, 0},
                             ++slice_revision_);
        }
    }
#else
    (void)volume;
    (void)version_id;
#endif  // PWB_WITH_APP_SHELL
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
            routeVolumeToWorkspacePanes(opened.volume, version_id);
            seismic_dock_->show();
            seismic_dock_->raise();
            statusBar()->showMessage(
                opened.descriptor.bin_grid.has_value()
                    ? tr("体版本已载入：%1（空间已标定；CRS 未绑定）")
                          .arg(QString::fromStdString(version_id))
                    : tr("体版本已载入：%1（无 bin-grid 标定）")
                          .arg(QString::fromStdString(version_id)),
                8000);
#if defined(PWB_WITH_GEO3D_VIZ) && defined(PWB_WITH_UI_WELLSEIS)
            // 06 closure: the same published volume feeds the joint 3D
            // host (its own JobCenter-backed open; survey + registration
            // rewire on arrival). The joint open captures its own fresh
            // service instance — the queued job then owns its lifetime
            // outright, independent of this window's member service.
            if (geo3d_dock_ != nullptr &&
                geo3d_dock_->joint_host() != nullptr) {
                auto joint_service =
                    std::make_shared<
                        pwb::seismic_service::SeismicVolumeService>();
                QString joint_error;
                geo3d_dock_->joint_host()->open_volume(
                    joint_service, payload_path, &joint_error);
            }
#endif
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
        routeVolumeToWorkspacePanes(volume, version_id);
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
    // read_segy (or the path ctor) throwing must still join the bridge: a
    // joinable std::thread destroyed during unwinding terminates the process
    // (#1451 B-10 family).
    pwb::job::ThreadJoinGuard bridge_guard{read_done, bridge};
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
        try {
            volume = pwb::seismic_io::read_segy(
                std::filesystem::path(path.toStdWString()), &read_error,
                cancel);
        } catch (const std::exception& ex) {
            read_error = ex.what();
        } catch (...) {
            read_error = "cancelled";
        }
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
        // Same exception-safety contract as the sync import path above.
        pwb::job::ThreadJoinGuard bridge_guard{read_done, bridge};
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
    // Removing layers (tree context-menu 移除组或图层) must retire the
    // domain facts too (#1451): a stale active entry kept every gated
    // tool reporting the misleading 图层源缺失（文件被移动或删除）
    // verdict until another layer was clicked.
    connect(context_.session().map().project(), &QgsProject::layersRemoved,
            this, [this](const QList<QString>& layer_ids) {
              (void)layer_ids;
              // Retire every fact whose layer no longer resolves in the
              // map, and clear the active selection if it was one of
              // them (#1451) — a stale active entry kept every gated
              // tool reporting the misleading 图层源缺失 verdict.
              bool active_removed = false;
              const auto active = context_.session().active_layer();
              for (auto it = facts_.begin(); it != facts_.end();) {
                if (context_.session().map().vectorLayerById(it->first)
                    == nullptr) {
                  if (active.has_value()
                      && active->layer_id == it->first) {
                    active_removed = true;
                  }
                  it = facts_.erase(it);
                } else {
                  ++it;
                }
              }
              if (active_removed) {
                context_.session().clear_active_layer();
              }
              refreshActionStates();
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
// BEGIN V14-QGIS-CONTROL
    // Layer-side stage policy: empty-group rematerialization + effective
    // group visibility + edit-target reassignment (instant, never
    // rewrites order — contracts 03 §6).
    if (layer_stage_ != nullptr) {
        layer_stage_->set_stage(*stage);
    }
// END V14-QGIS-CONTROL
    if (stage_dock_ != nullptr) stage_dock_->set_current_stage(*stage);
    refreshActionStates();
    refresh_readiness();
    // V14-THREE-STAGE-UX: every stage surface follows the authority —
    // the StageDock path (and any future writer) refreshes the flow
    // projection too (true-change contract makes the request_stage path's
    // extra refresh a no-op; no loop: refresh never writes the session).
#ifdef PWB_WITH_STAGE_FLOW
    if (stage_flow_ != nullptr) stage_flow_->refresh();
#endif
}

pwb::ui::ReadinessInputs MainWindow::readiness_inputs() const {
    pwb::ui::ReadinessInputs in;
    // CRS straight from the map authority.
    in.project_crs = context_.session().map().project()->crs().authid().toStdString();
    // Horizon: the store document's stratigraphy section when open.
    // 06 closure: this read goes through the CommitCoordinator's
    // serialization mutex (document_section) — a worker publish that
    // mutates the document can no longer tear the GUI's view (#1380
    // audit boundary; previously an unsynchronized document() read).
#ifdef PWB_WITH_DATA_INTEGRATION
    if (context_.projectStore() != nullptr) {
        const pwb::domain::Json stratigraphy =
            context_.projectStore()->coordinator().document_section(
                "stratigraphy", context_.projectStore()->document());
        if (stratigraphy.contains("target_horizon")) {
            const pwb::domain::Json& horizon = stratigraphy["target_horizon"];
            if (horizon.is_string()) {
                in.target_horizon = horizon.get<std::string>();
            }
        }
        const pwb::domain::Json workarea =
            context_.projectStore()->coordinator().document_section(
                "workarea", context_.projectStore()->document());
        if (workarea.contains("boundary")) {
            const pwb::domain::Json& boundary = workarea["boundary"];
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
    QgsMapLayer* layer =
        context_.session().map().layerById(active->layer_id);
    if (layer == nullptr) return;
    if (pwb::ui::layer_style::open_layer_properties(
            layer, canvas_, this)) {
        pwb::ui::layer_style::save_style_sidecar(layer, layer->source());
    }
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

// BEGIN V14-QGIS-CONTROL
#ifdef PWB_WITH_CONV_27
// Native layer control plane glue — see docs/development/
// qgis-v14-layer-control/02-architecture.md §D. The live workspace state
// is the single domain authority (loaded from the project document's
// mapping_workspace section, written back on save); QGIS stays the
// runtime tree authority through QgsLayerTreeStack.
void MainWindow::applyLayerControlForOpen(bool restored_from_qgis) {
    pwb::application::PwbDataStore* store = context_.projectStore().get();
    if (store == nullptr) {
        // Closed/no project: the workspace pointers from the previous
        // open are dangling — never leave them on the window.
        setProperty("pwb.layer_workspace", QVariant());
        setProperty("pwb.layer_groups", QVariant());
        return;
    }
    pwb::domain::DiagnosticList diagnostics;
    // Const read (the non-const mapping_workspace() would materialize an
    // empty section into the document on every open).
    const pwb::project::ProjectDocument& document = store->document();
    layer_workspace_ =
        std::make_unique<pwb::workspace::MappingWorkspaceState>(
            pwb::workspace::MappingWorkspaceState::from_json(
                document.mapping_workspace(), diagnostics));
    layer_tree_stack_ =
        std::make_unique<pwb::qgis::QgsLayerTreeStack>(
            context_.session().map());
    layer_groups_ =
        std::make_unique<pwb::ui_composite::LayerGroupController>(
            *layer_workspace_);
    layer_groups_->attach_stack(layer_tree_stack_.get());
    layer_stage_ =
        std::make_unique<pwb::ui_composite::LayerStageController>(
            *layer_workspace_, *layer_groups_);
    // Composition-root access (stage-action orchestration mutates the
    // SAME live state the save path persists — a second authority would
    // be clobbered by syncLayerControlOnSave). Same property pattern as
    // closure_factor_catalog: raw pointer rebound per project open.
    setProperty("pwb.layer_workspace",
                QVariant::fromValue(
                    static_cast<void*>(layer_workspace_.get())));
    setProperty("pwb.layer_groups",
                QVariant::fromValue(
                    static_cast<void*>(layer_groups_.get())));
    // Target model probes read the runtime map back (the canvas current
    // layer stays the fact; drift is reported, never papered over).
    layer_targets_ = std::make_unique<pwb::ui_composite::LayerTargets>();
    layer_targets_->set_probes(
        [this](const std::string& layer_id) {
            return context_.session().map().layerById(layer_id) != nullptr;
        },
        [this](const std::string& layer_id) {
            QgsVectorLayer* layer = context_.session().map().vectorLayerById(
                layer_id);
            return layer != nullptr && layer->isModified();
        },
        [this]() -> std::optional<std::string> {
            if (canvas_ == nullptr || canvas_->currentLayer() == nullptr) {
                return std::nullopt;
            }
            return std::optional<std::string>{
                pwb::qgis::layer_adapter::layer_id_of(
                    canvas_->currentLayer())};
        });
    // Composition snapshots come from the materialized working-copy
    // layers (facts_ holds the domain records of the open project).
    std::vector<pwb::ui_composite::LayerSnapshotInput> snapshots;
    snapshots.reserve(facts_.size());
    for (const auto& [layer_id, facts] : facts_) {
        pwb::ui_composite::LayerSnapshotInput input;
        input.id = layer_id;
        input.metadata["role"] = facts.role;
        input.metadata["maturity"] = facts.artifact_maturity;
        snapshots.push_back(std::move(input));
    }
    // Stage target resolution (V13 W-P order 2): first live layer of
    // each profile editing role, from the workspace memberships.
    layer_stage_->set_target_resolver(
        [this](const std::string& role) -> std::optional<std::string> {
            for (const std::string& layer_id :
                 pwb::workspace::layers_with_role(*layer_workspace_, role)) {
                if (context_.session().map().layerById(layer_id) != nullptr) {
                    return layer_id;
                }
            }
            return std::nullopt;
        });
    layer_stage_->set_target_validator(
        [this](const std::string& layer_id) {
            return context_.session().map().layerById(layer_id) != nullptr;
        });
    layer_snapshots_ = snapshots;
    // Partial composition (catalog-bound working copies only): ghost
    // cleanup must NOT run — an absent layer here is not evidence of
    // deletion (destructive-purge guard; contracts 03 §7).
    layer_groups_->ensure_memberships(snapshots, /*full_composition=*/false);
    try {
        if (restored_from_qgis) {
            // .qgs-restored tree: ADOPT the runtime structure (same
            // observation the save path uses for user edits) — placements
            // and order keys follow the QGIS authority instead of a
            // persisted desired tree, which the document no longer keeps.
            layer_groups_->observe_tree_nodes(
                layer_tree_stack_->tree_snapshot_nodes());
        } else {
            // Host guard (02-architecture §5): an applier throw must not
            // escape openProject — the plane degrades, the open proceeds.
            layer_groups_->reconcile(snapshots);
        }
    } catch (const std::exception& exc) {
        // Degrade, but TELL the user (N8: the comment promised a status
        // surface note that was never emitted — silent degradation).
        statusBar()->showMessage(
            tr("图层分组同步失败（%1），将继续重试")
                .arg(QString::fromStdString(exc.what())),
            10000);
    }
    // Drop targets referencing layers the runtime does not have (report
    // only — a fresh open cannot have dirty sessions yet).
    layer_targets_->revalidate();
    layer_stage_->restore_stage_view();
    // Row status language (contracts 03 §9): binding/freshness/target
    // projection for the panel chips + tooltips.
    for (auto& [layer_id, facts] : facts_) {
        pwb::ui_composite::LayerRowInputs inputs;
        inputs.layer_id = layer_id;
        const pwb::workspace::LayerBinding* binding =
            pwb::workspace::membership(*layer_workspace_, layer_id);
        inputs.binding = binding;
        inputs.is_active =
            layer_stage_->active_target_layer_id().has_value() &&
            *layer_stage_->active_target_layer_id() == layer_id;
        inputs.is_locked = facts.frozen || facts.stage_locked;
        facts.status_flags = [&] {
            const auto status =
                pwb::ui_composite::build_layer_row_status(inputs);
            return status.flags;
        }();
        facts.status_summary =
            pwb::ui_composite::layer_row_summary(inputs);
    }
    if (layer_panel_ != nullptr) layer_panel_->refresh_indicators();
}

QString MainWindow::persistQgisProjectOnSave() {
#ifdef PWB_WITH_DATA_INTEGRATION
    pwb::application::PwbDataStore* store = context_.projectStore().get();
    if (store == nullptr) return QString();  // no project: nothing to hand off
    const std::filesystem::path qgs = std::filesystem::path(
        pwb::qgis::map_project_store::default_qgs_path(
            store->project_file().string()));
    // QGIS state first: a failed QgsProject::write aborts the whole save
    // (the caller surfaces the error) — never a half-success where the
    // document points at a QGIS project that was not written.
    std::string error;
    if (!pwb::qgis::map_project_store::save(context_.session().map(),
                                            qgs.string(), &error)) {
        return QString::fromStdString(error);
    }
    // Record the handoff pointer (portable relative form, the convention
    // every other project-internal path uses). From this save on, the
    // workspace codec stops duplicating the GIS tree into the document.
    const std::string stored =
        pwb::project::relativize_path(qgs, store->project_file()).stored;
#ifdef PWB_WITH_CONV_27
    if (layer_workspace_ != nullptr) {
        layer_workspace_->qgis_project_file = stored;
    } else
#endif
    {
        pwb::domain::DiagnosticList diagnostics;
        pwb::workspace::MappingWorkspaceState state =
            pwb::workspace::MappingWorkspaceState::from_json(
                store->document().mapping_workspace(), diagnostics);
        state.qgis_project_file = stored;
        pwb::workspace::write_mapping_workspace(store->document().root(),
                                                state);
    }
#endif  // PWB_WITH_DATA_INTEGRATION
    return QString();
}

void MainWindow::syncLayerControlOnSave() {
    if (layer_workspace_ == nullptr) return;
    pwb::application::PwbDataStore* store = context_.projectStore().get();
    if (store == nullptr) return;
    // Adopt user tree-structure edits (drag / group moves) observed on
    // the QGIS tree, then RE-RECONCILE so the adopted structure reaches
    // state.tree (observe alone only updates the runtime placement
    // tables; only reconcile persists the tree — Round-2 review P1-1).
    // The re-reconcile diffs against the already-observed tree, so it
    // applies zero structural ops and just rewrites the desired-tree
    // payload. An illegal placement is rejected by the same
    // role-routing validation (desired tree unchanged). Real-time
    // model-signal write-back remains the Prompt-2 integration point
    // (08 §2).
    if (layer_tree_stack_ != nullptr && layer_groups_ != nullptr) {
        if (layer_groups_->observe_tree_nodes(
                layer_tree_stack_->tree_snapshot_nodes()) &&
            !layer_snapshots_.empty()) {
            try {
                // No force: the diff runs against the pre-drag baseline
                // and emits exactly the user's minimal move set.
                layer_groups_->reconcile(layer_snapshots_);
            } catch (const std::exception& exc) {
                // Save proceeds with the last persisted tree; the next
                // successful reconcile re-syncs it. Report the degraded
                // state instead of staying silent (N8).
                statusBar()->showMessage(
                    tr("图层分组同步失败（%1），已按上次持久化结果保存")
                        .arg(QString::fromStdString(exc.what())),
                    10000);
            }
        }
    }
    // Persist the desired tree / memberships / stage view states into
    // the project document (additive section rewrite; the store saves
    // right after through ProjectManager).
    pwb::workspace::write_mapping_workspace(store->document().root(),
                                            *layer_workspace_);
}
#endif
// END V14-QGIS-CONTROL

}  // namespace pwb::app
