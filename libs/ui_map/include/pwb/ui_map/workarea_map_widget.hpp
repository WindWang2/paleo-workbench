#pragma once

// UI-05 — WorkAreaMapWidget (workarea_map_widget.py): the reusable GIS
// work-area map (well positions + seismic surveys + boundary).
//
// The whole pane is one map: rendering goes through the same
// DisplayMapCanvas the home page / map preview use (a QgsMapCanvas when
// the bridge is up), data comes from the pure producer
// mapping/workarea_map_snapshot. Read-only interactions: wheel zoom,
// middle/space drag pan, left-click well pick (select + highlight +
// activate).
//
// The workstation's well-seismic 平面图 pane shares this widget — no
// second hand-drawn map copy.

#include <functional>
#include <string>

#include <QWidget>

#include <pwb/ui_map/map_chrome_core.hpp>

namespace pwb::ui_map {

class DisplayMapCanvas;

class WorkAreaMapWidget : public QWidget {
    Q_OBJECT
public:
    // title="" / show_legend=true — small panes (the linked 平面图) can
    // turn the legend off so it does not cover well positions.
    explicit WorkAreaMapWidget(QWidget* parent = nullptr,
                               std::string title = "",
                               bool show_legend = true);

    // Stop the render backend before the host destroys the widget.
    // Canvas shutdown is idempotent; hidden panes never get a reliable
    // closeEvent, so the host must call this on project switch/teardown.
    void shutdown();

    // ------------------------------------------------------------------
    // data
    // ------------------------------------------------------------------

    // Rebind the project; the snapshot rebuilds only on a domain change
    // (domain_signature cache — Python set_project parity). The snapshot
    // builder is injected because the producer
    // (workarea_map_snapshot.build_workarea_map_snapshot) is a
    // mapping-domain port owned by another slice; hosts pass the native
    // producer (or an adapter). A null project clears the map; a null
    // builder mirrors "no content".
    void set_project(const Json& project,
                     const std::function<Json(const Json&)>&
                         snapshot_builder = {});

    void zoom_to_all();

    // ------------------------------------------------------------------
    // selection
    // ------------------------------------------------------------------

    // Highlight a well (yellow ring via the overlay); optionally zoom to
    // it and/or re-emit well_selected (Python emit= parity).
    void select_well(const std::string& well_id, bool zoom = false,
                     bool emit_signal = false);
    const std::string& selected_well_id() const { return selected_well_id_; }

    // ------------------------------------------------------------------
    // test / integration surface
    // ------------------------------------------------------------------

    DisplayMapCanvas* map_canvas() const { return map_canvas_; }
    const Json& snapshot() const { return snapshot_; }
    bool has_snapshot() const { return !snapshot_.is_null(); }
    // _current_half_span: max(half x-span, half y-span, 1.0).
    double current_half_span() const;

signals:
    void well_selected(const QString& well_id);   // 单击选中
    void well_activated(const QString& well_id);  // 单击激活（直接开井）

private:
    Json overlay_state() const;
    Json well_feature(const std::string& well_id) const;
    void on_map_clicked(double x, double y);

    Json signature_ = Json(nullptr);  // domain_signature cache (_signature)
    Json snapshot_ = Json(nullptr);   // last built snapshot (_snapshot)
    std::string selected_well_id_;
    std::string title_;
    bool show_legend_ = true;
    DisplayMapCanvas* map_canvas_ = nullptr;  // child widget
};

}  // namespace pwb::ui_map
