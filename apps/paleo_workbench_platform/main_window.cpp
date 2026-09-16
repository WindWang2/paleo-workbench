#include "main_window.hpp"

#include <QDockWidget>
#include <QLabel>
#include <QStatusBar>
#include <QToolBar>

#include <qgslayertreeview.h>
#include <qgsmapcanvas.h>

#include <pwb/qgis/qgis_runtime.hpp>

namespace pwb::app {

MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent) {
    session_ = std::make_unique<pwb::application::ProjectSession>();
    buildUi();
    buildToolbar();
    setWindowTitle(tr("Paleo Workbench Platform (C++/QGIS)"));
    resize(1280, 800);
}

MainWindow::~MainWindow() = default;

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
}

void MainWindow::buildToolbar() {
    auto* toolbar = addToolBar(tr("地图工具"));
    toolbar->setObjectName(QStringLiteral("map-toolbar"));
    // Toolbar items are added on refreshActionStates from the policy
    // verdicts; no gate logic is embedded here.
    refreshActionStates();
}

void MainWindow::refreshActionStates() {
    const auto availability = pwb::tool_policy::evaluate_all(session_->snapshot());
    actions_.apply(availability);
    QString summary;
    int enabled = 0;
    for (const auto& [id, verdict] : availability) {
        if (verdict.enabled) ++enabled;
    }
    summary = tr("工具可用 %1/%2").arg(enabled).arg(availability.size());
    if (status_label_ != nullptr) status_label_->setText(summary);
}

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
    session_->set_active_layer(facts);
    map.setDestinationCrs("EPSG:4326", &error);
    if (!error.empty()) return QString::fromStdString(error);
    map.zoomToFullExtent(canvas_);
    refreshActionStates();
    return QString();
}

void MainWindow::closeEvent(QCloseEvent* event) {
    // Contract teardown order: session (edit -> canvas detach -> layers ->
    // project) before widget children die with the window.
    session_->close();
    QMainWindow::closeEvent(event);
}

}  // namespace pwb::app
