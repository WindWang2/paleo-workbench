// UI-16 — offscreen Qt smoke for the visual-QA shells.
//
// Two seam consumers get exercised end-to-end:
//   * V6..V10 drive recipes (qa_driver.cpp) run against FakeProbe — a
//     test double that models the workstation facts the Python window
//     owns (stage/tool gating, chips, docks, palette rows, task handles).
//     The double is fixture code, not production logic: the real adapter
//     binds MainWindow surfaces through the same VisualQaProbe contract.
//   * V11 scenario builders (scenario_host.cpp) run against the real
//     ported widgets (task panel / seismic toolbar / inspector / task
//     center / palette / state widgets) plus FakeXxxSurface test doubles
//     on the three honest seams (AppShell, DataPage, stage surface).
//
// QT_QPA_PLATFORM=offscreen (ctest env). The settle() waits are real —
// the drive recipes keep the Python settle-then-shot rhythm.

#include <map>
#include <memory>
#include <string>
#include <vector>

#include <QApplication>
#include <QComboBox>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>
#include <QSlider>
#include <QWidget>

#include <pwb/tool_policy/layer_roles.hpp>
#include <pwb/tool_policy/stages.hpp>
#include <pwb/ui_visualqa/qa_check.hpp>
#include <pwb/ui_visualqa/qa_checks.hpp>
#include <pwb/ui_visualqa/qa_snapshot.hpp>
#include <pwb/ui_visualqa/qa_states.hpp>
#include <pwb/ui_visualqa/qt/dual_volume_overlay.hpp>
#include <pwb/ui_visualqa/qt/qa_driver.hpp>
#include <pwb/ui_visualqa/qt/scenario_host.hpp>
#include <pwb/ui_visualqa/qt/workstation_probe.hpp>

#include "ui_visualqa_test.hpp"

using namespace pwb::ui_visualqa;
using pwb::ui_visualqa::qt::QaDock;
namespace qa_qt = pwb::ui_visualqa::qt;
namespace lr = pwb::tool_policy::layer_role;

namespace {

// ---------------------------------------------------------------------------
// FakeProbe — the VisualQaProbe test double. `recompute()` mirrors the real
// composite's _sync_action_state: it regenerates verdicts/actions/chips from
// the model state (selected layer role/maturity/editing, blocking task, CRS,
// topology, snapping) so the pure check table sees consistent facts.
// ---------------------------------------------------------------------------

struct FakeLayer {
    std::string kind;      // "point"|"line"|"polygon"
    std::string role;
    std::string name;
    std::string maturity;  // "" or "frozen"
    std::string crs;
    bool editing = false;
    bool dirty = false;
    int topology_errors = 0;
};

class FakeProbe : public qa_qt::VisualQaProbe {
public:
    WorkstationSnapshot snap;
    std::map<std::string, FakeLayer> layers;
    std::string selected;
    std::string stage = "facies_calibration";
    std::string blocking;
    std::string project_crs = "EPSG:4490";
    bool snapping_on = false;
    bool topology_on = false;
    int layer_seq = 0;
    int task_seq = 0;
    bool shown = false;

    FakeProbe() {
        snap.bound = true;
        snap.window_min_width = 960;
        for (const char* key :
             {"nav", "inspector", "stage", "task", "agent", "hub",
              "composite_layer"}) {
            snap.docks[key] = QaDockState{true, 0, 0, 0};
        }
        recompute();
    }

    // ---- the evaluator/verdict model -------------------------------------

