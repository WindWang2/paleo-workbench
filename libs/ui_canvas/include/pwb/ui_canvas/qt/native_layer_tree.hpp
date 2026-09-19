// UI-15 — Qt control surface for the authoritative C++ layer registry
// (native_layer_tree.py parity).
//
// NativeLayerModel owns no copy of map-layer state: each model request
// resolves the current LayerRegistry. Its only UI-local state is the
// current selection, which is intentionally not render state. Canvas
// consumers receive zoom requests as signals and remain responsible for
// applying a viewport transform.
#pragma once

#include <map>
#include <optional>
#include <string>
#include <vector>

#include <QAbstractItemModel>
#include <QFrame>
#include <QModelIndex>
#include <QString>

#include <pwb/ui_canvas/layer_tree_core.hpp>

class QAction;
class QLabel;
class QMenu;
class QTreeView;

namespace pwb::ui_canvas {

class NativeLayerModel : public QAbstractItemModel {
    Q_OBJECT
public:
    static constexpr int LayerIdRole = Qt::UserRole + 1;
    inline static const QString MimeType =
        QStringLiteral("application/x-paleo-workbench-layer-id");

    explicit NativeLayerModel(pwb::layer_model::LayerRegistry* registry,
                              QObject* parent = nullptr);

    pwb::layer_model::LayerRegistry* registry() const { return registry_; }

    std::optional<std::string> active_layer_id() const {
        return active_layer_id_;
    }

    // QAbstractItemModel -------------------------------------------------
    int columnCount(const QModelIndex& parent = {}) const override;
    int rowCount(const QModelIndex& parent = {}) const override;
    QModelIndex index(int row, int column,
                      const QModelIndex& parent = {}) const override;
    QModelIndex parent(const QModelIndex& index) const override;
    QVariant data(const QModelIndex& index,
                  int role = Qt::DisplayRole) const override;
    QVariant headerData(int section, Qt::Orientation orientation,
                        int role = Qt::DisplayRole) const override;
    Qt::ItemFlags flags(const QModelIndex& index) const override;
    QStringList mimeTypes() const override;
    QMimeData* mimeData(const QModelIndexList& indexes) const override;
    Qt::DropActions supportedDropActions() const override;
    bool dropMimeData(const QMimeData* data, Qt::DropAction action,
                      int row, int column,
                      const QModelIndex& parent) override;
    bool setData(const QModelIndex& index, const QVariant& value,
                 int role = Qt::EditRole) override;

    // Native-registry operations ------------------------------------------
    void refresh();
    pwb::layer_model::MapLayer* add_layer(
        const std::string& layer_id, const std::string& name,
        pwb::layer_model::LayerType layer_type,
        const std::string& parent_id = "");
    bool remove_layer(const std::string& layer_id);
    bool move_layer(const std::string& layer_id, std::size_t new_index);
    bool set_active_layer(const std::optional<std::string>& layer_id);
    bool request_zoom_to_layer(const std::string& layer_id);
    // Test parity: Python _index_for_id is reachable for selection tests.
    QModelIndex index_for_id(const std::string& layer_id,
                             int column = 0) const;

signals:
    void active_layer_changed(const std::optional<std::string>& layer_id);
    void layer_changed(const QString& layer_id);
    void zoom_to_layer_requested(const QString& layer_id,
                                 const std::array<double, 4>& extent);

private:
    std::size_t token_for(const std::string& layer_id);
    std::optional<std::string> id_from_index(
        const QModelIndex& index) const;
    pwb::layer_model::MapLayer* layer_at(const QModelIndex& index) const;

    pwb::layer_model::LayerRegistry* registry_ = nullptr;  // observer
    std::optional<std::string> active_layer_id_;
    // Stable internalId tokens (Python _id_to_token/_token_to_id parity).
    mutable std::map<std::string, std::size_t> id_to_token_;
    mutable std::map<std::size_t, std::string> token_to_id_;
    mutable std::size_t next_token_ = 1;
};

// Compact, keyboard-accessible QTreeView for native map layers. Layer
// management lives entirely on the right-click context menu.
class NativeLayerTree : public QFrame {
    Q_OBJECT
public:
    explicit NativeLayerTree(pwb::layer_model::LayerRegistry* registry,
                             QWidget* parent = nullptr);

    NativeLayerModel* model() const { return model_; }
    QTreeView* view() const { return tree_; }
    bool set_active_layer(const std::optional<std::string>& layer_id);
    void expand_all();

    QAction* add_layer_action() { return add_layer_action_; }
    QAction* add_group_action() { return add_group_action_; }
    QAction* remove_action() { return remove_action_; }
    QAction* move_up_action() { return move_up_action_; }
    QAction* move_down_action() { return move_down_action_; }
    QAction* zoom_action() { return zoom_action_; }
    QAction* properties_action() { return properties_action_; }

signals:
    void active_layer_changed(const std::optional<std::string>& layer_id);
    void zoom_to_layer_requested(const QString& layer_id,
                                 const std::array<double, 4>& extent);
    void add_layer_requested();
    void properties_requested(const QString& layer_id);
    void export_layer_requested(const QString& layer_id);

private:
    std::optional<std::string> current_layer_id() const;
    void sync_action_state();
    void add_group();
    void remove_current();
    void move_current(int delta);
    void zoom_current();
    void properties_current();
    void select_row_at(const QPoint& position);
    QMenu* build_context_menu();

    NativeLayerModel* model_ = nullptr;   // child QObject
    QTreeView* tree_ = nullptr;           // child widget
    QAction* add_layer_action_ = nullptr;
    QAction* add_group_action_ = nullptr;
    QAction* remove_action_ = nullptr;
    QAction* move_up_action_ = nullptr;
    QAction* move_down_action_ = nullptr;
    QAction* zoom_action_ = nullptr;
    QAction* properties_action_ = nullptr;
};

}  // namespace pwb::ui_canvas
