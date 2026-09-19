#pragma once

// UI-02 — bridge/canvas callback → Qt signal requeue, ported from
// paleo_workbench/ui/qgis_stack/events.py.
//
// The Python bridge delivers canvas callbacks on the GUI thread but
// deep inside the bridge call stack; every emit is requeued via
// QTimer::singleShot(0, context, …) so slots never run inside that
// stack. In the native port the "stack" IS a QgsMapCanvas — the same
// requeue contract applies: extentsChanged / xyCoordinates arrive
// inside canvas event processing, and consumers must not mutate the
// canvas mid-dispatch.
//
// V8 M9 (#951 root-cause class): the singleShot MUST carry a QObject
// context — a bare lambda is still woken after this object's death and
// emitting into a destroyed object crashes. The context cancels
// delivery on destruction; emit also guards with QPointer.

#include <QObject>
#include <QPointer>
#include <QTimer>

class QgsMapCanvas;

namespace pwb::ui_widgets::qgis {

class StackEvents : public QObject {
    Q_OBJECT
public:
    explicit StackEvents(QObject* parent = nullptr) : QObject(parent) {}

    // Attach to a live canvas. Both signals are requeued through
    // singleShot(0, this, …) — same as the Python bridge path.
    void attach(QgsMapCanvas* canvas);

signals:
    void extent_changed(double xmin, double ymin, double xmax,
                        double ymax);
    void map_position_changed(double x, double y);

private:
    // Requeue an emit so it never fires inside the canvas call stack.
    // Context = this: delivery cancels on destruction (#951); the
    // QPointer guard covers the emit moment itself.
    template <typename F>
    void requeue(F&& fn) {
        QPointer<StackEvents> context = this;
        QTimer::singleShot(0, this, [context, fn = std::forward<F>(fn)] {
            if (context != nullptr) {
                fn();
            }
        });
    }

    QPointer<QgsMapCanvas> canvas_;
};

}  // namespace pwb::ui_widgets::qgis