    void recompute() {
        snap.stage_marker_checked = {
            {"facies_calibration", stage == "facies_calibration"},
            {"constraint_factor", stage == "constraint_factor"},
            {"integrated_compilation",
             stage == "integrated_compilation"},
        };
        snap.stage_panel_shows_target = true;

        const FakeLayer* layer = nullptr;
        const auto it = layers.find(selected);
        if (it != layers.end()) layer = &it->second;
        const bool blocked = !blocking.empty();
        const bool raw =
            layer != nullptr &&
            (layer->role == lr::kInitialFaciesSource ||
             layer->role.rfind("factor_", 0) == 0);
        const bool frozen = layer != nullptr && layer->maturity == "frozen";
        const bool editable = layer != nullptr && !raw && !frozen;
        const bool line_kind = layer != nullptr && layer->kind == "line";

        for (const char* id :
             {"pan",      "layer_new",   "cancel",   "toggle_editing",
              "add_line", "add_polygon", "save_edits", "rollback",
              "undo",     "snapping",    "topology", "merge",
              "layer_properties", "layer_export", "symbology",
              "map_export"}) {
            QaToolVerdict& v = snap.availability[id];
            v.exists = true;
            v.enabled = true;
            v.preferred = false;
            v.checked = false;
            v.disabled_reason.clear();
        }
        snap.empty_hint_visible = false;
        snap.edit_chip_text.clear();
        snap.snapping_text = "捕捉: 关";
        snap.snapping_tooltip.clear();
        snap.crs_text.clear();
        snap.crs_tooltip.clear();
        snap.topology_chip_hidden = true;
        snap.topology_chip_text.clear();
        snap.preferred_button_present = false;
        snap.preferred_button_property = false;
        snap.availability["map_export"].enabled = false;
        snap.availability["map_export"].disabled_reason =
            "前置条件不满足：当前阶段不可导出";

        if (blocked) {
            const std::string reason =
                "后台任务进行中（" + blocking + "）";
            for (auto& [id, v] : snap.availability) {
                if (id != "cancel") {
                    v.enabled = false;
                    v.disabled_reason = reason;
                }
            }
        } else if (layer == nullptr) {
            QaToolVerdict& toggle = snap.availability["toggle_editing"];
            toggle.enabled = false;
            toggle.disabled_reason = "请先选择可编辑图层";
            snap.availability["add_line"].enabled = false;
            snap.availability["add_polygon"].enabled = false;
            snap.availability["save_edits"].enabled = false;
            snap.availability["rollback"].enabled = false;
            snap.availability["undo"].enabled = false;
            snap.empty_hint_visible = true;
        } else if (raw) {
            QaToolVerdict& toggle = snap.availability["toggle_editing"];
            toggle.enabled = false;
            toggle.disabled_reason = "RAW 图层不可编辑";
            snap.availability["add_line"].enabled = false;
            snap.availability["add_polygon"].enabled = false;
            snap.availability["add_polygon"].disabled_reason =
                "RAW 图层不可编辑";
            snap.availability["save_edits"].enabled = false;
            snap.availability["rollback"].enabled = false;
            snap.availability["undo"].enabled = false;
            snap.edit_chip_text = "RAW · 只读";
        } else if (frozen) {
            QaToolVerdict& toggle = snap.availability["toggle_editing"];
            toggle.enabled = false;
            toggle.disabled_reason = "图层已冻结（只读）";
            snap.availability["add_line"].enabled = false;
            snap.availability["add_polygon"].enabled = false;
            snap.availability["add_polygon"].disabled_reason = "图层已冻结";
            snap.availability["save_edits"].enabled = false;
            snap.availability["rollback"].enabled = false;
            snap.availability["undo"].enabled = false;
            snap.edit_chip_text = "已冻结";
        } else {
            // Editable layer: capture tools follow the target geometry —
            // a line role prefers add_line and blocks add_polygon.
            if (line_kind) {
                snap.availability["add_line"].enabled = true;
                snap.availability["add_line"].preferred = layer->editing;
                snap.availability["add_polygon"].enabled = false;
                snap.availability["add_polygon"].disabled_reason =
                    "当前编辑目标为线图层，仅线要素采集可用";
                if (layer->editing) {
                    snap.preferred_button_present = true;
                    snap.preferred_button_property = true;
                }
            } else {
                snap.availability["add_line"].enabled = false;
                snap.availability["add_polygon"].enabled = true;
            }
            if (layer->editing) {
                snap.availability["toggle_editing"].checked = true;
                if (layer->dirty) {
                    snap.edit_chip_text = "编辑中 ● 未保存";
                } else {
                    snap.availability["save_edits"].enabled = false;
                    snap.availability["rollback"].enabled = false;
                    snap.availability["undo"].enabled = false;
                    snap.edit_chip_text = "编辑中";
                }
            } else {
                snap.availability["save_edits"].enabled = false;
                snap.availability["save_edits"].disabled_reason =
                    "无未保存修改";
                snap.availability["rollback"].enabled = false;
                snap.availability["undo"].enabled = false;
            }
        }

        if (layer != nullptr && layer->topology_errors > 0) {
            snap.topology_chip_hidden = false;
            snap.topology_chip_text = "⚠ 拓扑问题 " +
                                      std::to_string(layer->topology_errors) +
                                      " 处";
            snap.availability["merge"].enabled = false;
            snap.availability["merge"].disabled_reason =
                "存在未处理的拓扑错误";
        }
        if (snapping_on) {
            snap.snapping_text = "捕捉: 开";
            snap.snapping_tooltip = "容差 10 px · 顶点+边";
            snap.availability["snapping"].enabled = true;
            snap.availability["snapping"].checked = true;
        }
        if (project_crs.empty()) {
            snap.crs_text = "CRS: 未声明";
            snap.availability["topology"].enabled = false;
            snap.availability["topology"].disabled_reason =
                "工程 CRS 未声明";
        } else if (layer != nullptr && !layer->crs.empty() &&
                   layer->crs != project_crs) {
            snap.crs_text = "⚠ " + layer->crs;
            snap.crs_tooltip = "图层 CRS 与工程 CRS 不一致";
        } else if (layer != nullptr && !layer->crs.empty()) {
            snap.crs_text = layer->crs;
        }

        // Actions mirror the verdicts (the real action_controller's
        // enabled state is evaluator-driven); stage filtering hides
        // add_line in phase 1.
        for (const char* id :
             {"pan", "toggle_editing", "add_line", "add_polygon",
              "save_edits", "snapping", "topology"}) {
            QaActionState& a = snap.actions[id];
            const QaToolVerdict& v = snap.availability[id];
            a.exists = true;
            a.visible = true;
            a.enabled = v.enabled;
            a.checked = v.checked;
            a.status_tip = v.disabled_reason;
        }
        snap.actions["add_line"].visible =
            (stage != "facies_calibration");
        snap.actions["add_polygon"].visible = true;
        if (editable && line_kind) {
            snap.actions["add_line"].tool_tip =
                "添加线要素\n当前编辑目标：" + layer->name;
        }
        if (snapping_on) {
            snap.actions["snapping"].tool_tip =
                "捕捉设置 · 容差 10 px";
        }

        snap.tree_status_joined.clear();
        for (const auto& [id, l] : layers) {
            if (l.maturity == "frozen") {
                if (!snap.tree_status_joined.empty())
                    snap.tree_status_joined += " | ";
                snap.tree_status_joined += "❄ 冻结";
            } else if (l.editing) {
                if (!snap.tree_status_joined.empty())
                    snap.tree_status_joined += " | ";
                snap.tree_status_joined +=
                    l.dirty ? "编辑中 ● 未保存" : "编辑中";
            }
        }
    }

