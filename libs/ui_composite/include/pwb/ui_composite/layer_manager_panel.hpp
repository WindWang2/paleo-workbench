#pragma once

// Port of LayerManagerPanel / InputTreePanel / LinkedViewsPanel from
// paleo_workbench/ui/workstation/composite_document.py (UI-13).
// 图层管理面板：可见性 / 不透明度 / 顺序 / 图例，真实写回渲染快照。
//
// 矢量图层的新建与删除不在此直接执行——面板只发请求信号，由宿主
// （CompositeDocument 等价物）经 CompositeEditController 落地后重绑。
// 树消费 MapLayerSnapshot（渲染快照的图层记录）——不是图层权威。

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/tool_policy/tool_availability.hpp>
#include <pwb/ui_composite/layer_decorations.hpp>
#include <pwb/ui_composite/map_snapshot.hpp>

#include <QFrame>
#include <QIcon>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QSlider>
#include <QToolButton>
#include <QTreeWidget>

namespace pwb::ui_composite {

using pwb::domain::Json;

// 画布鸭子类型（QgisCanvasShim）：面板只调用 set_extent /
// set_layer_snapshot 两个方法 → 显式 hooks。
struct LayerPanelCanvasHooks {
    std::function<void(const MapExtent&)> set_extent;
    std::function<void(const MapRenderSnapshot&)> set_layer_snapshot;
};

// 图层面板状态列装饰（V7 §7）：id → LayerPresentationState；token 与
// 摘要经核心 decoration_token / decoration_summary_text 单一派生。

// QGIS 式图层树类型图标（按几何类型绘制 16px 符号）。
QIcon layer_kind_icon(const std::string& kind, const Json& style);

class LayerManagerPanel : public QFrame {
    Q_OBJECT
public:
    explicit LayerManagerPanel(QWidget* parent = nullptr);

    // V8 M2/V10 M5 探针注入（宿主把目标图层事实投影进 canonical
    // evaluator；无注入 = 独立用/测试回落 metadata 旗标旧行为）。
    void set_repair_probe(
        std::function<std::optional<pwb::tool_policy::ToolAvailability>(
            const std::string&)> probe) {
        repair_probe_ = std::move(probe);
    }
    void set_menu_probe(
        std::function<std::optional<LayerMenuFacts>(const std::string&)>
            probe) {
        menu_probe_ = std::move(probe);
    }

    // -- 绑定 -----------------------------------------------------------------
    void bind(const LayerPanelCanvasHooks& canvas,
              const std::vector<MapLayerSnapshot>& layers);
    void set_project_crs(const std::string& crs);
    void select_layer(const std::string& layer_id);
    int tree_row_count() const;

    // -- 快照变更（渲染自底向上：上移 = 提前 = index-1） ------------------------
    const MapLayerSnapshot* layer_by_id(const std::string& layer_id) const;
    void set_layer_visible(const std::string& layer_id, bool visible,
                           bool reload_tree = true);
    void set_layer_opacity(const std::string& layer_id, double opacity);
    void move_layer(const std::string& layer_id, int direction);
    void set_editing_layer(const std::optional<std::string>& layer_id);
    void set_layer_decorations(
        const std::map<std::string, LayerPresentationState>& decorations);

    static bool is_editable_layer(const MapLayerSnapshot& layer);
    static bool is_reference_layer(const MapLayerSnapshot& layer);

    QLineEdit* search = nullptr;
    QTreeWidget* tree = nullptr;
    QSlider* opacity = nullptr;
    QListWidget* legend = nullptr;
    QToolButton* remove_button = nullptr;

signals:
    void create_layer_requested();
    void facies_taxonomy_requested();
    void remove_layer_requested(const QString& layer_id);
    void rename_layer_requested(const QString& layer_id);
    // 引用矢量图层（外部 GDAL 源，只读参考）的导入与上下文动作。
    void import_reference_requested();
    void remove_reference_requested(const QString& layer_id);
    void refresh_reference_requested(const QString& layer_id);
    void toggle_reference_snap_requested(const QString& layer_id);
    // QGIS 图层面板语义的上下文动作（由宿主落地）。
    void attribute_table_requested(const QString& layer_id);
    void toggle_editing_requested(const QString& layer_id);
    void properties_requested(const QString& layer_id);
    void symbology_requested(const QString& layer_id);
    void labeling_requested(const QString& layer_id);
    void duplicate_layer_requested(const QString& layer_id);
    void export_layer_requested(const QString& layer_id);
    void repair_layer_requested(const QString& layer_id);
    void render_preset_requested(const QString& layer_id);
    // 当前图层变化（无可编辑图层时携带空串）。
    void active_layer_changed(const QVariant& layer_id);
    // V7 §7：双击定位（zoom to layer；由宿主落地）。
    void zoom_to_layer_requested(const QString& layer_id);

private:
    void publish(bool reload_tree = true);
    void reload();
    void update_tree_item(QTreeWidgetItem* item,
                          const MapLayerSnapshot& layer);
    void apply_item_decoration(QTreeWidgetItem* item,
                               const std::string& layer_id,
                               const QString& label);
    void filter(const QString& text);
    void on_item_changed(QTreeWidgetItem* item);
    void on_context_menu(const QPoint& position);
    void on_current_changed(QTreeWidgetItem* current,
                            QTreeWidgetItem* previous);
    void sync_opacity();
    void apply_opacity(int value);
    void move_up();
    void move_down();

    std::function<std::optional<pwb::tool_policy::ToolAvailability>(
        const std::string&)>
        repair_probe_;
    std::function<std::optional<LayerMenuFacts>(const std::string&)>
        menu_probe_;

    std::vector<MapLayerSnapshot> layers_;
    LayerPanelCanvasHooks canvas_;
    bool tree_connected_ = false;
    std::optional<std::string> editing_layer_id_;
    bool reloading_ = false;
    std::map<std::string, LayerPresentationState> decorations_;
    std::string project_crs_;
};

// 输入与结果树：编修输入（井 / 地震）与成果（图件文档）的真实清单；
// 选中仅发布 payload。
class InputTreePanel : public QFrame {
    Q_OBJECT
public:
    explicit InputTreePanel(QWidget* parent = nullptr);

    // 工程只读投影（wells/seismic/maps 名称清单）。
    void refresh(const std::vector<std::string>& wells,
                 const std::vector<std::string>& seismic,
                 const std::vector<std::string>& maps);

    QTreeWidget* tree = nullptr;

signals:
    void object_selected(const QVariantMap& payload);
};

// 联动视图面板：与图件选择联动的测井/地震视图（诚实空态）。
class LinkedViewsPanel : public QFrame {
    Q_OBJECT
public:
    explicit LinkedViewsPanel(QWidget* parent = nullptr);
};

}  // namespace pwb::ui_composite
