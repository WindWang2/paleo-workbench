#include "main_window.hpp"

#include <QDockWidget>
#include <QFileDialog>
#include <QFileInfo>
#include <QItemSelectionModel>
#include <QLabel>
#include <QMenuBar>
#include <QMessageBox>
#include <QStatusBar>
#include <QToolBar>

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

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/qgis/layout_service.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
#include <pwb/seismic_attributes/attributes.hpp>
#endif

#ifdef PWB_WITH_WELL_LOG
#include <pwb/viz/well_log_host_widget.hpp>
#endif

namespace pwb::app {
namespace {
QString layerLabelFor(const pwb::application::DomainLayerFacts& facts) {
    if (!facts.role_label.empty()) {
        return QString::fromStdString(facts.role_label);
    }
    return QString::fromStdString(facts.layer_id);
}
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


MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent) {
    session_ = std::make_unique<pwb::application::ProjectSession>();
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
    // The app is the composition root: E's contract has the host register
    // explicitly (no static auto-registration into a shared registry).
    attribute_runner_ = std::make_unique<pwb::application::AlgorithmRunner>();
    const std::string rejections[] = {
        attribute_runner_->register_kernel(
            pwb::seismic_attributes::make_envelope("pwb-platform")),
        attribute_runner_->register_kernel(
            pwb::seismic_attributes::make_instantaneous_phase("pwb-platform")),
        attribute_runner_->register_kernel(
            pwb::seismic_attributes::make_instantaneous_frequency(
                "pwb-platform")),
        attribute_runner_->register_kernel(
            pwb::seismic_attributes::make_rms_amplitude("pwb-platform")),
    };
    for (const std::string& rejection : rejections) {
        if (!rejection.empty()) {
            qWarning("attribute kernel registration: %s", rejection.c_str());
        }
    }
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
}

MainWindow::~MainWindow() {
    // Ordered teardown must run while every member the signal paths touch
    // (actions_, status label, canvas) is still alive: member destruction
    // order would otherwise kill the action set before the session, and
    // MapSession::close() -> unsetMapTool -> mapToolSet -> refresh would
    // use the destroyed members (observed as a segfault in the integrated
    // build). ProjectSession::close()/MapSession::close() are idempotent
    // when closeEvent already ran.
    if (session_ != nullptr) session_->close();
}

void MainWindow::buildUi() {
    canvas_ = session_->map().createCanvas(this);
    setCentralWidget(canvas_);
    session_->attachCanvas(canvas_);

    auto* dock = new QDockWidget(tr("图层"), this);
    dock->setObjectName(QStringLiteral("layer-tree-dock"));
    tree_ = session_->map().createLayerTree(dock);
    dock->setWidget(tree_);
    addDockWidget(Qt::LeftDockWidgetArea, dock);

    status_label_ = new QLabel(QStringLiteral("ready"), this);
    statusBar()->addWidget(status_label_);

#ifdef PWB_WITH_WELL_LOG
    // C's WLE-backed well-log host in a dock (same Qt ABI, one process;
    // no Python). Same-session ownership: dies with the window.
    auto* well_log_dock = new QDockWidget(tr("测井"), this);
    well_log_dock->setObjectName(QStringLiteral("well-log-dock"));
    auto* well_log_host = new pwb::viz::WellLogHostWidget(well_log_dock);
    well_log_dock->setWidget(well_log_host);
    addDockWidget(Qt::RightDockWidgetArea, well_log_dock);
#endif
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
    // D's slice host in a dock (moc-free widget like the WLE host).
    seismic_dock_ = new QDockWidget(tr("地震视图"), this);
    seismic_dock_->setObjectName(QStringLiteral("seismic-dock"));
    slice_widget_ = new pwb::seismic_viewer::SeismicSliceWidget(seismic_dock_);
    seismic_dock_->setWidget(slice_widget_);
    addDockWidget(Qt::RightDockWidgetArea, seismic_dock_);
#endif

    // Tools are canvas-parented; MapSession teardown unsets them first.
    pan_tool_ = new QgsMapToolPan(canvas_);
    zoom_in_tool_ = new QgsMapToolZoom(canvas_, false);
    zoom_out_tool_ = new QgsMapToolZoom(canvas_, true);
    vertex_tool_ = new VertexMoveMapTool(canvas_, this);
    canvas_->setMapTool(pan_tool_);
    session_->set_current_tool("pan");

    connect(canvas_, &QgsMapCanvas::mapToolSet, this,
            [this]() { onCanvasMapToolChanged(); });
    connect(tree_->selectionModel(), &QItemSelectionModel::currentChanged, this,
            [this]() { onActiveLayerChanged(); });
}

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
    };

    refreshActionStates();  // materializes one QAction per tool id
    for (const Wire& wire : wired) {
        QAction* action = actions_.action(wire.id);
        if (action == nullptr) continue;   // vocabulary drift: keep honest
        action->setText(tr(wire.text));
        if (!wire.shortcut.isEmpty()) action->setShortcut(wire.shortcut);
    }

    QMenu* file_menu = menuBar()->addMenu(tr("文件(&F)"));
    file_menu->addAction(tr("打开工程…"), this,
                         &MainWindow::openProjectDialog, QKeySequence::Open);
    file_menu->addAction(actions_.action("reference_import"));
    file_menu->addAction(actions_.action("layer_new"));
    file_menu->addSeparator();
    file_menu->addAction(actions_.action("map_export"));
    file_menu->addSeparator();
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