    void apply_responsive(int w) {
        // The real window's responsive rules at the Python breakpoints.
        if (w <= 1000) {
            snap.docks["inspector"].hidden = true;
            snap.responsive_hid_inspector = true;
            snap.user_hid_inspector = false;
            snap.command_input_min_width = 220;
            snap.stage_label_visible = false;
            snap.docks["nav"].hidden = false;
            snap.composite_width = w - 480 > 300 ? w - 480 : 300;
        } else {
            snap.docks["inspector"].hidden = false;
            snap.responsive_hid_inspector = false;
            snap.command_input_min_width = 300;
            snap.stage_label_visible = true;
            snap.docks["nav"].hidden = false;
            snap.docks["composite_layer"].hidden = false;
            snap.composite_width =
                w >= 2560 ? 1800 : (w - 720 > 800 ? w - 720 : 800);
        }
        snap.canvas_width = snap.composite_width - 40;
    }

    // ---- VisualQaProbe ----------------------------------------------------

    void show_window() override {
        shown = true;
        if (snap.window_width == 0) {
            resize_window(kPrimeSize.width, kPrimeSize.height);
        }
    }
    void resize_window(int w, int h) override {
        snap.window_width = w;
        snap.window_height = h;
        apply_responsive(w);
    }
    void show_dock(QaDock dock) override {
        snap.docks[qa_qt::qa_dock_key(dock)].hidden = false;
    }
    void raise_dock(QaDock dock) override { show_dock(dock); }
    void resize_dock_horizontal(QaDock dock, int px) override {
        snap.docks[qa_qt::qa_dock_key(dock)].width = px;
    }
    void resize_dock_height(QaDock dock, int px) override {
        snap.docks[qa_qt::qa_dock_key(dock)].height = px;
    }

