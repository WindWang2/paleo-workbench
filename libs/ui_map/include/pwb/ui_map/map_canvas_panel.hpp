#pragma once

// UI-05 — MapCanvasPanel (map_canvas_panel.py): the center panel that
// embeds the display canvas behind an empty-state surface. The Python
// three-surface stack (empty label / legacy PaleoMapCanvas /
// NativeMapCanvas) collapses to the authoritative QgsMapCanvas in C++:
// load_preview renders the pre-normalized payload through the display
// canvas, and the empty label covers the no-document state.
//
// load_native_scene remains a compatibility seam: the native factor-map
// composition is a later slice; the panel accepts the scene's render
// snapshot Json and shows the same canvas (never a second renderer).

#include <QFrame>

#include <pwb/ui_map/map_chrome_core.hpp>

class QLabel;
class QStackedLayout;

namespace pwb::ui_map {

class DisplayMapCanvas;

class MapCanvasPanel : public QFrame {
    Q_OBJECT
public:
    explicit MapCanvasPanel(QWidget* parent = nullptr);

    DisplayMapCanvas* canvas() const { return canvas_; }

    // load_preview(features, wells=(), period_name=""): empty payload ->
    // empty-state surface; otherwise the display canvas receives the
    // preview snapshot.
    void load_preview(const Json& features, const Json& wells = Json::array(),
                      const std::string& period_name = "");

    // load_native_scene(scene_snapshot): show the native composition
    // snapshot on the display canvas (compatibility export surface).
    void load_native_scene(const Json& scene_snapshot);

    // update_state(document): derive the preview payload from the
    // document (facies_polygons/well_overlays/linked_target_horizon) —
    // viz.mapping_helpers.preview_payload_from_document parity.
    void update_state(const Json& document);

    // Current stack page: "empty" | "canvas".
    QString current_surface() const;

private:
    QLabel* empty_label_ = nullptr;
    DisplayMapCanvas* canvas_ = nullptr;
    QStackedLayout* stack_ = nullptr;
};

}  // namespace pwb::ui_map
