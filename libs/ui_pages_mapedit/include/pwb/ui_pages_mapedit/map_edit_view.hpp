// UI-08 — paleo_workbench/ui/pages/map_edit_view.py port: the primary
// QGraphicsView over MapEditScene — wheel zoom, cursor-position publish,
// view-state dict, and the navigation display LOD (idle-restore timer).
#pragma once

#include <QGraphicsView>
#include <QPointF>
#include <QVariantMap>

class QTimer;

namespace pwb::ui_pages_mapedit {

class MapEditScene;

// Idle delay before full-detail rendering is restored after navigation.
inline constexpr int kNavLodIdleMs = 120;

class MapEditView : public QGraphicsView {
    Q_OBJECT
public:
    explicit MapEditView(QWidget* parent = nullptr);

    bool navigation_lod_active() const { return nav_lod_active_; }

    // {"center": (x, y), "scale": m11} — the shared view-state dict.
    QVariantMap view_state() const { return shared_view_state_; }
    // emit_change ↔ Python emit=True keyword ('emit' is a Qt macro).
    void apply_view_state(const QVariantMap& state,
                        bool emit_change = false);
    void reset_view();

    MapEditScene* edit_scene() const;

signals:
    void view_state_changed(const QVariantMap& state);
    // (x, y) pair — Python Signal(tuple) parity.
    void cursor_position_changed(double x, double y);

protected:
    void wheelEvent(QWheelEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void scrollContentsBy(int dx, int dy) override;
    void keyPressEvent(QKeyEvent* event) override;

private:
    void begin_navigation_lod();
    void end_navigation_lod();
    QVariantMap read_view_state() const;

    QVariantMap shared_view_state_;
    bool nav_lod_active_ = false;
    QTimer* nav_lod_timer_ = nullptr;
};

}  // namespace pwb::ui_pages_mapedit