    void set_mapping_stage(const std::string& stage_value) override {
        stage = stage_value;
        recompute();
    }
    std::string add_layer(const qa_qt::QaLayerSpec& spec) override {
        const std::string id = "layer-" + std::to_string(++layer_seq);
        FakeLayer layer;
        layer.kind = spec.kind;
        layer.role = spec.role;
        layer.name = spec.name.empty() ? spec.role : spec.name;
        layers[id] = layer;
        selected = id;
        recompute();
        return id;
    }
    void select_layer(const std::string& layer_id) override {
        selected = layer_id;
        recompute();
    }
    void request_command(const std::string& command_id) override {
        if (command_id == "toggle_editing") {
            const auto it = layers.find(selected);
            if (it != layers.end()) {
                FakeLayer& layer = it->second;
                const bool raw =
                    layer.role == lr::kInitialFaciesSource ||
                    layer.role.rfind("factor_", 0) == 0;
                if (!raw && layer.maturity != "frozen" &&
                    blocking.empty()) {
                    layer.editing = true;
                }
            }
            recompute();
        } else if (command_id == "snapping") {
            snapping_on = true;
            recompute();
        } else if (command_id == "topology") {
            topology_on = true;
            recompute();
        } else if (command_id == "add_polygon" ||
                   command_id == "add_line") {
            QaActionState& tool = snap.actions[command_id];
            tool.exists = true;
            tool.visible = true;
            tool.checked = true;
            QaActionState& pan = snap.actions["pan"];
            pan.exists = true;
            pan.visible = true;
            pan.checked = false;
        }
    }
    bool add_edit_feature(
        const std::string& layer_id,
        const qa_qt::QaFeatureInsert&) override {
        const auto it = layers.find(layer_id);
        if (it == layers.end() || !it->second.editing) {
            return false;
        }
        it->second.dirty = true;
        recompute();
        return true;
    }
    void sync_action_state() override { recompute(); }
    void sync_composition_now() override { recompute(); }
    void set_maturity(const std::string& key,
                      const std::string& maturity) override {
        const std::size_t colon = key.rfind(':');
        const std::string layer_id =
            colon == std::string::npos ? key : key.substr(colon + 1);
        const auto it = layers.find(layer_id);
        if (it != layers.end()) {
            it->second.maturity = maturity;
            selected = layer_id;
        }
        recompute();
    }
    void set_blocking_task_label(const std::string& label) override {
        blocking = label;
        recompute();
    }
    void set_project_crs(const std::string& crs) override {
        project_crs = crs;
        recompute();
    }
    void set_layer_crs(const std::string& layer_id,
                       const std::string& crs) override {
        layers[layer_id].crs = crs;
        recompute();
    }
    void record_topology_validation(const std::string& layer_id,
                                    int error_count) override {
        layers[layer_id].topology_errors = error_count;
        recompute();
    }
    void emit_native_tool_activation_failed(
        const std::string& tool_id,
        const std::string& reason) override {
        snap.status_messages.push_back("工具 " + tool_id +
                                       " 激活失败：" + reason);
        QaActionState& pan = snap.actions["pan"];
        pan.exists = true;
        pan.visible = true;
        pan.checked = true;
        QaActionState& tool = snap.actions[tool_id];
        tool.exists = true;
        tool.visible = true;
        tool.checked = false;
    }
    void begin_status_capture() override {
        snap.status_messages.clear();
    }
    void build_canvas_menu() override {
        snap.canvas_menu_present = true;
        snap.canvas_menu_actions = {
            {"缩放到全图", "", true},
            {"捕捉设置", "snapping",
             snap.availability["snapping"].enabled},
            {"添加线要素", "add_line",
             snap.availability["add_line"].enabled},
            {"添加面要素", "add_polygon",
             snap.availability["add_polygon"].enabled},
        };
    }
    void build_write_grant_dialog(
        const std::vector<std::string>& action_ids) override {
        QaDialogSnapshot& d = snap.grab_dialog;
        d.present = true;
        d.object_name = "WriteGrantDialog";
        d.hidden = false;
        d.deny_present = true;
        d.deny_default = true;
        d.deny_text = "拒绝";
        d.grant_present = true;
        d.grant_text = "授权";
        d.granted = false;
        d.label_texts = {"写入动作授权"};
        for (const std::string& id : action_ids) {
            d.label_texts.push_back(id + " — 注册动作说明");
        }
    }

    std::string submit_task(
        const std::string&,
        std::function<void(qa_qt::QaTaskContext&)>) override {
        // The fake models scheduler bookkeeping only — the body
        // (cancellable_demo_task's 100 s run) is not executed; the
        // cancel claim-window state is what the checks read.
        const std::string id = "task-" + std::to_string(++task_seq);
        snap.task_handles.push_back(QaTaskHandle{id, "running", false});
        return id;
    }
    void cancel_task(const std::string& task_id) override {
        for (QaTaskHandle& h : snap.task_handles) {
            if (h.task_id == task_id) h.cancel_requested = true;
        }
    }

    void enforce_toolbar_rows() override {
        snap.map_top_in_top_area = true;
        snap.map_bottom_in_top_area = true;
        snap.overflow_toolbar_children = 0;
    }
    void inspect_layer_selection(const std::string& layer_id) override {
        const auto it = layers.find(layer_id);
        if (it == layers.end()) return;
        if (it->second.role.rfind("factor_", 0) == 0) {
            snap.inspector_header =
                "检查器 · 单因素成果 · " + it->second.name;
        } else {
            snap.inspector_header = "检查器 · " + it->second.name;
        }
    }
    void apply_layout_preset(const std::string& preset_id) override {
        // B-3 parity: presets change visibility, never dock geometry.
        snap.current_preset_id = preset_id;
    }
    void show_agent() override {
        snap.docks["agent"].hidden = false;
    }
    void show_hub_page(const std::string&) override {
        snap.docks["hub"].hidden = false;
        snap.docks["hub"].min_size_hint_width = 80;
        snap.hub_scroll_min_width = 80;
    }
    void refresh_ui_context() override {
        snap.workbench_label_text =
            "阶段② 约束与单因素 · 相带边界 · QGIS · 任务";
        snap.workbench_label_hidden = false;
    }
    void popup_palette() override {
        snap.palette_present = true;
        snap.palette_hidden = false;
    }
    void set_palette_filter(const std::string& text) override {
        snap.palette_items.clear();
        if (text == "单因素") {
            snap.palette_items = {
                {"阶段动作 · 单因素工作台", true, true,
                 "stage:constraint_factor:open_factor_workbench", ""},
                {"阶段动作 · 叠加单因素结果（当前阶段不可用）",
                 false, true,
                 "stage:constraint_factor:overlay_factor_results", ""},
            };
        } else if (text == "编图") {
            snap.palette_items = {
                {"编图 · 开始编辑", false, false, "map:toggle_editing",
                 ""},
                {"编图 · 导出图面（前置条件不满足）", false, false,
                 "map:map_export", ""},
            };
        }
    }
    void set_session_value(const std::string& key, int value) override {
        snap.session_values[key] = value;
    }

