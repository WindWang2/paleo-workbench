#include "pwb/ui_widgets/qgis/stack_events.hpp"

#include <qgsmapcanvas.h>
#include <qgspointxy.h>
#include <qgsrectangle.h>

namespace pwb::ui_widgets::qgis {

void StackEvents::attach(QgsMapCanvas* canvas) {
    canvas_ = canvas;
    if (canvas == nullptr) {
        return;
    }
    // QgsMapCanvas::extentsChanged has no payload — read the current
    // extent at emit time (the Python bridge passes the rect directly;
    // the requeue delays delivery, so read it in the queued lambda to
    // match "the extent the consumer sees" semantics).
    connect(canvas, &QgsMapCanvas::extentsChanged, this, [this] {
        QgsMapCanvas* canvas = canvas_;
        if (canvas == nullptr) {
            return;
        }
        requeue([canvas, this] {
            const QgsRectangle e = canvas->extent();
            emit extent_changed(e.xMinimum(), e.yMinimum(), e.xMaximum(),
                                e.yMaximum());
        });
    });
    connect(canvas, &QgsMapCanvas::xyCoordinates, this,
            [this](const QgsPointXY& p) {
                const double x = p.x();
                const double y = p.y();
                requeue([this, x, y] { emit map_position_changed(x, y); });
            });
}

}  // namespace pwb::ui_widgets::qgis
