#include <pwb/ui_composite/composite_document.hpp>

#include <pwb/ui_composite/composite_controller.hpp>
#include <pwb/ui_composite/composite_controller_qt.hpp>
#include <pwb/ui_composite/composite_panels.hpp>
#include <pwb/ui_composite/facies_selector.hpp>
#include <pwb/ui_composite/layer_manager_panel.hpp>
#include <pwb/ui_composite/mapping_stage_bar.hpp>
#include <pwb/ui_composite/mapping_stage_panel.hpp>
#include <pwb/ui_composite/topology_checker_panel.hpp>
#include <pwb/ui_shell/map_status_bar.hpp>
#include <pwb/ui_widgets/constraint_factor_hud.hpp>
#include <pwb/ui_widgets/facies_eyedropper.hpp>
#include <pwb/ui_widgets/facies_palette_widget.hpp>
#include <pwb/ui_widgets/interactive_qc_hub.hpp>
#include <pwb/ui_widgets/stratigraphic_timeline_slider.hpp>

#include <QVBoxLayout>

namespace pwb::ui_composite {

CompositeDocument::CompositeDocument(QWidget* parent) : QWidget(parent) {
    setObjectName("CompositeDocument");

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    // M1 多期次时间轴：画布之上的常驻横条（宿主绑定 EpochTimelineController）。
    timeline = new pwb::ui_widgets::StratigraphicTimelineWidget(this);
    layout->addWidget(timeline);

    // 中央画布占位：宿主 set_canvas 注入真实控件（QgisCanvasShim 或回退）。
    // 空态提示挂画布层（WA_TransparentForMouseEvents）。

    // M3 单因素约束 HUD：画布右上角浮动只读条（宿主装 canvas 后 reparent）。
    constraint_hud = new pwb::ui_widgets::ConstraintFactorHud(this);
    constraint_hud->hide();

    // 识别结果 / 拓扑 / QC / 状态条：图件主视图的诚实附属层。
    identify_results = new IdentifyResultsPanel(this);
    identify_results->setMaximumHeight(200);
    layout->addWidget(identify_results);

    topology_panel = new TopologyCheckerPanel(this);
    topology_panel->setMaximumHeight(220);
    topology_panel->hide();
    layout->addWidget(topology_panel);

    qc_hub = new pwb::ui_widgets::InteractiveQCHub(this);
    qc_hub->setMaximumHeight(240);
    qc_hub->hide();
    layout->addWidget(qc_hub);

    status_bar = new pwb::ui_shell::MapStatusBar(this);
    layout->addWidget(status_bar);

    // 编辑控制器：Qt-free 核心 + QObject 信号面（面板多订阅）。
    edit_controller = new CompositeEditController();
    controller_object =
        new CompositeEditControllerObject(edit_controller, this);
    topology_panel->bind(edit_controller);

    // M2 相带画刷 + 调色板 + 吸色管（调色板默认隐藏——宿主 dock 挂载时
    // reparent）。
    facies_brush = new pwb::ui_widgets::FaciesBrushContext(this);
    facies_palette = new pwb::ui_widgets::FaciesPaletteWidget(this);
    facies_palette->set_brush(facies_brush);
    facies_palette->hide();
    facies_eyedropper = new pwb::ui_widgets::FaciesEyedropper(this);

    // dock 面板（宿主注册）。
    layer_manager = new LayerManagerPanel();
    input_tree = new InputTreePanel();
    linked_views = new LinkedViewsPanel();
    stage_panel = new MappingStagePanel();
    stage_bar = new MappingStageBar();

    // 内容变化（数字化 / 属性编辑）经 120ms debounce 重组快照；结构变
    // 化立即重组（Python 同语义）。
    composition_timer_ = new QTimer(this);
    composition_timer_->setSingleShot(true);
    composition_timer_->setInterval(120);
    connect(composition_timer_, &QTimer::timeout, this,
            &CompositeDocument::sync_composition_now);

    wire_panels();
}

CompositeDocument::~CompositeDocument() { delete edit_controller; }

void CompositeDocument::set_canvas(QWidget* canvas,
                                   bool uses_native_stack) {
    if (canvas_ == canvas) return;
    if (canvas_ != nullptr) {
        layout()->removeWidget(canvas_);
        canvas_->setParent(nullptr);
    }
    canvas_ = canvas;
    uses_native_stack_ = uses_native_stack;
    if (canvas_ != nullptr) {
        // 时间轴(0) 之后、附属层之前 = 中央区。
        auto* box = static_cast<QVBoxLayout*>(layout());
        box->insertWidget(1, canvas_, 1);
        // 空态提示挂画布（鼠标穿透）。
        if (empty_hint_ == nullptr) {
            empty_hint_ = new QLabel(
                QStringLiteral(
                    "空工程 — 从左侧 Explorer 导入数据，"
                    "或用工具条「新建图层」开始编图"),
                canvas_);
            empty_hint_->setObjectName("CompositeEmptyHint");
            empty_hint_->setAlignment(Qt::AlignCenter);
            empty_hint_->setAttribute(Qt::WA_TransparentForMouseEvents);
            empty_hint_->hide();
        }
        constraint_hud->setParent(canvas_);
    }
}

void CompositeDocument::set_project_crs(const std::string& crs) {
    project_crs_ = crs;
    layer_manager->set_project_crs(crs);
    edit_controller->project_crs = crs;
}

void CompositeDocument::update_empty_hint(bool has_content) {
    if (empty_hint_ != nullptr) empty_hint_->setVisible(!has_content);
}

// -- 面板接线（壳层分派；重逻辑在控制器/宿主） --------------------------------------

void CompositeDocument::wire_panels() {
    // 控制器事件 → 组合快照节奏（结构立即 / 内容 debounce / 提交立即）。
    connect(controller_object,
            &CompositeEditControllerObject::layers_changed, this,
            [this]() { sync_composition(true); });
    connect(controller_object,
            &CompositeEditControllerObject::content_changed, this,
            [this](const QString&) { sync_composition(false); });
    connect(controller_object,
            &CompositeEditControllerObject::sessions_committed, this,
            [this]() { sync_composition(true); });
    connect(controller_object,
            &CompositeEditControllerObject::native_join_refused, this,
            &CompositeDocument::status_message);

    // 阶段条/阶段面板 → 宿主请求信号。
    connect(stage_bar, &MappingStageBar::stage_requested, this,
            &CompositeDocument::stage_switch_requested);
    connect(stage_bar, &MappingStageBar::horizon_requested, this,
            &CompositeDocument::horizon_requested);
    connect(stage_panel, &MappingStagePanel::stage_switch_requested, this,
            &CompositeDocument::stage_switch_requested);
    connect(stage_panel, &MappingStagePanel::action_requested, this,
            &CompositeDocument::stage_action_requested);
    connect(stage_panel, &MappingStagePanel::locate_requested, this,
            &CompositeDocument::locate_requested);
    connect(stage_panel, &MappingStagePanel::constraint_requested, this,
            &CompositeDocument::constraint_requested);

    // 输入树选择 → 宿主联动。
    connect(input_tree, &InputTreePanel::object_selected, this,
            &CompositeDocument::object_selected);

    // 状态条激活路径（V10 §15 拓扑 chip / 捕捉设置）。
    connect(status_bar, &pwb::ui_shell::MapStatusBar::topology_activated,
            this, [this]() {
                if (!topology_panel->isVisible()) topology_panel->show();
            });
}

// -- 画布槽（宿主接线） -------------------------------------------------------------

void CompositeDocument::on_tool_operation(bool edits_data) {
    // 工具手势落点：结构变化立即重组，否则走 debounce（Python
    // _on_tool_operation 同语义）。
    sync_composition(edits_data);
}

void CompositeDocument::on_extent_changed() {
    // 视野是高频事件：只轻量刷新（Python _on_extent_changed 同语义）。
    // 勾选态/全量上下文重建留在状态同步链。
    sync_status_bar();
}

void CompositeDocument::on_map_position(double x, double y) {
    if (status_bar != nullptr) {
        status_bar->update_coordinate({x, y});
    }
}

void CompositeDocument::on_backend_status_changed() {
    sync_status_bar();
}

void CompositeDocument::on_native_tool_activation_failed(
    const QString& tool_id, const QString& reason) {
    // V8/M1：原生 QgsMapTool 激活失败 → 回退 pan + 状态条原因。
    emit status_message(
        reason.isEmpty()
            ? QStringLiteral("原生工具 %1 不可用，已回退到平移").arg(tool_id)
            : reason);
}

void CompositeDocument::sync_status_bar() {
    // 状态条事实聚合在宿主（facts 经 status_bar.apply_context 注入；
    // 壳层不二次判定，只触发重估）。
    if (rebuild_status) rebuild_status();
}

void CompositeDocument::sync_composition(bool immediate) {
    if (immediate) {
        composition_timer_->stop();
        sync_composition_now();
        return;
    }
    composition_timer_->start();
}

void CompositeDocument::sync_composition_now() {
    // 快照重组的渲染发布在宿主侧（壳层只负责节奏）。
    if (rebuild_composition) rebuild_composition();
}

}  // namespace pwb::ui_composite