    WorkstationSnapshot collect() const override { return snap; }
};

// ---------------------------------------------------------------------------
// V11 seam fakes — the honest injected surfaces.
// ---------------------------------------------------------------------------

class FakeStageSurface : public qa_qt::QaStageSurface {
public:
    QWidget host;
    std::string stage = "facies_calibration";
    std::string horizon;
    // Real styled children so the theme-matrix grab sees non-degenerate
    // content like the real bar+panel composite (markers + horizon
    // label + constraints row) — the snapshot facts still model the
    // seam contract, but the widget is a plausible stand-in.
    std::vector<QPushButton*> markers;
    QLabel* horizon_label = nullptr;
    QPushButton* constraints_row = nullptr;

    FakeStageSurface() {
        auto* layout = new QVBoxLayout(&host);
        auto* row = new QHBoxLayout();
        const std::vector<std::string> labels = {
            "① 智能预测", "② 约束与单因素", "③ 综合编图"};
        for (const std::string& label : labels) {
            auto* b = new QPushButton(
                QString::fromUtf8(label.data(),
                                  static_cast<qsizetype>(label.size())),
                &host);
            b->setCheckable(true);
            markers.push_back(b);
            row->addWidget(b);
        }
        layout->addLayout(row);
        horizon_label = new QLabel(QStringLiteral("层位 —"), &host);
        layout->addWidget(horizon_label);
        constraints_row =
            new QPushButton(QStringLiteral("新建地质约束"), &host);
        layout->addWidget(constraints_row);
        // The real composite fills the dock — two stretched panels with
        // child-level styles keep the themed grab non-degenerate at any
        // sample stride (the parent's theme QSS does not override
        // child-level stylesheets).
        auto* fill_row = new QHBoxLayout();
        auto* panel_a = new QFrame(&host);
        panel_a->setStyleSheet(
            QStringLiteral("background:#12141C;color:#F0F0F0;"));
        auto* panel_b = new QFrame(&host);
        panel_b->setStyleSheet(
            QStringLiteral("background:#E8EAF0;color:#1A1C24;"));
        fill_row->addWidget(panel_a, 1);
        fill_row->addWidget(panel_b, 1);
        layout->addLayout(fill_row, 1);
        markers[0]->setChecked(true);
        host.resize(720, 320);
    }

    QWidget* widget() override { return &host; }
    void set_horizon_state(
        const std::string& current,
        const std::vector<std::string>&) override {
        horizon = current;
        horizon_label->setText(
            QString::fromUtf8(("层位 " + current).data(),
                              static_cast<qsizetype>(
                                  ("层位 " + current).size())));
    }
    void set_stage(const std::string& stage_value) override {
        stage = stage_value;
        int index = 0;
        for (const pwb::tool_policy::MappingStage s :
             pwb::tool_policy::kStageOrder) {
            markers[index]->setChecked(
                stage == pwb::tool_policy::stage_value(s));
            ++index;
        }
    }
    QaStageSurfaceSnapshot snapshot() const override {
        QaStageSurfaceSnapshot snap;
        int index = 0;
        for (const pwb::tool_policy::MappingStage s :
             pwb::tool_policy::kStageOrder) {
            snap.stage_marker_checked[pwb::tool_policy::stage_value(s)] =
                markers[index]->isChecked();
            ++index;
        }
        snap.stage_panel_shows_target = true;
        snap.current_horizon = horizon;
        snap.constraints_row_visible = (stage == "constraint_factor");
        return snap;
    }
};

class FakeShellSurface : public qa_qt::QaShellSurface {
public:
    QWidget host;
    QWidget* widget() override { return &host; }
    QaShellSnapshot snapshot() const override {
        QaShellSnapshot snap;
        snap.workstation_present = true;
        snap.inspector_header = "检查器 · 工程";
        snap.inspector_current_is_project = true;
        snap.task_center_rows = 0;
        snap.project_wells = 0;
        snap.project_resources = 0;
        return snap;
    }
};

class FakeDataPageSurface : public qa_qt::QaDataPageSurface {
public:
    QWidget host;
    int selected_asset = -1;
    QWidget* widget() override { return &host; }
    int resource_count() const override { return 5; }
    void refresh() override {}
    void select_asset(int index) override { selected_asset = index; }
    QaDataManagerSnapshot snapshot() const override {
        QaDataManagerSnapshot snap;
        snap.asset_rows = 5;
        snap.resource_count = 5;
        snap.inspector_title =
            selected_asset >= 0 ? "检查器 · A12.las" : "";
        snap.inspector_empty_hidden = selected_asset >= 0;
        snap.inspector_tabs_hidden = false;
        return snap;
    }
};

// The stage_vocabulary.py parity table — injected through the seam (the
// vocabulary itself is unported domain data; the test fixture mirrors it).
std::vector<qa_qt::QaStageActionSpec> python_stage_actions() {
    using S = qa_qt::QaStageActionSpec;
    return {
        S{"constraint_factor", "open_factor_workbench", "单因素工作台",
          "factor_workbench"},
        S{"constraint_factor", "overlay_factor_results",
          "叠加单因素结果", "factor_overlay"},
        S{"constraint_factor", "commit_constraints", "提交约束版本", ""},
        S{"constraint_factor", "stage_save", "保存阶段成果", ""},
        S{"facies_calibration", "add_seismic_prediction_overlay",
          "叠加地震相预测", ""},
        S{"facies_calibration", "load_initial_facies", "加载初始相图",
          ""},
        S{"facies_calibration", "create_facies_draft", "创建解释草稿",
          ""},
        S{"facies_calibration", "stage_save", "保存阶段成果", ""},
        S{"integrated_compilation", "run_qa", "运行 QA", "qa_run"},
        S{"integrated_compilation", "assemble_map_product",
          "生成 MapProduct", "map_product_assemble"},
    };
}

qa_qt::ScenarioSeams full_seams() {
    qa_qt::ScenarioSeams seams;
    seams.shell_factory = [] {
        return std::make_unique<FakeShellSurface>();
    };
    seams.data_page_factory = [] {
        return std::make_unique<FakeDataPageSurface>();
    };
    seams.stage_surface_factory = [] {
        return std::make_unique<FakeStageSurface>();
    };
    seams.stage_actions = python_stage_actions();
    return seams;
}

}  // namespace

