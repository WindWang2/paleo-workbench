#pragma once

// UI-02 — QGIS widget hosts + viewport/tree helpers, ported from
// paleo_workbench/ui/qgis_stack/widgets.py.
//
// The Python module exists to cross the PySide/shiboken address
// boundary: the bridge hands back raw widget addresses that get
// wrapped as QWidgets. In the native port the boundary is gone —
// pwb::qgis::MapSession creates real QgsMapCanvas / QgsLayerTreeView
// objects directly; these classes keep the host layout + helper API
// contract the callers use.

#include <QWidget>

class QgsMapCanvas;
class QgsLayerTreeView;
class QVBoxLayout;

namespace pwb::qgis {
class MapSession;
}

namespace pwb::ui_widgets::qgis {

// The canvas viewport — where QgsMapCanvas (a QGraphicsView) delivers
// mouse events and where chrome overlays parent themselves.
QWidget* canvas_viewport(QgsMapCanvas* canvas);

// Expand arrows + decorations + branch icons on the layer tree
// (configure_layer_tree_view parity): decorated root, expandable items,
// expand-on-double-click, 20px indent, map branch QSS, expand all.
void configure_layer_tree_view(QgsLayerTreeView* view);

// Host widget embedding a session-owned QgsMapCanvas in a Qt layout
// (the Python QgisCanvasHost contract; the address is the canvas
// pointer — kept only for diagnostics parity, never dereferenced).
class QgisCanvasHost : public QWidget {
    Q_OBJECT
public:
    QgisCanvasHost(pwb::qgis::MapSession& session,
                   QWidget* parent = nullptr);

    QgsMapCanvas* canvas() const { return canvas_; }
    quintptr canvas_address() const {
        return reinterpret_cast<quintptr>(canvas_);
    }

private:
    QgsMapCanvas* canvas_ = nullptr;  // session-owned, child of this
};

// Host for the native QgsLayerTreeView bound to the same session
// project (QgisLayerTreeHost parity).
class QgisLayerTreeHost : public QWidget {
    Q_OBJECT
public:
    QgisLayerTreeHost(pwb::qgis::MapSession& session,
                      QWidget* parent = nullptr);

    QgsLayerTreeView* tree_view() const { return tree_view_; }

private:
    QgsLayerTreeView* tree_view_ = nullptr;  // session-owned
};

}  // namespace pwb::ui_widgets::qgis
