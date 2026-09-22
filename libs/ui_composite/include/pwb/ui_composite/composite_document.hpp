#pragma once

// Qt shell of paleo_workbench/ui/workstation/composite_document.py
// (UI-13). 编图文档：图件画布即主窗口内容（永不浮动），面板全部为宿
// 主 dock。
//
// 本壳层只做装配：中央画布（宿主注入的 QgisCanvasShim/回退画布控件）
// + 已移植的 dock 面板 + 状态条 + 识别结果/拓扑/QC 附属层 + 编辑控制
// 器（Qt-free 核心 + QObject 信号面）。语义权威全部在核心库与既有部
// 件（MapStatusBar / InteractiveQCHub / FaciesPaletteWidget / HUD /
// timeline）——壳层不再生长第二份编排逻辑；画布的鸭子类型信号
// （tool_operation / extent_changed / map_position / context menu…）
// 由宿主接线到本类的公开槽（Python getattr(canvas, sig, None) 的诚
// 实等价：信号缺席 = 不接线）。

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/map_snapshot.hpp>

#include <QLabel>
#include <QTabBar>
#include <QTimer>
#include <QWidget>

namespace pwb::ui_shell {
class MapStatusBar;
}
namespace pwb::ui_widgets {
class ConstraintFactorHud;
class FaciesEyedropper;
class FaciesPaletteWidget;
class FaciesBrushContext;
class InteractiveQCHub;
class StratigraphicTimelineWidget;
}  // namespace pwb::ui_widgets

namespace pwb::ui_composite {

using pwb::domain::Json;

class CompositeEditController;
class CompositeEditControllerObject;
class IdentifyResultsPanel;
class InputTreePanel;
class LayerManagerPanel;
class LinkedViewsPanel;
class MappingStageBar;
class MappingStagePanel;
class TopologyCheckerPanel;

class CompositeDocument : public QWidget {
    Q_OBJECT
public:
    explicit CompositeDocument(QWidget* parent = nullptr);
    ~CompositeDocument() override;

    // -- 宿主装配缝 -------------------------------------------------------------
    // 画布控件 + 其 CompositeCanvasHooks（QgisCanvasShim 或回退画布）。
    // 只负责挂进中央区；编辑控制器 attach 由宿主或 attach_controller 完
    // 成。uses_native = QGIS 原生栈呈现态（状态条用）。
    void set_canvas(QWidget* canvas, bool uses_native_stack = false);
    QWidget* canvas() const { return canvas_; }
    bool uses_native_stack() const { return uses_native_stack_; }

    // 面板实例由壳层创建、宿主注册为 dock（Python WorkstationFrame
    // parity）。
    LayerManagerPanel* layer_manager = nullptr;
    InputTreePanel* input_tree = nullptr;
    LinkedViewsPanel* linked_views = nullptr;
    MappingStagePanel* stage_panel = nullptr;
    MappingStageBar* stage_bar = nullptr;
    IdentifyResultsPanel* identify_results = nullptr;
    TopologyCheckerPanel* topology_panel = nullptr;
    pwb::ui_widgets::InteractiveQCHub* qc_hub = nullptr;
    pwb::ui_widgets::FaciesPaletteWidget* facies_palette = nullptr;
    pwb::ui_widgets::FaciesEyedropper* facies_eyedropper = nullptr;
    pwb::ui_widgets::FaciesBrushContext* facies_brush = nullptr;
    pwb::ui_widgets::StratigraphicTimelineWidget* timeline = nullptr;
    pwb::ui_widgets::ConstraintFactorHud* constraint_hud = nullptr;
    pwb::ui_shell::MapStatusBar* status_bar = nullptr;
    // 层位标签行（画布上方）：target_horizon 的又一视图，与状态条层位
    // 下拉共享同一权威——本部件只发 horizon_requested，不持有状态。
    QTabBar* horizon_tabs = nullptr;
    // 图件标题浮层（画布顶部居中，鼠标穿透）。
    QLabel* map_title = nullptr;

    CompositeEditController* edit_controller = nullptr;
    CompositeEditControllerObject* controller_object = nullptr;

    // 项目 CRS 注入（图层面板/快照发布的单一权威入口）。
    void set_project_crs(const std::string& crs);
    const std::string& project_crs() const { return project_crs_; }

    // 宿主重建缝（缺席 = no-op）：状态条事实聚合与画布快照重组在宿主
    // 侧（它们消费项目文档/画布，壳层不二次判定）。
    std::function<void()> rebuild_status;
    std::function<void()> rebuild_composition;

    // 空态提示：无图层时中央画布给明确引导（视觉 QA 11）。
    void update_empty_hint(bool has_content);

    // 层位状态投影（宿主经 StageFlow 快照驱动）：当前层位 + 候选清单。
    // 与 StatusBar::set_horizon_state 同一权威数据，互不复制状态。
    void set_horizon_state(const QString& horizon,
                           const std::vector<QString>& options);
    QString current_horizon() const;
    // 图件标题浮层（"C6层沉积相智能预测图" 式；空串隐藏）。
    void set_map_title(const QString& title);

    // 宿主出口：dock 挂载、阶段动作派发等由 WorkstationFrame 接线。
signals:
    void object_selected(const QVariantMap& selection);
    void status_message(const QString& message);
    void well_track_toggled(bool checked);
    void seismic_section_toggled(bool checked);
    void link_toggled(bool checked);
    // V5：阶段动作请求导航到既有 hub 页，由宿主壳执行。
    void hub_page_requested(const QString& page_id);
    void stage_switch_requested(const QString& stage_value);
    // (stage_value, action_id) — 阶段上下文动作（面板透传）。
    void stage_action_requested(const QString& stage_value,
                                const QString& action_id);
    void constraint_requested(const QString& constraint_kind_value);
    void horizon_requested(const QString& horizon);
    void locate_requested(const QString& stage_value,
                          const QString& target);

public slots:
    // 画布鸭子类型信号的公开槽（宿主用 QObject::connect 接线；缺席即不
    // 接）。每个槽只做壳层分派，重逻辑在控制器。
    void on_tool_operation(bool edits_data = true);
    void on_extent_changed();
    void on_map_position(double x, double y);
    void on_backend_status_changed();
    void on_native_tool_activation_failed(const QString& tool_id,
                                          const QString& reason);
    void sync_status_bar();
    void sync_composition(bool immediate = true);

private slots:
    void sync_composition_now();

private:
    void wire_panels();
    void layout_map_title();
    bool eventFilter(QObject* obj, QEvent* event) override;

    QWidget* canvas_ = nullptr;
    bool uses_native_stack_ = false;
    QLabel* empty_hint_ = nullptr;
    bool syncing_horizon_tabs_ = false;
    QTimer* composition_timer_ = nullptr;
    std::string project_crs_;
};

}  // namespace pwb::ui_composite
