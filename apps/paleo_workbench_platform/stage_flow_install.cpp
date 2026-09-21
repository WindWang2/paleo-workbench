// V14-THREE-STAGE-UX — three-stage workbench install (named block member
// functions of MainWindow; declared under PWB_WITH_STAGE_FLOW in
// main_window.hpp).
//
// What this slice wires (one composition point, no second authorities):
//  1. Mounts the (previously orphan) CompositeDocument::stage_bar on the
//     WorkstationFrame app-bar row — the top-of-window stage switch.
//  2. StageFlowController: seams to ProjectSession (stage) + the project
//     document stratigraphy (horizon); per-stage layout profiles applied
//     through WorkstationFrame docks / MappingPage panels / MainWindow
//     docks; per-stage user preferences persisted in QSettings
//     (stage_presentation/ group, version-fenced).
//  3. Production command registrations into ui_shell::command_registry()
//     — the palette registry was an empty shell in the product build.
//  4. TaskCenter providers: JobCenter scheduler snapshots + the global
//     operation registry; cancel routes through the scheduler.
//  5. Selection/focus bus: one QtSelectionContext + ViewCoordination-
//     Controller per window (PWB_WITH_UI_CONTROLLERS), project-bound on
//     open and cleared when the session store detaches.
//
// GUI-thread only. Idempotent.

#include "main_window.hpp"

#include <cstring>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <QDockWidget>
#include <QSettings>
#include <QStatusBar>
#include <QString>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/application/project_session.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui/stage_readiness.hpp>
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_composite/mapping_stage_bar.hpp>
#include <pwb/ui_map/map_dock_manager.hpp>
#include <pwb/ui_map/mapping_page.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/operation_registry.hpp>
#include <pwb/ui_stageflow/qt/stage_flow_controller.hpp>
#include <pwb/ui_workstation/task_center.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>
#include <pwb/workspace/state.hpp>

#include "app_context.hpp"
#include "app_shell.hpp"
#include "job_center.hpp"

#ifdef PWB_WITH_CONV_16
#include "factor_stats_dock.hpp"
#endif

#ifdef PWB_WITH_CLOSURE_MAPPING
#include "closure_mapping_document.hpp"
#include "closure_mapping_install.hpp"
#endif

#ifdef PWB_WITH_UI_CONTROLLERS
#include <pwb/ui_controllers/qt/view_coordination_controller.hpp>
#endif