// ---------------------------------------------------------------------------
// Drive-recipe seam coverage
// ---------------------------------------------------------------------------

PWB_TEST(drive_dispatch_covers_all_states) {
    FakeProbe probe;
    for (const std::string& state : all_v6_v10_states()) {
        CHECK(drive_state(state, probe));
    }
    CHECK(!drive_state("no_such_state", probe));
}

PWB_TEST(unbound_probe_fails_closed) {
    FakeProbe probe;
    probe.snap.bound = false;
    const std::vector<CheckResult> results =
        qa_qt::run_state_checks("mapping_stage_phase1", probe);
    CHECK_EQ(results.size(), 1u);
    CHECK(!results[0].ok);
}

PWB_TEST(v6_drives_pass_end_to_end) {
    FakeProbe probe;
    drive_state("mapping_stage_phase1", probe);
    CHECK(all_ok(qa_qt::run_state_checks("mapping_stage_phase1", probe)));
    drive_state("mapping_stage_phase2", probe);
    CHECK(all_ok(qa_qt::run_state_checks("mapping_stage_phase2", probe)));
    drive_state("mapping_stage_phase3", probe);
    CHECK(all_ok(qa_qt::run_state_checks("mapping_stage_phase3", probe)));
}

PWB_TEST(v6_dialog_status_palette_drives) {
    {
        FakeProbe probe;
        drive_state("command_palette_context", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("command_palette_context", probe)));
    }
    {
        FakeProbe probe;
        drive_state("write_grant_dialog", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("write_grant_dialog", probe)));
    }
    {
        FakeProbe probe;
        drive_state("status_workbench_segment", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("status_workbench_segment", probe)));
    }
}

PWB_TEST(v7_drives_pass_end_to_end) {
    {
        FakeProbe probe;
        drive_state("phase1_raw_blocked", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("phase1_raw_blocked", probe)));
    }
    {
        FakeProbe probe;
        drive_state("phase1_editing_session", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("phase1_editing_session", probe)));
    }
    {
        FakeProbe probe;
        drive_state("phase2_constraint_line", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("phase2_constraint_line", probe)));
    }
    {
        FakeProbe probe;
        drive_state("phase2_factor_raster", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("phase2_factor_raster", probe)));
    }
    {
        FakeProbe probe;
        drive_state("layer_tree_decorations", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("layer_tree_decorations", probe)));
    }
    {
        FakeProbe probe;
        drive_state("task_cancelling", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("task_cancelling", probe)));
    }
    {
        FakeProbe probe;
        drive_state("toolbar_overflow_narrow", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("toolbar_overflow_narrow", probe)));
    }
    {
        FakeProbe probe;
        drive_state("inspector_factor", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("inspector_factor", probe)));
    }
}

PWB_TEST(v8_drives_pass_end_to_end) {
    {
        FakeProbe probe;
        drive_state("empty_project_tool_surface", probe);
        CHECK(all_ok(qa_qt::run_state_checks("empty_project_tool_surface",
                                             probe)));
    }
    {
        FakeProbe probe;
        drive_state("derived_polygon_editing_dirty", probe);
        CHECK(all_ok(qa_qt::run_state_checks(
            "derived_polygon_editing_dirty", probe)));
    }
    {
        FakeProbe probe;
        drive_state("frozen_map_product", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("frozen_map_product", probe)));
    }
    {
        FakeProbe probe;
        drive_state("palette_disabled_reason", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("palette_disabled_reason", probe)));
    }
    {
        FakeProbe probe;
        drive_state("native_activation_failure_revert", probe);
        CHECK(all_ok(qa_qt::run_state_checks(
            "native_activation_failure_revert", probe)));
    }
    {
        FakeProbe probe;
        drive_state("blocking_task_tool_surface", probe);
        CHECK(all_ok(qa_qt::run_state_checks(
            "blocking_task_tool_surface", probe)));
    }
}

