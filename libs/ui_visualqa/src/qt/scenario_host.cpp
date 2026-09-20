#include <pwb/ui_visualqa/qt/scenario_host.hpp>

#include <set>
#include <stdexcept>
#include <utility>

#include <QComboBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QPixmap>
#include <QProgressBar>
#include <QTabWidget>
#include <QVBoxLayout>

#include <pwb/domain/json.hpp>
#include <pwb/platform_services/theme_service.hpp>
#include <pwb/platform_services/theme_tokens.hpp>
#include <pwb/tool_policy/stages.hpp>
#include <pwb/tool_policy/tool_availability.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/operation_registry.hpp>
#include <pwb/ui_visualqa/qa_checks.hpp>
#include <pwb/ui_visualqa/qa_states.hpp>
#include <pwb/ui_visualqa/qt/qa_driver.hpp>
#include <pwb/ui_wellseis/slices.hpp>
#include <pwb/ui_wellseis/qt/seismic_context_toolbar.hpp>
#include <pwb/ui_wellseis/qt/task_panel_base.hpp>
#include <pwb/ui_widgets/badges.hpp>
#include <pwb/ui_widgets/states.hpp>
#include <pwb/ui_workstation/action_help.hpp>
#include <pwb/ui_workstation/inspector_panel.hpp>
#include <pwb/ui_workstation/task_center.hpp>
#include <pwb/ui_workstation/task_projection.hpp>
#include <pwb/ui_workstation/tool_help.hpp>
#include <pwb/ui_workstation/tool_surface.hpp>
#include <pwb/ui_workstation/ui_context.hpp>

