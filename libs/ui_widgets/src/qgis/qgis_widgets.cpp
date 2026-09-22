#include "pwb/ui_widgets/qgis/qgis_widgets.hpp"

#include <pwb/platform_services/resource_locator.hpp>
#include <pwb/qgis/map_session.hpp>

#include <QDir>
#include <QMetaObject>
#include <QVBoxLayout>

#include <qgslayertreeview.h>
#include <qgsmapcanvas.h>

namespace pwb::ui_widgets::qgis {

QWidget* canvas_viewport(QgsMapCanvas* canvas) {
    if (canvas == nullptr) {
        return nullptr;
    }
    // QgsMapCanvas is a QGraphicsView — the event drop point is its
    // viewport (Python's shiboken-wrap path resolves the same object).
    if (QWidget* viewport = canvas->viewport()) {
        return viewport;
    }
    // Fallback parity: the unnamed qt_scrollarea_viewport child.
    const auto children = canvas->findChildren<QWidget*>();
    for (QWidget* child : children) {
        if (child->objectName() == QStringLiteral("qt_scrollarea_viewport")) {
            return child;
        }
    }
    return nullptr;
}

void configure_layer_tree_view(QgsLayerTreeView* view) {
    if (view == nullptr) {
        return;
    }
    view->setRootIsDecorated(true);
    view->setItemsExpandable(true);
    view->setExpandsOnDoubleClick(true);
    view->setIndentation(20);
    // Branch icons from the bundled map assets (Python _layer_tree_branch_qss).
    const QString closed = platform_services::icon_file(
        QStringLiteral("map/tree-branch-closed.svg"));
    const QString opened = platform_services::icon_file(
        QStringLiteral("map/tree-branch-open.svg"));
    const QString closed_url = QDir(closed).absolutePath();
    const QString opened_url = QDir(opened).absolutePath();
    view->setStyleSheet(
        QStringLiteral(
            "QTreeView { show-decoration-selected: 1; }\n"
            "QTreeView::branch { background: transparent; }\n"
            "QTreeView::branch:has-children:!has-siblings:closed,"
            "QTreeView::branch:closed:has-children:has-siblings {"
            " border-image: none; image: url(\"%1\"); }\n"
            "QTreeView::branch:open:has-children:!has-siblings,"
            "QTreeView::branch:open:has-children:has-siblings {"
            " border-image: none; image: url(\"%2\"); }\n")
            .arg(closed_url, opened_url));
    // Python: QMetaObject.invokeMethod(widget, "expandAllNodes",
    // DirectConnection) — QgsLayerTreeView::expandAllNodes is the same
    // slot (expand all group nodes once on configure).
    view->expandAllNodes();
}

QgisCanvasHost::QgisCanvasHost(pwb::qgis::MapSession& session,
                               QWidget* parent)
    : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    canvas_ = session.createCanvas(this);
    layout->addWidget(canvas_);
}

QgisLayerTreeHost::QgisLayerTreeHost(pwb::qgis::MapSession& session,
                                     QWidget* parent)
    : QWidget(parent) {
    tree_view_ = session.createLayerTree(this);
    configure_layer_tree_view(tree_view_);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    layout->addWidget(tree_view_);
}

}  // namespace pwb::ui_widgets::qgis
