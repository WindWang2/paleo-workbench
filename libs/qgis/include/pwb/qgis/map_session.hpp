#pragma once

// MapSession — session-owned QgsProject + canvas + layer tree (CPP-A
// contract §2). One authoritative project per session; no boundary-less
// singletons. Qt widgets are parented into the caller's widget tree; this
// class only tracks them (QPointer) to enforce the teardown order:
// tool → canvas layers cleared → canvas detached → layers removed → project.

#include <memory>
#include <string>
#include <vector>

#include <QPointer>

#include <pwb/qgis/layer_adapter.hpp>

class QgsMapCanvas;
class QgsLayerTreeView;
class QgsProject;
class QgsVectorLayer;
class QgsRasterLayer;
class QgsMapLayer;
class QWidget;

namespace pwb::qgis {

struct LayerBinding;  // from layer_adapter.hpp (re-exported there)

class MapSession {
public:
    MapSession();
    ~MapSession();

    MapSession(const MapSession&) = delete;
    MapSession& operator=(const MapSession&) = delete;

    // Widget factories: the caller gives the Qt parent (MainWindow/dock).
    // The session records the widget for ordered teardown only.
    QgsMapCanvas* createCanvas(QWidget* parent);
    QgsLayerTreeView* createLayerTree(QWidget* parent);

    QgsProject* project() const { return project_.get(); }

    // Layer admission with domain join key (pwb/layer_id ...). Returns
    // nullptr + diagnostic on provider failure — never a fake success.
    QgsVectorLayer* addVectorLayer(const std::string& uri,
                                   const std::string& name,
                                   const LayerBinding& binding,
                                   std::string* error);
    QgsRasterLayer* addRasterLayer(const std::string& uri,
                                   const std::string& name,
                                   const LayerBinding& binding,
                                   std::string* error);

    // Domain-id addressed lookup (join key authority).
    QgsMapLayer* layerById(const std::string& layer_id) const;
    QgsVectorLayer* vectorLayerById(const std::string& layer_id) const;
    std::vector<std::string> layerIdsTopFirst() const;

    // CONV-29: screen-state snapshot for export parity. Shape:
    // {"extent":[xmin,ymin,xmax,ymax]|null, "crs": authid,
    //  "layers":[{"id","visible"}...] (top-first), "grid": false,
    //  "legend": <has an on-screen layer tree>}.
    // Extent comes from the first live canvas, else the visible spatial
    // layer union transformed into the project CRS; null when neither
    // exists. "grid": false — the plain QgsMapCanvas draws no grid overlay.
    std::string canvas_state_json() const;

    // Canvas helpers.
    void setDestinationCrs(const std::string& auth_id, std::string* error);
    void refreshCanvases();
    void zoomToFullExtent(QgsMapCanvas* canvas);

    // BEGIN V14-QGIS-CONTROL
    // Live canvases for the layer-tree stack's transaction window
    // (render suppression during the batch, single deferred sync at
    // close).
    std::vector<QgsMapCanvas*> canvases() const;
    // END V14-QGIS-CONTROL

    // Ordered teardown, also invoked by the destructor.
    void close();

private:
    void syncCanvasLayers();

    std::unique_ptr<QgsProject> project_;
    std::vector<QPointer<QgsMapCanvas>> canvases_;
    std::vector<QPointer<QgsLayerTreeView>> trees_;
    bool closed_ = false;
};

}  // namespace pwb::qgis