PWB_TEST(v9_drives_pass_end_to_end) {
    {
        FakeProbe probe;
        drive_state("compact_viewport", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("compact_viewport", probe)));
    }
    {
        FakeProbe probe;
        drive_state("wide_viewport", probe);
        CHECK(all_ok(qa_qt::run_state_checks("wide_viewport", probe)));
    }
    {
        FakeProbe probe;
        drive_state("ultrawide_viewport", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("ultrawide_viewport", probe)));
    }
    {
        FakeProbe probe;
        drive_state("narrow_hub_page", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("narrow_hub_page", probe)));
    }
    {
        FakeProbe probe;
        drive_state("preset_visibility_only", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("preset_visibility_only", probe)));
    }
    {
        FakeProbe probe;
        drive_state("agent_grow_only", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("agent_grow_only", probe)));
    }
}

PWB_TEST(v10_drives_pass_end_to_end) {
    {
        FakeProbe probe;
        drive_state("raw_layer_readonly_surface", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("raw_layer_readonly_surface", probe)));
    }
    {
        FakeProbe probe;
        drive_state("capture_preferred_line_role", probe);
        CHECK(all_ok(qa_qt::run_state_checks(
            "capture_preferred_line_role", probe)));
    }
    {
        FakeProbe probe;
        drive_state("editing_dirty_chip", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("editing_dirty_chip", probe)));
    }
    {
        FakeProbe probe;
        drive_state("snapping_detail_surface", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("snapping_detail_surface", probe)));
    }
    {
        FakeProbe probe;
        drive_state("topology_error_chip", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("topology_error_chip", probe)));
    }
    {
        FakeProbe probe;
        drive_state("crs_undeclared_surface", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("crs_undeclared_surface", probe)));
    }
    {
        FakeProbe probe;
        drive_state("crs_mismatch_warning", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("crs_mismatch_warning", probe)));
    }
    {
        FakeProbe probe;
        drive_state("frozen_layer_surface", probe);
        CHECK(all_ok(
            qa_qt::run_state_checks("frozen_layer_surface", probe)));
    }
    {
        FakeProbe probe;
        drive_state("canvas_context_menu_surface", probe);
        CHECK(all_ok(qa_qt::run_state_checks(
            "canvas_context_menu_surface", probe)));
    }
    {
        FakeProbe probe;
        drive_state("compact_1366_toolbar_identity", probe);
        CHECK(all_ok(qa_qt::run_state_checks(
            "compact_1366_toolbar_identity", probe)));
    }
}

// ---------------------------------------------------------------------------
// V11 scenario host — real widgets + injected seams
// ---------------------------------------------------------------------------

PWB_TEST(scenario_dispatch_covers_all) {
    const qa_qt::ScenarioSeams seams = full_seams();
    for (const std::string& name : v11_scenarios()) {
        std::unique_ptr<qa_qt::ScenarioHandle> handle =
            qa_qt::build_scenario(name, seams);
        CHECK(handle != nullptr);
        CHECK(handle->widget() != nullptr);
    }
}