namespace pwb::app {

#ifdef PWB_WITH_STAGE_FLOW

namespace {

using StageFlowController = pwb::ui_stageflow::qt::StageFlowController;
using ui_stageflow::kStage1Value;
using ui_stageflow::kStage2Value;
using ui_stageflow::kStage3Value;

// The authoritative stage write. With the CONV-27 workbench closure in
// the build this is MainWindow::applyStageValue (canonicalize + stage
// dock + actions + readiness refresh); a reduced configure writes the
// same ProjectSession authority directly — canonicalized identically.
inline void apply_stage_authority(MainWindow& window,
                                  const std::string& value) {
#ifdef PWB_WITH_CONV_27
    window.applyStageValue(value);
#else
    const auto stage = pwb::tool_policy::stage_from_value(value);
    if (!stage.has_value()) return;
    window.session()->set_mapping_stage(
        pwb::tool_policy::stage_value(*stage));
#endif
}

// The production command set. Every callback routes through the SAME
// implementations the UI surfaces use (request_stage / navigate_to /
// dock toggles) — no parallel action paths.
struct CommandSeed {
    const char* id;
    const char* label;
    const char* hint;
    const char* keywords;
    const char* group;
    const char* shortcut_hint;  // "" = none
    std::vector<std::string> stages;  // empty = all stages
    bool requires_project;
};

const std::vector<CommandSeed>& command_seeds() {
    static const std::vector<CommandSeed> seeds = {
        {"stage.goto.prediction", "切换到 ① 智能预测",
         "进入智能预测阶段（沉积相智能预测上下文）",
         "阶段 stage 预测 prediction 一", "阶段", "1", {}, false},
        {"stage.goto.constraints", "切换到 ② 约束与单因素",
         "进入约束与单因素分析阶段", "阶段 stage 约束 constraint 因素 二",
         "阶段", "2", {}, false},
        {"stage.goto.compilation", "切换到 ③ 综合编图",
         "进入综合编图阶段", "阶段 stage 综合 compilation 编图 三",
         "阶段", "3", {}, false},
        {"nav.hub.data", "打开 数据 页", "切到数据工作区",
         "导航 页面 data 数据", "导航", "", {}, false},
        {"nav.hub.wells", "打开 井 页", "切到井/测井工作区",
         "导航 页面 well 井 测井", "导航", "", {}, false},
        {"nav.hub.seismic", "打开 地震 页", "切到地震工作区",
         "导航 页面 seismic 地震", "导航", "", {}, false},
        {"nav.hub.mapping", "打开 编图 页", "切到编图工作区",
         "导航 页面 mapping 编图", "导航", "", {}, false},
        {"nav.hub.viz", "打开 可视化 页", "切到可视化工作区",
         "导航 页面 viz 可视化", "导航", "", {}, false},
        {"panel.toggle.tasks", "任务中心 开/关", "显示或隐藏任务中心",
         "面板 任务 task center 后台", "面板", "", {}, false},
        {"panel.toggle.agent", "Agent 面板 开/关", "显示或隐藏 Agent 面板",
         "面板 agent 助手", "面板", "", {}, false},
        {"panel.toggle.logs", "日志 开/关", "显示或隐藏日志面板",
         "面板 日志 log", "面板", "", {}, false},
        {"panel.toggle.console", "控制台 开/关", "显示或隐藏控制台",
         "面板 console 控制台", "面板", "", {}, false},
        // (no panel.toggle.layers: the mapping page registers
        // reference/chrome/composer/bottom only; the workstation's own
        // layer dock is composite_layer — an always-on surface the
        // profiles deliberately do not manage.)
        {"panel.toggle.reference", "参考图面板 开/关", "编图画布的参考图面板",
         "面板 reference 参考", "面板", "", {kStage2Value, kStage3Value},
         false},
        {"panel.toggle.composer", "组图面板 开/关", "综合编图的组图面板",
         "面板 composer 组图", "面板", "", {kStage3Value}, false},
        {"panel.toggle.bottom", "底部工作台 开/关", "编图画布的底部工作台",
         "面板 bottom 底部 工作台", "面板", "", {kStage2Value, kStage3Value},
         false},
        {"stage.reset_layout", "恢复本阶段默认布局",
         "清除本阶段的布局偏好，回到阶段默认", "布局 reset 恢复 默认",
         "阶段", "", {}, false},
    };
    return seeds;
}

// Which hub index a nav command addresses (submodule keys mirror
// ui_shell/navigation.cpp registration order).
struct NavTarget {
    int hub;
    const char* subkey;
};
const std::map<std::string, NavTarget>& nav_targets() {
    static const std::map<std::string, NavTarget> targets = {
        {"nav.hub.data", {0, "overview"}},
        {"nav.hub.wells", {1, "well_log"}},
        {"nav.hub.seismic", {2, "seismic"}},
        {"nav.hub.mapping", {3, "canvas"}},
        {"nav.hub.viz", {4, ""}},
    };
    return targets;
}

}  // namespace

// ---------------------------------------------------------------------------
// Per-stage visibility application
// ---------------------------------------------------------------------------

void MainWindow::applyStageVisibility(
    const std::map<std::string, bool>& visibility) {
    AppShell* shell = appShell();
    if (shell == nullptr) return;
    auto* workstation = shell->workstation();
    if (workstation != nullptr) {
        constexpr std::string_view prefix = "workstation.";
        for (const auto& [key, visible] : visibility) {
            if (!key.starts_with(prefix)) continue;
            const std::string dock_id = key.substr(prefix.size());
            // Absent docks (capability-off degrade) are skipped, not
            // errors — honest degradation, never a crash.
            if (workstation->dock(dock_id) != nullptr) {
                workstation->set_dock_visible(dock_id, visible);
            }
        }
    }
    if (auto* page = shell->mapping_page()) {
        auto* manager = page->dock_manager();
        if (manager != nullptr) {
            constexpr std::string_view prefix = "mapping.";
            for (const auto& [key, visible] : visibility) {
                if (!key.starts_with(prefix)) continue;
                manager->set_panel_visible(key.substr(prefix.size()), visible);
            }
        }
    }
    constexpr std::string_view prefix = "window.";
    for (const auto& [key, visible] : visibility) {
        if (!key.starts_with(prefix)) continue;
        const std::string dock_key = key.substr(prefix.size());
        QDockWidget* dock = nullptr;
        if (dock_key == "constraint_panel") {
#ifdef PWB_WITH_CONV_27
            dock = constraint_dock_;
#endif
        } else if (dock_key == "factor_stats") {
#ifdef PWB_WITH_CONV_16
            dock = factor_dock_;
#endif
        }
        if (dock != nullptr) dock->setVisible(visible);
    }
}

// ---------------------------------------------------------------------------
// Stage restore from the project document
// ---------------------------------------------------------------------------

void MainWindow::restoreStageFromProject() {
#ifdef PWB_WITH_DATA_INTEGRATION
    const auto store = context_.projectStore();
    if (store == nullptr) return;
    // Const read: the non-const mapping_workspace() INSERTS an empty
    // object into the live document when the section is absent (an
    // unlocked mutation this restore path must not make).
    const pwb::project::ProjectDocument& document = store->document();
    domain::DiagnosticList diagnostics;
    const pwb::workspace::MappingWorkspaceState state =
        pwb::workspace::MappingWorkspaceState::from_json(
            document.mapping_workspace(), diagnostics);
    // The authority write canonicalizes and (with the CONV-27 closure)
    // refreshes dock/readiness/actions; an unknown persisted value was
    // already lenient-fallbacked to stage 1 by the codec (state.cpp).
    apply_stage_authority(*this, state.current_stage);
    if (stage_flow_ != nullptr) stage_flow_->refresh();

    // Selection bus project token: (re)bind on open.
#ifdef PWB_WITH_UI_CONTROLLERS
    if (stage_flow_coordination_ != nullptr) {
        stage_flow_coordination_->bind_project(store->document());
    }
#endif
#endif
}

// ---------------------------------------------------------------------------
// Install
// ---------------------------------------------------------------------------

void MainWindow::installStageFlow() {
    if (stage_flow_ != nullptr) return;  // idempotent
    AppShell* shell = appShell();
    if (shell == nullptr) return;
    auto* workstation = shell->workstation();
    auto* composite = shell->composite();
    if (workstation == nullptr || composite == nullptr) return;

#ifdef PWB_WITH_DATA_INTEGRATION
    // V14 constraint authoring (#1446): the stage panel's eight
    // constraint buttons used to emit constraint_requested with no
    // consumer — dead UI on the flagship Stage-2 surface. Route them to
    // the production creation path (constraint_authoring.cpp).
    connect(composite,
            &pwb::ui_composite::CompositeDocument::constraint_requested,
            this, &MainWindow::createStageConstraint);
#endif

    // -- controller + persistence sink --------------------------------------
    // buildUi() runs BEFORE the constructor's platform-services stage
    // binds services_settings_ (injected or owned fallback) — at install
    // time the member may still be null. The sink resolves the pointer
    // lazily per call; after the constructor completes it is always valid,
    // and the null guard keeps pre-bind calls honest.
    pwb::ui_stageflow::StagePreferenceSink sink;
    sink.load = [this](const std::string& key) -> std::optional<std::string> {
        QSettings* settings = services_settings_;
        if (settings == nullptr) return std::nullopt;
        const QVariant value = settings->value(
            QString::fromStdString("stage_presentation/" + key));
        if (!value.isValid()) return std::nullopt;
        return value.toString().toStdString();
    };
    sink.save = [this](const std::string& key,
                       const std::string& value) {
        if (services_settings_ == nullptr) return;
        services_settings_->setValue(
            QString::fromStdString("stage_presentation/" + key),
            QString::fromStdString(value));
    };

    stage_flow_ = new StageFlowController(std::move(sink), this);

    // -- seams ----------------------------------------------------------------
    StageFlowController::Seams seams;
    seams.read_stage = [this]() -> std::optional<std::string> {
        return context_.session().mapping_stage();
    };
    seams.apply_stage = [this](const std::string& value) {
        apply_stage_authority(*this, value);
    };
    seams.read_horizon = [this]() -> std::optional<std::string> {
#ifdef PWB_WITH_DATA_INTEGRATION
        const auto store = context_.projectStore();
        if (store == nullptr) return std::nullopt;
        const pwb::domain::Json stratigraphy =
            store->coordinator().document_section(
                "stratigraphy", store->document());
        if (stratigraphy.contains("target_horizon")
            && stratigraphy["target_horizon"].is_string()) {
            return stratigraphy["target_horizon"].get<std::string>();
        }
#endif
        return std::nullopt;
    };
    seams.apply_horizon = [this](const std::string& horizon) {
#ifdef PWB_WITH_DATA_INTEGRATION
        const auto store = context_.projectStore();
        if (store == nullptr) return;
        // Serialized section mutation: the raw root write this replaced
        // raced worker publishes on the same JSON tree (the read twin
        // document_section documents that lock contract). Persistence
        // rides the next project save (workspace-mutations contract).
        pwb::domain::Json stratigraphy =
            store->coordinator().document_section(
                "stratigraphy", store->document());
        if (!stratigraphy.is_object()) {
            stratigraphy = pwb::domain::Json::object();
        }
        stratigraphy["target_horizon"] = horizon;
        store->coordinator().set_document_section(
            "stratigraphy", stratigraphy, store->document());
        statusBar()->showMessage(
            tr("目标层位已设为 %1（随工程保存生效）")
                .arg(QString::fromStdString(horizon)),
            8000);
#endif
    };
    seams.apply_visibility = [this](const std::map<std::string, bool>& vis) {
        applyStageVisibility(vis);
    };
    seams.project_open = [this]() {
        return context_.session().store() != nullptr;
    };
    seams.write_granted = [this]() {
        return context_.session().snapshot().write_granted;
    };
    seams.running_tasks = [this]() {
#ifdef PWB_WITH_CONV_30
        return static_cast<int>(job_center_->scheduler().statuses().size());
#else
        return 0;
#endif
    };
    seams.readiness = [this]() -> pwb::ui_stageflow::StageReadinessKind {
#ifdef PWB_WITH_CONV_27
        const auto& stage = context_.session().mapping_stage();
        const auto parsed = pwb::tool_policy::stage_from_value(
            stage.value_or(""));
        if (!parsed.has_value()) {
            return pwb::ui_stageflow::StageReadinessKind::Unknown;
        }
        const auto readiness =
            pwb::ui::evaluate_stage_readiness(*parsed, readiness_inputs());
        switch (readiness.status()) {
            case pwb::ui::StageReadinessStatus::Ready:
                return pwb::ui_stageflow::StageReadinessKind::Ready;
            case pwb::ui::StageReadinessStatus::ReadyWithWarnings:
                return pwb::ui_stageflow::StageReadinessKind::ReadyWithWarnings;
            case pwb::ui::StageReadinessStatus::NotReady:
                return pwb::ui_stageflow::StageReadinessKind::NotReady;
        }
#endif
        // Reduced configure (no CONV-27 workbench closure): the readiness
        // evaluator's inputs are not collected — report the honest
        // unknown instead of fabricating a verdict.
        return pwb::ui_stageflow::StageReadinessKind::Unknown;
    };
    stage_flow_->set_seams(std::move(seams));

    // -- stage bar mount (the orphan becomes the top stage switch) -----------
    if (composite->stage_bar != nullptr &&
        workstation->mount_top_bar(composite->stage_bar)) {
        auto* bar = composite->stage_bar;
        connect(bar, &pwb::ui_composite::MappingStageBar::stage_requested, this,
                [this](const QString& value) {
                    if (stage_flow_ != nullptr) {
                        stage_flow_->request_stage(value.toStdString());
                    }
                });
        connect(bar, &pwb::ui_composite::MappingStageBar::horizon_requested, this,
                [this](const QString& horizon) {
                    if (stage_flow_ != nullptr) {
                        stage_flow_->request_horizon(horizon.toStdString());
                    }
                });
        connect(stage_flow_, &StageFlowController::stage_applied, bar,
                [bar](const QString& value) {
                    bar->set_current_stage(value.toStdString());
                });
        connect(stage_flow_, &StageFlowController::snapshot_changed, bar,
                [this, bar]() {
                    const auto& snap = stage_flow_->snapshot();
                    // Empty horizon (project without stratigraphy) clears
                    // the combo — a stale horizon must not survive a
                    // project switch.
                    bar->set_horizon_state(
                        snap.horizon.has_value()
                            ? QString::fromStdString(*snap.horizon)
                            : QString());
                });
    }

    // -- production commands (the palette registry leaves its empty shell) ---
    auto& registry = pwb::ui_shell::command_registry();
    int registered = 0;
    for (const CommandSeed& seed : command_seeds()) {
        pwb::ui_shell::CommandSpec spec;
        spec.id = seed.id;
        spec.label = seed.label;
        spec.hint = seed.hint;
        spec.keywords = seed.keywords;
        spec.group = seed.group;
        spec.shortcut_hint = seed.shortcut_hint;
        spec.stages = seed.stages;
        spec.requires_write = false;
        spec.applicability =
            [this, requires_project = seed.requires_project](
                const pwb::ui_shell::CommandContext&) -> std::optional<std::string> {
            if (requires_project && context_.session().store() == nullptr) {
                return std::string("需要先打开工程");
            }
            return std::nullopt;
        };

        const std::string id = seed.id;
        if (id.rfind("stage.goto.", 0) == 0) {
            const std::string target =
                id == "stage.goto.prediction" ? kStage1Value
                : id == "stage.goto.constraints" ? kStage2Value
                                                 : kStage3Value;
            spec.callback = [this, target]() {
                if (stage_flow_ != nullptr) stage_flow_->request_stage(target);
            };
        } else if (id.rfind("nav.hub.", 0) == 0) {
            const auto& target = nav_targets().at(id);
            const int hub = target.hub;
            const QString subkey = QString::fromUtf8(target.subkey);
            spec.callback = [this, hub, subkey]() {
                if (appShell() != nullptr) {
                    appShell()->navigate_to(hub, subkey);
                }
            };
        } else if (id.rfind("panel.toggle.", 0) == 0) {
            const std::string rest = id.substr(strlen("panel.toggle."));
            if (rest == "tasks" || rest == "agent" || rest == "logs" ||
                rest == "console") {
                spec.callback = [this, rest]() {
                    auto* ws = appShell() != nullptr ? appShell()->workstation()
                                                     : nullptr;
                    if (ws != nullptr && ws->dock(rest) != nullptr) {
                        ws->set_dock_visible(rest, !ws->dock_visible(rest));
                    }
                };
            } else {
                // mapping-page panels: preference overrides for the CURRENT
                // stage — the same toggle path the panel menus use. The
                // applicability gate below refuses unknown keys so a
                // stale seed can never write a garbage preference.
                spec.applicability =
                    [this, rest](const pwb::ui_shell::CommandContext&)
                        -> std::optional<std::string> {
                        auto* page = appShell() != nullptr
                                         ? appShell()->mapping_page()
                                         : nullptr;
                        if (page == nullptr || page->dock_manager() == nullptr
                            || !page->dock_manager()->is_panel_registered(
                                rest)) {
                            return std::string("面板不可用（无编图画布或未注册）");
                        }
                        return std::nullopt;
                    };
                spec.callback = [this, rest]() {
                    if (stage_flow_ == nullptr) return;
                    bool now = true;
                    auto* page = appShell() != nullptr
                                     ? appShell()->mapping_page()
                                     : nullptr;
                    if (page != nullptr && page->dock_manager() != nullptr) {
                        now = !page->dock_manager()->is_panel_visible(rest);
                    }
                    stage_flow_->set_panel_visible("mapping." + rest, now);
                };
            }
        } else if (id == "stage.reset_layout") {
            spec.callback = [this]() {
                if (stage_flow_ != nullptr) {
                    stage_flow_->reset_stage_preferences();
                }
            };
        } else {
            continue;  // unknown seed — honest skip
        }
        registry.register_command(spec);
        stage_flow_command_ids_.push_back(id);
        ++registered;
    }
    stage_flow_command_count_ = registered;
    // Unregistration lives in ~MainWindow (the body runs while the id
    // list member is alive; a destroyed-signal hook would race member
    // destruction).

    // -- TaskCenter providers (the dock leaves its permanent empty state) ---
#ifdef PWB_WITH_CONV_30
    if (workstation->task_center() != nullptr) {
        auto* center = workstation->task_center();
        center->set_snapshot_provider([this]() {
            return job_center_->scheduler().statuses();
        });
        center->set_operation_provider([]() {
            return pwb::ui_shell::operation_registry().records();
        });
        center->set_cancel_task([this](const std::string& job_id) {
            return job_center_->scheduler().cancel(job_id);
        });
        center->set_record_lookup(
            [](const std::string& op_id)
                -> const pwb::ui_shell::OperationRecord* {
                return pwb::ui_shell::operation_registry().record(op_id);
            });
    }
#endif

    // -- selection / focus bus -------------------------------------------------
#ifdef PWB_WITH_UI_CONTROLLERS
    {
        auto* selection =
            new pwb::ui_controllers::qt::QtSelectionContext(this);
        stage_flow_coordination_ =
            new pwb::ui_controllers::qt::ViewCoordinationController(
                selection, nullptr, this);
        auto* coordination = stage_flow_coordination_;
        // Well-selection routing: dock raise + honest status mirror. The
        // map/canvas highlight surface is the layer-tree line's seam;
        // unbound sinks stay absent rather than fabricated.
        coordination->set_well_dock_sink([this](std::string well) {
            if (stage_flow_well_log_dock_ != nullptr) {
                stage_flow_well_log_dock_->show();
                stage_flow_well_log_dock_->raise();
            }
            status_label_->setText(
                tr("井: %1").arg(QString::fromStdString(well)));
        });
        coordination->set_map_select_well_sink([this](std::string well) {
            status_label_->setText(
                tr("地图选中井: %1").arg(QString::fromStdString(well)));
        });
        coordination->set_horizon_sink([this](std::string horizon) {
            if (stage_flow_ != nullptr) {
                stage_flow_->request_horizon(horizon);
            }
        });
    }
#endif

    // -- bank → page data link (the previously dangling signals) ----------
    // MapDocumentBank is the hub-3 document authority; MappingPage's
    // layer tree / chrome / preview consumed nothing because nothing fed
    // update_state. Every bank mutation now pushes the live list.
#ifdef PWB_WITH_CLOSURE_MAPPING
    if (auto* bank = pwb::app::closure_mapping::document_bank(this)) {
        auto push = [this, bank]() {
            auto* page = appShell() != nullptr ? appShell()->mapping_page()
                                               : nullptr;
            if (page != nullptr) {
                page->update_state(bank->documents(), bank->active_id());
            }
        };
        connect(bank, &pwb::app::closure_mapping::MapDocumentBank::active_changed, this,
                [push](const QString&) { push(); });
        connect(bank, &pwb::app::closure_mapping::MapDocumentBank::document_saved, this,
                [push](const QString&) { push(); });
        connect(bank, &pwb::app::closure_mapping::MapDocumentBank::dirty_changed, this,
                [push](bool) { push(); });
        push();
    }
#endif

    stage_flow_->refresh();
}

#endif  // PWB_WITH_STAGE_FLOW

}  // namespace pwb::app
