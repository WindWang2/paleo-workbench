#pragma once

// [NON-PRODUCTION] UI-11 — workstation_composite_prototype.py Qt shell:
// the three-layout composite-editing design exploration (throwaway — do
// not wire into production code). Gated by PALEO_PROTOTYPE_COMPOSITE=1
// (prototype_requested); the target only compiles when Pwb::UiMapQgis
// exists because the canvas is the real QGIS DisplayMapCanvas.
//
// The snapshot producer (workarea_map_snapshot.build_workarea_map_
// snapshot) stays an injected seam — the host passes the snapshot Json.

#include "pwb/domain/json.hpp"
#include "pwb/ui_review/composite_layers.hpp"

#include <QFrame>
#include <QWidget>

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_map {
class DisplayMapCanvas;
}  // namespace pwb::ui_map

class QEvent;
class QKeyEvent;
class QLineEdit;
class QListWidget;
class QResizeEvent;
class QSlider;
class QTreeWidget;
class QTreeWidgetItem;

namespace pwb::ui_review::qt {

class CompositeVariantsWidget;

// PALEO_PROTOTYPE_COMPOSITE gate — {"1","true","yes","on"} verbatim.
bool prototype_requested();

// LayerManagerPanel parity — layer tree + opacity + order + legend,
// mutations write back through the owner's snapshot publish cycle.
class LayerManagerPanel : public QFrame {
    Q_OBJECT
public:
    explicit LayerManagerPanel(CompositeVariantsWidget* owner,
                               QWidget* parent = nullptr);

    void refresh_tree();
    QTreeWidget* tree() const { return tree_; }

private:
    void reload();
    void filter(const QString& text);
    void on_item_changed(QTreeWidgetItem* item);
    void sync_opacity();
    void apply_opacity(int value);
    void move(int direction);

    CompositeVariantsWidget* owner_;
    bool reload_guard_ = false;
    QLineEdit* search_ = nullptr;
    QTreeWidget* tree_ = nullptr;
    QSlider* opacity_ = nullptr;
    QListWidget* legend_ = nullptr;
};

// CompositeVariants — three layout variants + the floating switcher.
class CompositeVariantsWidget : public QWidget {
    Q_OBJECT
public:
    // snapshot: {"project_crs": ..., "layers": [...]} — the host's
    // workarea snapshot; project_json supplies the B-variant input tree
    // (wells array).
    explicit CompositeVariantsWidget(
        QWidget* parent, const domain::Json& snapshot,
        const domain::Json& project_json = domain::Json::object());

    // Variant vocabulary: ("A","右置图层管理") ("B","双栏工作台")
    // ("C","全幅浮动停靠").
    QString variant_key() const;
    QString variant_name() const;
    int variant_index() const { return variant_index_; }

    void apply_variant(int index);
    void next_variant() { apply_variant(variant_index_ + 1); }
    void previous_variant() { apply_variant(variant_index_ - 1); }

    // Layer mutations (snapshot publish cycle).
    const domain::Json* layer_by_id(const std::string& id) const;
    void set_layer_visible(const std::string& id, bool visible);
    void set_layer_opacity(const std::string& id, double opacity);
    void move_layer(const std::string& id, int direction);
    const CompositeLayers& layers() const { return layers_; }

    ui_map::DisplayMapCanvas* canvas() const { return canvas_; }
    LayerManagerPanel* layer_manager() const { return layer_manager_; }

signals:
    void variant_changed();

protected:
    void keyPressEvent(QKeyEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    void publish();
    QWidget* build_a();
    QWidget* build_b();
    QWidget* build_c();
    QWidget* map_toolbar();
    QWidget* input_tree();
    void mount_switcher();
    void reposition_switcher();

    ui_map::DisplayMapCanvas* canvas_ = nullptr;
    LayerManagerPanel* layer_manager_ = nullptr;
    domain::Json project_json_;
    std::string project_crs_;
    CompositeLayers layers_;
    int variant_index_ = 0;
    QFrame* switcher_ = nullptr;
    // Variant-C floating chrome (rebuilt per apply_variant).
    QWidget* c_page_ = nullptr;
    std::function<void()> c_relayout_;
};

}  // namespace pwb::ui_review::qt