#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_SEISMIC_ATTRIBUTES) \
    && defined(PWB_WITH_DATA_INTEGRATION)
    QMenu* seismic_menu = menuBar()->addMenu(tr("地震(&S)"));
    seismic_menu->addAction(tr("计算属性…"), this,
                            &MainWindow::runAttributeDialog,
                            QKeySequence(Qt::CTRL | Qt::Key_U));
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
}

void MainWindow::refreshActionStates() {
    const auto availability = pwb::tool_policy::evaluate_all(session_->snapshot());
    actions_.apply(availability);
    setStatusFromPolicy(availability);
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
    QgsVectorLayer* layer = session_->map().addVectorLayer(
        path.toStdString(), layer_id.toStdString(), binding, &error);
    if (layer == nullptr) return QString::fromStdString(error);

    pwb::application::DomainLayerFacts facts;
    facts.layer_id = layer_id.toStdString();
    facts.role = "facies_boundary";
    facts.role_label = layer_id.toStdString();
    facts.artifact_maturity = "draft";
    // Module-only authority: layers this shell opens itself are granted
    // write here; once B bindings exist the store becomes the authority.
    facts.write_granted = true;
    facts_[facts.layer_id] = facts;
    session_->set_active_layer(facts);
    canvas_->setExtent(layer->extent());
    refreshActionStates();
    return QString();
}