namespace pwb::ui_visualqa::qt {

// PWB-V14-DATA-LINEAGE: this TU's scenario blocks reference shell:: —
// the pwb::ui_shell short alias the Python-side scenario DSL used. Define
// it locally (was an unresolved name on MSVC builds of this lib).
namespace shell = pwb::ui_shell;

namespace {

QString qs(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

std::string unq(const QString& s) { return s.toStdString(); }

// ---------------------------------------------------------------------------
// Generic handle: owns a widget + a collector that fills its section.
// ---------------------------------------------------------------------------

using Collector = std::function<void(ScenarioSnapshot&)>;

class WidgetHandle : public ScenarioHandle {
public:
    WidgetHandle(QWidget* widget, Collector collector)
        : widget_(widget), collector_(std::move(collector)) {}
    QWidget* widget() override { return widget_.get(); }
    void collect(ScenarioSnapshot& out) override {
        if (collector_) collector_(out);
    }

private:
    std::unique_ptr<QWidget> widget_;
    Collector collector_;
};

// The honest seam-unavailable placeholder — never a fake surface.
class UnavailableHandle : public ScenarioHandle {
public:
    explicit UnavailableHandle(std::string reason)
        : reason_(std::move(reason)) {
        auto* w = new QWidget;
        auto* layout = new QVBoxLayout(w);
        auto* label = new QLabel(
            QStringLiteral("V11 视觉 QA 场景不可用：%1")
                .arg(qs(reason_)),
            w);
        label->setObjectName(QStringLiteral("QaUnavailableLabel"));
        label->setWordWrap(true);
        layout->addWidget(label);
        w->resize(560, 200);
        widget_.reset(w);
    }
    QWidget* widget() override { return widget_.get(); }
    bool available() const override { return false; }
    std::string unavailable_reason() const override { return reason_; }
    void collect(ScenarioSnapshot&) override {}

private:
    std::unique_ptr<QWidget> widget_;
    std::string reason_;
};

// ---------------------------------------------------------------------------
// The palette context: CommandContext carrying the full UIContextSnapshot —
// the Python shell wires the palette's context_provider to the
// UIContextService snapshot (duck-typed ctx); CommandContext documents the
// "domain snapshots may subclass; predicates may downcast" contract.
// ---------------------------------------------------------------------------

class QaPaletteContext : public pwb::ui_shell::CommandContext {
public:
    pwb::ui_workstation::UIContextSnapshot ui;
};

// Shell registration parity helpers — the applicability/tool-details
// predicates receive the base CommandContext and downcast to reach the
// UIContextSnapshot (tool_context_from_ui_snapshot parity).

pwb::tool_policy::ToolContextSnapshot tool_ctx(
    const pwb::ui_shell::CommandContext& ctx) {
    const auto& qa = static_cast<const QaPaletteContext&>(ctx);
    return pwb::ui_workstation::tool_context_from_ui_snapshot(qa.ui);
}

std::optional<std::string> tool_applicability(
    const std::string& tool_id,
    const pwb::ui_shell::CommandContext& ctx) {
    if (tool_id.empty()) return std::nullopt;
    const pwb::tool_policy::ToolAvailability avail =
        pwb::tool_policy::evaluate_tool(tool_id, tool_ctx(ctx));
    if (avail.disabled_reason.empty()) return std::nullopt;
    return avail.disabled_reason;
}

// ---------------------------------------------------------------------------
// Collector helpers (findChild-based — mirrors the Python attribute reads).
// ---------------------------------------------------------------------------

std::vector<std::string> list_texts(const QListWidget* list) {
    std::vector<std::string> out;
    if (list == nullptr) return out;
    for (int row = 0; row < list->count(); ++row) {
        const QListWidgetItem* item = list->item(row);
        out.push_back(item != nullptr ? unq(item->text()) : "");
    }
    return out;
}

// Read-only value labels inside the seismic settings card, in grid-row
// order (task / horizon / attribute / mode / shape / mock — the Python
// attribute order parity).
std::vector<QLabel*> settings_values(QWidget* card) {
    if (card == nullptr) return {};
    const QList<QLabel*> found = card->findChildren<QLabel*>(
        QStringLiteral("WorkFieldValue"));
    return {found.begin(), found.end()};
}

QaPaletteItem palette_item_of(const QListWidgetItem* item,
                              const pwb::ui_shell::CommandRegistry& reg) {
    QaPaletteItem out;
    if (item == nullptr) return out;
    out.text = unq(item->text());
    out.enabled = (item->flags() & Qt::ItemFlag::ItemIsEnabled) !=
                  Qt::ItemFlags{};
    out.spec_id =
        item->data(Qt::ItemDataRole::UserRole).toString().toStdString();
    out.tool_tip = unq(item->toolTip());
    const pwb::ui_shell::CommandSpec* spec = reg.get(out.spec_id);
    out.stage_scoped = spec != nullptr && !spec->stages.empty();
    return out;
}

}  // namespace

// ==========================================================================
// Builders — build_<scenario>() parity
// ==========================================================================

std::unique_ptr<ScenarioHandle> build_first_open_empty_shell(
    const ScenarioSeams& seams) {
    // AppShell is unported (integration slice's composition root) — the
    // scenario takes the surface through the injected factory.
    if (!seams.shell_factory) {
        return std::make_unique<UnavailableHandle>(
            "first_open_empty_shell 需要 shell_factory（AppShell 未移植）");
    }
    std::unique_ptr<QaShellSurface> surface = seams.shell_factory();
    if (!surface) {
        return std::make_unique<UnavailableHandle>(
            "shell_factory 返回空 surface");
    }
    QaShellSurface* raw = surface.get();
    // The handle owns the surface (which owns its widget).
    class ShellHandle : public ScenarioHandle {
    public:
        explicit ShellHandle(std::unique_ptr<QaShellSurface> s)
            : surface_(std::move(s)) {}
        QWidget* widget() override { return surface_->widget(); }
        void collect(ScenarioSnapshot& out) override {
            out.shell = surface_->snapshot();
        }
    private:
        std::unique_ptr<QaShellSurface> surface_;
    };
    (void)raw;
    return std::make_unique<ShellHandle>(std::move(surface));
}

std::unique_ptr<ScenarioHandle> build_data_manager_surface(
    const ScenarioSeams& seams) {
    if (!seams.data_page_factory) {
        return std::make_unique<UnavailableHandle>(
            "data_manager_surface 需要 data_page_factory"
            "（DataPage 未移植 — UI-06 已记录延后）");
    }
    std::unique_ptr<QaDataPageSurface> surface = seams.data_page_factory();
    if (!surface) {
        return std::make_unique<UnavailableHandle>(
            "data_page_factory 返回空 surface");
    }
    // build_data_manager_surface parity: refresh() + select first asset +
    // update inspector — the seam does the same on its own surface.
    surface->refresh();
    if (surface->resource_count() > 0) {
        surface->select_asset(0);
    }
    settle(100);
    class DataPageHandle : public ScenarioHandle {
    public:
        explicit DataPageHandle(std::unique_ptr<QaDataPageSurface> s)
            : surface_(std::move(s)) {}
        QWidget* widget() override { return surface_->widget(); }
        void collect(ScenarioSnapshot& out) override {
            out.data_manager = surface_->snapshot();
        }
    private:
        std::unique_ptr<QaDataPageSurface> surface_;
    };
    return std::make_unique<DataPageHandle>(std::move(surface));
}

std::unique_ptr<ScenarioHandle> build_well_task_workflow_panel() {
    namespace wellseis = pwb::ui_wellseis;
    using pwb::domain::Json;

    // The SimpleNamespace task fixtures — pending / running / complete.
    wellseis::PredictionTaskSlice pending;
    pending.id = "pred-003";
    pending.name = "D63 砂地比预测";
    pending.status = "pending";
    pending.adapter_kind = "demo";

    wellseis::PredictionTaskSlice running;
    running.id = "pred-002";
    running.name = "T1 岩相预测";
    running.status = "running";
    running.adapter_kind = "xgboost";
    running.probability_summary["mean_probability"] = 0.72;
    running.review_area_count = 2;

    wellseis::PredictionTaskSlice complete;
    complete.id = "pred-001";
    complete.name = "ZJ2 孔隙度预测";
    complete.status = "complete";
    complete.adapter_kind = "xgboost";
    complete.probability_summary["mean_probability"] = 0.81;

    auto* panel = new wellseis::qt::PredictionTaskPanel();
    panel->update_state({pending, running, complete},
                        /*selected_index=*/1);

    auto* container = new QWidget();
    auto* layout = new QVBoxLayout(container);
    layout->setContentsMargins(8, 8, 8, 8);
    layout->addWidget(panel, 1);
    container->resize(420, 560);

    return std::make_unique<WidgetHandle>(
        container, [panel](ScenarioSnapshot& out) {
            QaTaskPanelSnapshot snap;
            auto* list = panel->findChild<QListWidget*>(
                QStringLiteral("WorkListWidget"));
            auto* badge = panel->findChild<QLabel*>(
                QStringLiteral("PwbBadge"));
            snap.panel_found = true;
            snap.row_texts = list_texts(list);
            if (badge != nullptr) {
                snap.status_badge_text = unq(badge->text());
                snap.status_badge_tone =
                    unq(badge->property("tone").toString());
            }
            out.task_panel = std::move(snap);
        });
}

std::unique_ptr<ScenarioHandle> build_seismic_context_surface() {
    namespace wellseis = pwb::ui_wellseis;

    wellseis::PredictionTaskSlice task;
    task.name = "振幅属性提取 · HZ26";

    auto* toolbar = new wellseis::qt::SeismicContextToolbar();
    // seismic_source_combo.addItem + setCurrentIndex(0) parity.
    toolbar->set_source_entries(
        {wellseis::SourceComboEntry{"HZ26_3D_full.sgy", "survey-1"}});
    auto* source_combo = toolbar->findChild<QComboBox*>(
        QStringLiteral("SeismicPredictionSourceCombo"));
    if (source_combo != nullptr) {
        source_combo->setCurrentIndex(0);
    }
    toolbar->set_context(&task, "D63", "RMS振幅", "wiggle",
                         std::array<std::int64_t, 3>{301, 401, 1201},
                         std::optional<std::string>{"演示（非科学预测）"});
    toolbar->set_status(QStringLiteral("运行中 · 第 4/9 属性"));

    auto* container = new QWidget();
    auto* layout = new QVBoxLayout(container);
    layout->setContentsMargins(8, 8, 8, 8);
    auto* caption =
        new QLabel(QStringLiteral("地震上下文面（V11 QA 场景）"), container);
    caption->setObjectName(QStringLiteral("WorkFieldLabel"));
    layout->addWidget(caption);
    layout->addWidget(toolbar);
    layout->addStretch(1);
    container->resize(1180, 120);

    return std::make_unique<WidgetHandle>(
        container, [toolbar](ScenarioSnapshot& out) {
            QaSeismicContextSnapshot snap;
            // findChild(SeismicContextToolbar) parity — the toolbar is
            // already captured; the flag records presence only.
            snap.toolbar_found = toolbar != nullptr;
            auto* source = toolbar->findChild<QComboBox*>(
                QStringLiteral("SeismicPredictionSourceCombo"));
            auto* attribute = toolbar->findChild<QComboBox*>(
                QStringLiteral("SeismicAttributeDropdownCombo"));
            snap.source_text =
                source != nullptr ? unq(source->currentText()) : "";
            snap.attribute_text =
                attribute != nullptr ? unq(attribute->currentText()) : "";
            // The details card's WorkFieldValue labels in grid-row order:
            // task / horizon / attribute / mode / shape / mock.
            auto* card = toolbar->findChild<QWidget*>(
                QStringLiteral("SeismicSettingsDetailsCard"));
            const std::vector<QLabel*> values = settings_values(card);
            if (values.size() >= 5) {
                snap.task_text = unq(values[0]->text());
                snap.horizon_text = unq(values[1]->text());
                snap.shape_text = unq(values[4]->text());
            }
            // status_value_ is the WorkFieldValue that is a DIRECT child
            // of the toolbar (the settings card's are nested).
            const auto direct = toolbar->findChildren<QLabel*>(
                QStringLiteral("WorkFieldValue"),
                Qt::FindChildOption::FindDirectChildrenOnly);
            if (!direct.isEmpty()) {
                snap.status_text = unq(direct.first()->text());
            }
            out.seismic = std::move(snap);
        });
}

std::unique_ptr<ScenarioHandle> build_stage_bar_phase(
    const std::string& stage_value, const ScenarioSeams& seams) {
    if (!seams.stage_surface_factory) {
        return std::make_unique<UnavailableHandle>(
            "stage_bar_phase* 需要 stage_surface_factory"
            "（MappingStageBar+Panel 组合面未移植 — StageDock 是平台改型）");
    }
    std::unique_ptr<QaStageSurface> surface = seams.stage_surface_factory();
    if (!surface) {
        return std::make_unique<UnavailableHandle>(
            "stage_surface_factory 返回空 surface");
    }
    // _stage_surface parity: horizon state + current stage + panel page.
    surface->set_horizon_state("D63", {"T1", "D63", "M10"});
    surface->set_stage(stage_value);
    class StageHandle : public ScenarioHandle {
    public:
        explicit StageHandle(std::unique_ptr<QaStageSurface> s)
            : surface_(std::move(s)) {}
        QWidget* widget() override { return surface_->widget(); }
        void collect(ScenarioSnapshot& out) override {
            out.stage = surface_->snapshot();
        }
    private:
        std::unique_ptr<QaStageSurface> surface_;
    };
    return std::make_unique<StageHandle>(std::move(surface));
}

namespace {

std::unique_ptr<ScenarioHandle> inspector_payload_widget(
    pwb::ui_workstation::InspectorPayload payload) {
    auto* inspector = new pwb::ui_workstation::WorkstationInspector();
    inspector->show_payload(payload);
    auto* container = new QWidget();
    auto* layout = new QVBoxLayout(container);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(inspector, 1);
    container->resize(340, 640);

    return std::make_unique<WidgetHandle>(
        container, [inspector](ScenarioSnapshot& out) {
            QaInspectorSnapshot snap;
            auto* header = inspector->findChild<QLabel*>(
                QStringLiteral("WorkstationInspectorHeader"));
            snap.header = header != nullptr ? unq(header->text()) : "";
            // _form_values parity: the FieldRole read-only QLineEdits per
            // tab page (tab 0 = 属性 / tab 1 = 解释).
            auto collect = [&snap](QWidget* page, bool interpretation) {
                if (page == nullptr) return;
                const auto edits = page->findChildren<QLineEdit*>(
                    QStringLiteral("WorkstationInspectorValue"));
                for (QLineEdit* edit : edits) {
                    if (edit == nullptr) continue;
                    (interpretation ? snap.interpretation_values
                                    : snap.property_values)
                        .push_back(unq(edit->text()));
                }
            };
            QTabWidget* tabs = inspector->tabs();
            if (tabs != nullptr) {
                collect(tabs->widget(0), false);
                collect(tabs->widget(1), true);
            }
            out.inspector = std::move(snap);
        });
}

}  // namespace

std::unique_ptr<ScenarioHandle> build_inspector_version_payload() {
    pwb::ui_workstation::InspectorPayload payload;
    payload.kind = "version";
    payload.fields = {
        {"version_id", "ver_20260912_a12c"},
        {"asset_name", "A12.las"},
        {"version_number", "3"},
        {"stage", "derived"},
        {"created_at", "2026-09-12 10:24"},
        // "9f2c" * 16 — abbreviated by the core (>12 chars).
        {"checksum",
         "9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c"
         "9f2c9f2c"},
        {"run_id", "run_compile_0451"},
        {"source_kind", "map_compile"},
    };
    payload.list_counts = {
        {"parent_ids", 1},
        {"downstream_count", 2},
    };
    return inspector_payload_widget(std::move(payload));
}

std::unique_ptr<ScenarioHandle> build_inspector_run_payload() {
    pwb::ui_workstation::InspectorPayload payload;
    payload.kind = "run";
    payload.fields = {
        {"run_id", "run_compile_0451"},
        {"operation", "map_compile"},
        {"status", "warning"},
        {"model", "ConstrainedIDW v2"},
        {"parameters_compact",
         "resolution_m=250.0, constraint_mode=hard"},
        {"started_at", "1760000000.0"},
        {"finished_at", "1760000038.5"},
    };
    payload.list_counts = {
        {"input_version_ids", 3},
        {"output_version_ids", 1},
    };
    return inspector_payload_widget(std::move(payload));
}

std::unique_ptr<ScenarioHandle> build_task_center_operations() {
    namespace shell = pwb::ui_shell;
    namespace ws = pwb::ui_workstation;

    auto registry = std::make_unique<shell::OperationRegistry>();
    // build_task_center_operations parity: in-flight + terminal rows.
    registry->begin("v11qa-import", "导入 SEG-Y",
                    std::optional<std::string>{"HZ26_3D_full.sgy"},
                    /*cancellable=*/true);
    registry->set_cancel("v11qa-import", [] {});
    registry->update("v11qa-import", /*done=*/42, /*total=*/100,
                     std::optional<std::string>{"读取道头"});
    registry->begin("v11qa-verify", "完整性校验",
                    std::optional<std::string>{"A12.las"});
    registry->finish("v11qa-verify", shell::OperationState::Warning,
                     std::nullopt,
                     std::optional<std::string>{"2 项过期"},
                     [] {});

    shell::OperationRegistry* raw = registry.get();
    auto* center = new ws::WorkstationTaskCenter();
    // attach_registry parity: providers + cancel + record lookup wired
    // to the same registry object.
    center->set_operation_provider([raw] {
        return raw->records();
    });
    center->set_snapshot_provider(
        [] { return std::vector<pwb::job::JobSnapshot>{}; });
    center->set_cancel_operation(
        [raw](const std::string& op_id) {
            return raw->request_cancel(op_id);
        });
    center->set_record_lookup(
        [raw](const std::string& op_id)
            -> const shell::OperationRecord* {
            return raw->record(op_id);
        });
    center->refresh();

    auto* container = new QWidget();
    auto* layout = new QVBoxLayout(container);
    layout->setContentsMargins(8, 8, 8, 8);
    layout->addWidget(center, 1);
    container->resize(760, 320);

    class TaskCenterHandle : public ScenarioHandle {
    public:
        TaskCenterHandle(std::unique_ptr<QWidget> w,
                         ws::WorkstationTaskCenter* center,
                         std::unique_ptr<shell::OperationRegistry> reg)
            : widget_(std::move(w)),
              center_(center),
              registry_(std::move(reg)) {}
        QWidget* widget() override { return widget_.get(); }
        void collect(ScenarioSnapshot& out) override {
            QaTaskCenterSnapshot snap;
            const ws::TaskTableModel* model = center_->model();
            const int rows = model != nullptr ? model->rowCount() : 0;
            for (int row = 0; row < rows; ++row) {
                const ws::TaskRow* handle = model->row_at(row);
                if (handle == nullptr) continue;
                snap.row_ids.push_back(handle->task_id);
                if (handle->task_id == "op:v11qa-import") {
                    snap.running_present = true;
                    snap.running_state_text =
                        ws::task_state_text(*handle);
                    snap.running_progress = handle->progress;
                }
                if (handle->task_id == "op:v11qa-verify") {
                    snap.finished_present = true;
                    if (handle->message.has_value()) {
                        snap.finished_message = *handle->message;
                    }
                }
            }
            // _check_task_center parity: the cancel request itself is the
            // verdict probe (registry.request_cancel).
            snap.cancel_request_result =
                registry_->request_cancel("v11qa-import");
            out.task_center = std::move(snap);
        }
    private:
        std::unique_ptr<QWidget> widget_;
        ws::WorkstationTaskCenter* center_;
        std::unique_ptr<shell::OperationRegistry> registry_;
    };
    std::unique_ptr<QWidget> owner(container);
    return std::make_unique<TaskCenterHandle>(std::move(owner), center,
                                              std::move(registry));
}

// The palette needs the stage-action vocabulary — build through the seam
// (declared in the header; this body replaces the stub above via the
// dispatch table's call with `seams`).
std::unique_ptr<ScenarioHandle> build_command_palette_disabled_reason(
    const ScenarioSeams& seams) {
    namespace shell = pwb::ui_shell;
    namespace ws = pwb::ui_workstation;
    using pwb::tool_policy::MappingStage;

    class PaletteHandle : public ScenarioHandle {
    public:
        // Owns: context -> registry -> (palette + host widget).
        std::unique_ptr<QaPaletteContext> context =
            std::make_unique<QaPaletteContext>();
        std::unique_ptr<shell::CommandRegistry> registry =
            std::make_unique<shell::CommandRegistry>();
        std::unique_ptr<QWidget> host;
        shell::CommandPalette* palette = nullptr;

        QWidget* widget() override { return host.get(); }
        void collect(ScenarioSnapshot& out) override {
            QaPaletteScenarioSnapshot snap;
            snap.open = palette != nullptr && !palette->isHidden();
            auto* list = palette != nullptr
                             ? palette->findChild<QListWidget*>()
                             : nullptr;
            auto* filter = palette != nullptr
                               ? palette->findChild<QLineEdit*>()
                               : nullptr;
            if (list == nullptr || filter == nullptr) {
                out.palette = std::move(snap);
                return;
            }
            for (int row = 0; row < list->count(); ++row) {
                const QaPaletteItem item =
                    palette_item_of(list->item(row), *registry);
                if (item.enabled) ++snap.enabled_count;
                snap.stage_items.push_back(item);
            }
            filter->setText(qs(palette_tool_filter()));
            settle(60);
            for (int row = 0; row < list->count(); ++row) {
                snap.tool_items.push_back(
                    palette_item_of(list->item(row), *registry));
            }
            out.palette = std::move(snap);
        }
    };

    auto handle = std::make_unique<PaletteHandle>();
    // Python: stage① context (FACIES_CALIBRATION) — write grant absent
    // (the harness grants nothing).
    handle->context->ui.project_open = true;
    handle->context->ui.mapping_stage =
        pwb::tool_policy::stage_value(MappingStage::FaciesCalibration);
    handle->context->mapping_stage = handle->context->ui.mapping_stage;
    handle->context->write_granted = false;

    shell::CommandRegistry& registry = *handle->registry;

    // _register_stage_palette_commands parity: stage:<value>:<action>
    // specs with the stage whitelist + tool applicability — the
    // (action_id,title,tool) vocabulary arrives via the seam.
    for (const QaStageActionSpec& action : seams.stage_actions) {
        shell::CommandSpec spec;
        spec.id = "stage:" + action.stage_value + ":" + action.action_id;
        spec.label = "阶段动作 · " + action.title;
        spec.hint =
            pwb::tool_policy::stage_display_or_raw(action.stage_value);
        spec.keywords = "阶段 stage 编图";
        spec.group = "编图阶段";
        spec.stages = {action.stage_value};
        if (!action.tool_id.empty()) {
            const std::string tool = action.tool_id;
            spec.applicability =
                [tool](const shell::CommandContext& ctx) {
                    return tool_applicability(tool, ctx);
                };
        }
        registry.register_command(std::move(spec));
    }

    // _register_surface_palette_commands parity: map:topology_validate
    // + the surface tools with evaluator applicability.
    {
        shell::CommandSpec spec;
        spec.id = "map:topology_validate";
        spec.label = "编图 · 拓扑校验（定位首问题）";
        spec.hint = "校验全部打开的编辑会话并定位首个拓扑问题";
        spec.keywords = "拓扑 校验 问题 定位 topology";
        spec.group = "编图工具";
        registry.register_command(std::move(spec));
    }
    static const char* kSurfaceTools[] = {
        "layer_new",          "reference_import", "layer_properties",
        "attribute_table",    "layer_zoom",       "layer_export",
        "symbology",          "style_manager",    "factor_workbench",
        "factor_overlay",     "qa_run",           "map_product_assemble",
        "map_export",
        "toggle_editing",     "save_edits",       "rollback",
        "undo",               "redo",             "delete_selected",
        "snapping",           "topology",
        "identify",           "measure_distance", "select_rectangle",
        "split",              "merge",            "reshape",
    };
    for (const char* tool_c : kSurfaceTools) {
        const std::string tool = tool_c;
        shell::CommandSpec spec;
        spec.id = "map:" + tool;
        spec.label = "编图 · " + ws::tool_label(tool);
        const ws::ToolHelpSpec* help = ws::tool_help_for(tool);
        spec.hint = help != nullptr ? help->impact : "";
        spec.keywords = "map 编图 图层 符号 因子 导出";
        spec.group = "编图工具";
        spec.applicability =
            [tool](const shell::CommandContext& ctx) {
                return tool_applicability(tool, ctx);
            };
        registry.register_command(std::move(spec));
    }

    // Host widget — the palette is a plain child (no window flags —
    // offscreen-safe parity).
    handle->host = std::make_unique<QWidget>();
    handle->host->resize(1600, 900);
    QaPaletteContext* context = handle->context.get();
    auto* palette = new shell::CommandPalette(
        handle->host.get(), registry,
        [context]() -> const shell::CommandContext* { return context; });
    // map: tool detail tooltips — action_help.format_details parity.
    palette->set_tool_details_provider(
        [](const std::string& tool_id,
           const shell::CommandContext& ctx) -> QString {
            const ws::ActionExplanation explanation =
                ws::explain(tool_id, tool_ctx(ctx));
            return qs(ws::format_details(explanation));
        });
    handle->palette = palette;

    // The drive parity: popup + stage filter (the scenario leaves the
    // palette open in the stage-filtered state; the collector's second
    // sweep mirrors the check's own tool-filter switch).
    handle->host->show();
    settle(200);
    palette->popup();
    auto* filter = palette->findChild<QLineEdit*>();
    if (filter != nullptr) {
        filter->setText(qs(palette_stage_filter()));
    }
    settle(100);
    return handle;
}

std::unique_ptr<ScenarioHandle> build_error_empty_states_composite() {
    auto* container = new QWidget();
    auto* layout = new QVBoxLayout(container);
    layout->setContentsMargins(12, 12, 12, 12);
    layout->setSpacing(12);

    auto* empty = new pwb::ui_widgets::PwbEmptyState(
        QStringLiteral("暂无数据资产"),
        QStringLiteral("导入文件或连接数据目录后在此显示"), "inbox.svg",
        nullptr, container);
    layout->addWidget(empty, 1);

    auto* loading = new pwb::ui_widgets::PwbLoadingState(
        QStringLiteral("正在解析 HZ26_3D_full.sgy 道头…"), container);
    layout->addWidget(loading, 1);

    auto* badge_row = new QWidget(container);
    auto* row = new QHBoxLayout(badge_row);
    row->setContentsMargins(0, 0, 0, 0);
    row->setSpacing(8);
    auto* caption =
        new QLabel(QStringLiteral("目录健康："), badge_row);
    caption->setObjectName(QStringLiteral("WorkFieldLabel"));
    row->addWidget(caption);
    std::vector<pwb::ui_widgets::PwbBadge*> badges = {
        new pwb::ui_widgets::PwbBadge(QStringLiteral("2 项过期"),
                                      QStringLiteral("warning"),
                                      badge_row),
        new pwb::ui_widgets::PwbBadge(QStringLiteral("1 项校验失败"),
                                      QStringLiteral("error"),
                                      badge_row),
        new pwb::ui_widgets::PwbBadge(QStringLiteral("98 项已验证"),
                                      QStringLiteral("success"),
                                      badge_row),
    };
    for (pwb::ui_widgets::PwbBadge* badge : badges) {
        row->addWidget(badge);
    }
    row->addStretch(1);
    layout->addWidget(badge_row);
    layout->addStretch(2);
    container->resize(560, 520);

    return std::make_unique<WidgetHandle>(
        container,
        [empty, loading, badges](ScenarioSnapshot& out) {
            QaStatesCompositeSnapshot snap;
            if (empty != nullptr) {
                snap.empty_found = true;
                auto* title = empty->findChild<QLabel*>(
                    QStringLiteral("PwbStateTitle"));
                auto* hint = empty->findChild<QLabel*>(
                    QStringLiteral("PwbStateHint"));
                snap.empty_title =
                    title != nullptr ? unq(title->text()) : "";
                snap.empty_hint_hidden =
                    hint == nullptr || hint->isHidden();
            }
            if (loading != nullptr) {
                snap.loading_found = true;
                auto* text = loading->findChild<QLabel*>(
                    QStringLiteral("PwbStateHint"));
                auto* bar = loading->findChild<QProgressBar*>(
                    QStringLiteral("PwbProgress"));
                snap.loading_text =
                    text != nullptr ? unq(text->text()) : "";
                snap.loading_indeterminate =
                    bar != nullptr && bar->minimum() == 0 &&
                    bar->maximum() == 0;
            }
            for (const pwb::ui_widgets::PwbBadge* badge : badges) {
                if (badge == nullptr) continue;
                snap.badges.push_back(QaBadgeSnapshot{
                    unq(badge->tone()), unq(badge->text())});
            }
            out.states_composite = std::move(snap);
        });
}

std::unique_ptr<ScenarioHandle> build_theme_matrix_smoke(
    const ScenarioSeams& seams) {
    // Reuses the phase-2 stage surface (build_theme_matrix_smoke parity).
    std::unique_ptr<ScenarioHandle> stage_handle =
        build_stage_bar_phase("constraint_factor", seams);
    if (!stage_handle->available()) {
        return stage_handle;
    }
    class ThemeHandle : public ScenarioHandle {
    public:
        explicit ThemeHandle(std::unique_ptr<ScenarioHandle> inner)
            : inner_(std::move(inner)) {}
        QWidget* widget() override { return inner_->widget(); }
        void collect(ScenarioSnapshot& out) override {
            // _check_theme_matrix parity: for each (theme, size) resize +
            // settle + grab + sampled distinct colors. Theme switching
            // goes through the real ThemeService (per-instance port of
            // theme_manager) applied to this widget — the previous theme
            // is restored afterwards like the Python finally block.
            QWidget* w = widget();
            pwb::platform_services::ThemeService themes;
            const pwb::platform_services::ThemeMode previous =
                themes.theme();
            for (const std::string& theme_name : theme_matrix_themes()) {
                themes.set_theme(
                    pwb::platform_services::theme_from_string(theme_name));
                themes.apply(*w);
                for (const QaSize& size : theme_matrix_sizes()) {
                    w->resize(size.width, size.height);
                    settle(60);
                    const QPixmap pixmap = w->grab();
                    QaThemeRender render;
                    render.theme = theme_name;
                    render.want_width = size.width;
                    render.want_height = size.height;
                    render.null_pixmap = pixmap.isNull();
                    if (!pixmap.isNull()) {
                        const QImage image = pixmap.toImage();
                        render.width = image.width();
                        render.height = image.height();
                        // _distinct_sampled_colors parity (step=48).
                        std::set<QRgb> colors;
                        for (int y = 0; y < image.height(); y += 48) {
                            for (int x = 0; x < image.width(); x += 48) {
                                colors.insert(image.pixel(x, y));
                            }
                        }
                        render.distinct_colors =
                            static_cast<int>(colors.size());
                    }
                    out.theme_renders.push_back(std::move(render));
                }
            }
            themes.set_theme(previous);
            themes.apply(*w);
        }
    private:
        std::unique_ptr<ScenarioHandle> inner_;
    };
    return std::make_unique<ThemeHandle>(std::move(stage_handle));
}

// ==========================================================================
// dispatch
// ==========================================================================

std::unique_ptr<ScenarioHandle> build_scenario(
    const std::string& name, const ScenarioSeams& seams) {
    using pwb::tool_policy::MappingStage;
    if (name == "first_open_empty_shell")
        return build_first_open_empty_shell(seams);
    if (name == "data_manager_surface")
        return build_data_manager_surface(seams);
    if (name == "well_task_workflow_panel")
        return build_well_task_workflow_panel();
    if (name == "seismic_context_surface")
        return build_seismic_context_surface();
    if (name == "stage_bar_phase1")
        return build_stage_bar_phase(
            pwb::tool_policy::stage_value(MappingStage::FaciesCalibration),
            seams);
    if (name == "stage_bar_phase2")
        return build_stage_bar_phase(
            pwb::tool_policy::stage_value(MappingStage::ConstraintFactor),
            seams);
    if (name == "stage_bar_phase3")
        return build_stage_bar_phase(
            pwb::tool_policy::stage_value(
                MappingStage::IntegratedCompilation),
            seams);
    if (name == "inspector_version_payload")
        return build_inspector_version_payload();
    if (name == "inspector_run_payload")
        return build_inspector_run_payload();
    if (name == "task_center_operations")
        return build_task_center_operations();
    if (name == "command_palette_disabled_reason")
        return build_command_palette_disabled_reason(seams);
    if (name == "error_empty_states_composite")
        return build_error_empty_states_composite();
    if (name == "theme_matrix_smoke")
        return build_theme_matrix_smoke(seams);
    // Python KeyError parity.
    throw std::invalid_argument("未知 V11 视觉 QA 场景: " + name);
}

std::vector<CheckResult> run_scenario_checks(
    const std::string& name, ScenarioHandle& handle) {
    if (!handle.available()) {
        return {make_check("surface_available", false,
                           handle.unavailable_reason())};
    }
    ScenarioSnapshot snapshot;
    handle.collect(snapshot);
    return pwb::ui_visualqa::run_scenario_checks(name, snapshot);
}

}  // namespace pwb::ui_visualqa::qt