PWB_TEST(unknown_scenario_throws) {
    bool threw = false;
    try {
        (void)qa_qt::build_scenario("no_such_scenario", {});
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
}

PWB_TEST(unbound_seams_report_unavailable) {
    // No seams: the seam-backed scenarios report honest unavailability
    // instead of fabricating surfaces (non-gating parity).
    for (const std::string& name :
         {"first_open_empty_shell", "data_manager_surface",
          "stage_bar_phase1", "stage_bar_phase2", "stage_bar_phase3",
          "theme_matrix_smoke"}) {
        std::unique_ptr<qa_qt::ScenarioHandle> handle =
            qa_qt::build_scenario(name, {});
        CHECK(handle != nullptr);
        CHECK(!handle->available());
        CHECK(!handle->unavailable_reason().empty());
        const std::vector<CheckResult> results =
            qa_qt::run_scenario_checks(name, *handle);
        CHECK_EQ(results.size(), 1u);
        CHECK(!results[0].ok);
    }
}

PWB_TEST(seam_backed_scenarios_pass) {
    const qa_qt::ScenarioSeams seams = full_seams();
    for (const std::string& name :
         {"first_open_empty_shell", "data_manager_surface",
          "stage_bar_phase1", "stage_bar_phase2", "stage_bar_phase3"}) {
        std::unique_ptr<qa_qt::ScenarioHandle> handle =
            qa_qt::build_scenario(name, seams);
        CHECK(handle->available());
        const std::vector<CheckResult> results =
            qa_qt::run_scenario_checks(name, *handle);
        if (!all_ok(results)) {
            for (const CheckResult& r : results) {
                if (!r.ok) {
                    std::fprintf(stderr,
                                 "  %s failed check %s: %s\n",
                                 name, r.name.c_str(), r.detail.c_str());
                }
            }
        }
        CHECK(all_ok(results));
    }
}

PWB_TEST(real_widget_scenarios_pass) {
    // These builders construct the real ported widgets — no seams.
    for (const std::string& name :
         {"well_task_workflow_panel", "seismic_context_surface",
          "inspector_version_payload", "inspector_run_payload",
          "task_center_operations", "error_empty_states_composite"}) {
        std::unique_ptr<qa_qt::ScenarioHandle> handle =
            qa_qt::build_scenario(name, {});
        CHECK(handle->available());
        const std::vector<CheckResult> results =
            qa_qt::run_scenario_checks(name, *handle);
        if (!all_ok(results)) {
            for (const CheckResult& r : results) {
                if (!r.ok) {
                    std::fprintf(stderr,
                                 "  %s failed check %s: %s\n",
                                 name, r.name.c_str(), r.detail.c_str());
                }
            }
        }
        CHECK(all_ok(results));
    }
}

PWB_TEST(palette_scenario_with_stage_vocabulary) {
    qa_qt::ScenarioSeams seams;
    seams.stage_actions = python_stage_actions();
    std::unique_ptr<qa_qt::ScenarioHandle> handle =
        qa_qt::build_scenario("command_palette_disabled_reason", seams);
    CHECK(handle->available());
    const std::vector<CheckResult> results = qa_qt::run_scenario_checks(
        "command_palette_disabled_reason", *handle);
    for (const CheckResult& r : results) {
        if (!r.ok) {
            std::fprintf(stderr, "  palette failed check %s: %s\n",
                         r.name.c_str(), r.detail.c_str());
        }
    }
    CHECK(all_ok(results));
    // Honest empty vocabulary: no stage commands registered -> the
    // stage-scoped check can never pass on map:* rows alone (their
    // specs carry no stage whitelist); the run reports honestly.
    std::unique_ptr<qa_qt::ScenarioHandle> bare =
        qa_qt::build_scenario("command_palette_disabled_reason", {});
    const std::vector<CheckResult> bare_results =
        qa_qt::run_scenario_checks("command_palette_disabled_reason",
                                   *bare);
    CHECK(!all_ok(bare_results));
}

PWB_TEST(theme_matrix_renders) {
    const qa_qt::ScenarioSeams seams = full_seams();
    std::unique_ptr<qa_qt::ScenarioHandle> handle =
        qa_qt::build_scenario("theme_matrix_smoke", seams);
    CHECK(handle->available());
    ScenarioSnapshot snapshot;
    handle->collect(snapshot);
    CHECK_EQ(snapshot.theme_renders.size(), 4u);
    const std::vector<CheckResult> results =
        qa_qt::run_scenario_checks("theme_matrix_smoke", *handle);
    for (const CheckResult& r : results) {
        if (!r.ok) {
            std::fprintf(stderr, "  theme failed check %s: %s\n",
                         r.name.c_str(), r.detail.c_str());
        }
    }
    CHECK(all_ok(results));
}

// ---------------------------------------------------------------------------
// Dual-volume prototype shell
// ---------------------------------------------------------------------------

PWB_TEST(dual_volume_window_smoke) {
    qa_qt::ProtoDualVolumeWindow window;
    window.resize(900, 700);
    window.show();
    qa_qt::settle(50);
    qa_qt::DualVolumeOverlayWidget* canvas = window.canvas();
    CHECK(canvas != nullptr);
    CHECK(window.axis_combo() != nullptr);
    CHECK_EQ(window.axis_combo()->count(), 3);
    CHECK(window.slice_slider() != nullptr);
    CHECK(window.opacity_slider() != nullptr);
    CHECK(window.threshold_slider() != nullptr);

    // All three dims are 200 — the slider range stays 0..199 on every
    // axis; the axis switch drives set_slice with the current index.
    window.axis_combo()->setCurrentIndex(0);
    qa_qt::settle(20);
    CHECK_EQ(canvas->axis(), kAxisInline);

    // Variant switch + slider drives update_render like the Python
    // setters.
    canvas->set_variant(QStringLiteral(
        "Variant C: Coherence Masking Overlay"));
    canvas->set_slice(kAxisInline, 5);
    canvas->set_opacity(0.75);
    canvas->set_threshold(0.4);
    CHECK_EQ(canvas->axis(), kAxisInline);
    CHECK_EQ(canvas->slice_index(), 5);
    CHECK(canvas->last_render_ms() >= 0.0);
    const QPixmap shot = window.grab();
    CHECK(!shot.isNull());
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    return pwb_test::run_all();
}
