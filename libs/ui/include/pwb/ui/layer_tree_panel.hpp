#pragma once

// CONV-27 — LayerTreePanel: the domain-aware face over QgsLayerTreeView.
// Fixes the PySide6-era layer tree defects at the authority level:
//   * selection -> active layer sync resolves the DOMAIN id through the
//     join key (layer_adapter), never the row index (row mapping broke
//     under groups/reorder);
//   * group add/rename/remove/reorder go through QGIS default actions on
//     the same tree the canvas bridge consumes (one visibility/order
//     authority; business state lives in the facts map, untouched by
//     reorder);
//   * edit-state indication is derived from the QGIS edit buffer itself
//     (isEditable/isModified), not a mirrored flag;
//   * role/maturity/frozen facts render as tooltips from the host's
//     facts provider (DomainLayerFacts).

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <QWidget>

#include <pwb/application/project_session.hpp>

class QgsMapCanvas;
class QgsLayerTreeView;
class QgsLayerTreeViewIndicator;
class QgsLayerTreeViewDefaultActions;
class QgsMapLayer;
class QMenu;
class QSlider;
class QToolBar;

namespace pwb::ui {

class LayerTreePanel : public QWidget {
    Q_OBJECT
public:
    // Facts lookup the host owns (layer_id -> DomainLayerFacts).
    using FactsProvider =
        std::function<std::optional<pwb::application::DomainLayerFacts>(
            const std::string&)>;

    // The view is created through MapSession::createLayerTree (session
    // tracks it for ordered teardown); the panel parents it here. The
    // canvas feeds the QGIS default zoom actions.
    LayerTreePanel(pwb::qgis::MapSession& session, QgsMapCanvas* canvas,
                   const FactsProvider& facts_provider,
                   QWidget* parent = nullptr);

    QgsLayerTreeView* view() const { return view_; }

    // Reflects the authoritative active layer into the tree selection
    // (no signal loops: setCurrentLayer on the same layer is a no-op).
    void set_active_layer(const std::string& layer_id);

    // Re-derives edit indicators + facts tooltips for every layer node
    // (call after edit state, facts or layer set changed).
    void refresh_indicators();

    // Test readback: layer ids that currently carry the editing
    // indicator, in tree order.
    std::vector<std::string> editing_indicated_layer_ids() const;

signals:
    // Domain layer id of the tree's current layer ("" when the current
    // node is a group / no layer).
    void active_layer_changed(const QString& layer_id);

    // Context-menu facts: the user asked for native layer properties on
    // this layer (host opens the QGIS properties surface).
    void layer_properties_requested(const QString& layer_id);

private:
    void build_context_menu(const QPoint& global_pos);
    void on_current_layer_changed(QgsMapLayer* layer);
    void sync_opacity_control(QgsMapLayer* layer);

    pwb::qgis::MapSession& session_;
    QgsMapCanvas* canvas_ = nullptr;
    FactsProvider facts_provider_;
    QgsLayerTreeView* view_ = nullptr;
    ::QgsLayerTreeViewDefaultActions* default_actions_ = nullptr;
    QToolBar* toolbar_ = nullptr;
    QSlider* opacity_ = nullptr;
    // One editing indicator per domain layer id (recreated on refresh).
    std::map<std::string, QgsLayerTreeViewIndicator*> edit_indicators_;
};

}  // namespace pwb::ui