QString MainWindow::openRasterLayer(const QString& path) {
    const QString layer_id = QFileInfo(path).completeBaseName();
    pwb::qgis::LayerBinding binding{
        layer_id.toStdString(), "", "", "raster"};
    std::string error;
    QgsRasterLayer* layer = session_->map().addRasterLayer(
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

QString MainWindow::openProject(const QString& project_file) {
    if (session_->store() != nullptr) {
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

    session_->set_store(store);
    project_store_ = store;

    // Materialize every bound GeoJSON layer as an explicit working copy —
    // the catalog payload file itself is read-only for the shell.
    auto snapshot = store->snapshot();
    if (!snapshot.is_ok()) {
        session_->set_store(nullptr);
        project_store_ = nullptr;
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
        if (it == versions.end() || it->second == nullptr
            || it->second->format != "GeoJSON" || it->second->trashed) {
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
        const std::filesystem::path working =
            working_dir / (binding.layer_id + ".geojson");
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
        QgsVectorLayer* layer = session_->map().addVectorLayer(
            working.string(), binding.layer_id, qbinding, &add_error);
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
        if (!session_->active_layer().has_value()) {
            session_->set_active_layer(facts);
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
    return QString();
}

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
    session_->map().zoomToFullExtent(canvas_);
    refreshActionStates();
}

void MainWindow::refreshMap() {
    session_->map().refreshCanvases();
    refreshActionStates();
}

void MainWindow::toggleEditing() {
    const auto active = session_->active_layer();
    if (!active.has_value()) return;
    const std::string id = active->layer_id;
    if (session_->edit().editing(id)) {
        if (session_->edit().dirty(id)) {
            // Stop with pending edits goes through the same three-way
            // decision as dirty-close (no silent discard).
            const int choice = dirty_close_responder_();
            if (choice == QMessageBox::Cancel) return;
            if (choice == QMessageBox::Save) { saveEdits(); return; }
            rollBackEdits();
            return;
        }
        session_->edit().roll_back(id);
    } else {
        const std::string error = session_->edit().start_editing(id);
        if (!error.empty()) {
            QMessageBox::warning(this, tr("开始编辑"), QString::fromStdString(error));
        }
    }
    refreshActionStates();
}

void MainWindow::saveEdits() {
    const auto active = session_->active_layer();
    if (!active.has_value() || !session_->edit().editing(active->layer_id)) return;
    const std::filesystem::path staged_dir =
        std::filesystem::temp_directory_path() / "pwb-platform" / "staged";
    std::string error;
    const pwb::qgis::StagedAsset staged =
        session_->stage_commit(active->layer_id, staged_dir, &error);
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
    const auto active = session_->active_layer();
    if (!active.has_value()) return;
    if (session_->edit().dirty(active->layer_id)) {
        if (discard_confirm_responder_() != QMessageBox::Yes) return;
    }
    session_->edit().roll_back(active->layer_id);
    refreshActionStates();
}

void MainWindow::undoEdition() {
    const auto active = session_->active_layer();
    if (!active.has_value()) return;
    session_->edit().undo(active->layer_id);
    refreshActionStates();
}

void MainWindow::redoEdition() {
    const auto active = session_->active_layer();
    if (!active.has_value()) return;
    session_->edit().redo(active->layer_id);
    refreshActionStates();
}

void MainWindow::exportLayoutDialog() {
    const QString path = QFileDialog::getSaveFileName(
        this, tr("导出布局"), QString(),
        tr("PNG 图像 (*.png);;PDF 文档 (*.pdf);;SVG 矢量 (*.svg)"));
    if (path.isEmpty()) return;
    const QString suffix = QFileInfo(path).suffix().toLower();
    pwb::qgis::LayoutService layouts(session_->map());
    pwb::qgis::LayoutSpec spec;
    const std::string error = layouts.export_layout(
        spec, std::filesystem::path(path.toStdWString()),
        suffix.toStdString(), 96.0);
    if (!error.empty()) {
        QMessageBox::warning(this, tr("导出布局"), QString::fromStdString(error));
    } else {
        statusBar()->showMessage(tr("已导出: %1").arg(path), 8000);
    }
}

// ------------------------------------------------------------ reactions ----

void MainWindow::onCanvasMapToolChanged() {
    const QgsMapTool* tool = canvas_->mapTool();
    std::string tool_id = "unknown";
    if (tool == pan_tool_) tool_id = "pan";
    else if (tool == zoom_in_tool_) tool_id = "zoom_in";
    else if (tool == zoom_out_tool_) tool_id = "zoom_out";
    else if (tool == vertex_tool_) tool_id = "vertex";
    session_->set_current_tool(tool_id);
    refreshActionStates();
}

void MainWindow::onActiveLayerChanged() {
    const QModelIndex current = tree_->currentIndex();
    if (!current.isValid()) return;
    // Map the tree row back to a domain layer id via the join key.
    const auto layers = session_->map().layerIdsTopFirst();
    const int row = current.row();
    if (row < 0 || static_cast<size_t>(row) >= layers.size()) return;
    const std::string layer_id = layers[static_cast<size_t>(row)];
    const auto it = facts_.find(layer_id);
    if (it == facts_.end()) return;
    session_->set_active_layer(it->second);
    refreshActionStates();
}

// ---------------------------------------------------------------- close ----

bool MainWindow::anyDirtyEditSession() const {
    const auto active = session_->active_layer();
    return active.has_value() && session_->edit().editing(active->layer_id)
        && session_->edit().dirty(active->layer_id);
}

void MainWindow::closeEvent(QCloseEvent* event) {
    if (anyDirtyEditSession()) {
        const int choice = dirty_close_responder_();
        if (choice == QMessageBox::Cancel) {
            event->ignore();
            return;
        }
        if (choice == QMessageBox::Save) {
            const auto active = session_->active_layer();
            const std::filesystem::path staged_dir =
                std::filesystem::temp_directory_path() / "pwb-platform" / "staged";
            std::string error;
            session_->stage_commit(active->layer_id, staged_dir, &error);
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
            const auto active = session_->active_layer();
            if (active.has_value()) session_->edit().roll_back(active->layer_id);
        }
    }
    // Contract teardown order: session (edit -> canvas detach -> layers ->
    // project) before widget children die with the window.
    session_->close();
    QMainWindow::closeEvent(event);
}

// ------------------------------------------------------------ fixtures ----

QString MainWindow::loadFixtures(const QString& vector_uri,
                                 const QString& raster_uri) {
    const pwb::qgis::LayerBinding vector_binding{
        "fixture.facies_boundary", "asset-fixture-1", "version-1", "vector"};
    std::string error;
    pwb::qgis::MapSession& map = session_->map();
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
    session_->set_active_layer(facts);
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
    const auto active = session_->active_layer();
    if (!active.has_value()) return QStringLiteral("no active layer");
    std::string error;
    session_->stage_commit(active->layer_id, staged_dir, &error);
    return QString::fromStdString(error);
}

#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
std::vector<std::string> MainWindow::volumeVersionIds() const {
    std::vector<std::string> ids;
    if (project_store_ == nullptr) return ids;
    auto snapshot = project_store_->snapshot();
    if (!snapshot.is_ok()) return ids;
    for (const auto& version : snapshot.value().catalog_versions) {
        if (version.format == "PWBVOL1" && !version.trashed) {
            ids.push_back(version.id.str());
        }
    }
    return ids;
}

QString MainWindow::openVolumeVersion(const std::string& version_id) {
    if (project_store_ == nullptr) return tr("未打开工程");
    auto snapshot = project_store_->snapshot();
    if (!snapshot.is_ok()) {
        return QString::fromStdString(snapshot.error().message);
    }
    const std::filesystem::path project_dir =
        project_store_->project_file().parent_path();
    for (const auto& version : snapshot.value().catalog_versions) {
        if (version.id.str() != version_id || version.format != "PWBVOL1") {
            continue;
        }
        pwb::application::VolumePayload payload;
        const std::string read_error = pwb::application::read_volume_payload(
            project_dir / version.path, &payload);
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
    if (attribute_runner_ == nullptr) {
        if (error != nullptr) *error = "attribute runner unavailable";
        return "";
    }
    return attribute_runner_->submit(project_store_, algorithm_id, params,
                                     input_version_id, error);
}

pwb::application::AlgorithmRunner::Outcome MainWindow::attributeOutcome(
    const std::string& request_id) {
    if (attribute_runner_ == nullptr) return {};
    return attribute_runner_->outcome(request_id);
}

void MainWindow::runAttributeDialog() {
    if (project_store_ == nullptr) {
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
    for (const auto& info : attribute_runner_->algorithms()) {
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

    auto* form = new QFormLayout;
    form->addRow(tr("算法"), algorithm);
    form->addRow(tr("输入体版本"), input);
    form->addRow(tr("窗口（RMS）"), window);
    form->addRow(tr("采样间隔（瞬时频率）"), sample_interval);
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
    } else if (algorithm_id == "seismic.instantaneous_frequency") {
        params["sample_interval"] = std::to_string(
            sample_interval->value());
    }

    std::string error;
    const std::string request_id =
        runAttribute(algorithm_id, params, input_version, &error);
    if (request_id.empty()) {
        QMessageBox::warning(this, tr("计算属性"),
                             QString::fromStdString(error));
        return;
    }

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
}
#endif

}  // namespace pwb::app
