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

#include <pwb/qgis/layout_service.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

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

}  // namespace pwb::app
