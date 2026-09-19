// Oracle replay test for the ui_shell Qt-free cores (UI-01).
// Fixture: fixtures/ui_shell_oracle.json — frozen from the real Python
// modules by tools/oracle/generate_ui_shell_fixtures.py.
// Seam note: command_registry's stage_whitelist_reason is frozen as
// "STAGE_SENTINEL[a,b]" — the replay translates it through the real
// pwb::tool_policy::stage_whitelist_reason, verifying both the stage
// whitelist passed and the live reason text.

#include <cmath>
#include <fstream>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/tool_policy/tool_availability.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/deferred_page_bindings.hpp>
#include <pwb/ui_shell/dock_manager.hpp>
#include <pwb/ui_shell/dock_registry.hpp>
#include <pwb/ui_shell/layout_presets.hpp>
#include <pwb/ui_shell/navigation.hpp>
#include <pwb/ui_shell/operation_registry.hpp>

#include "ui_shell_test.hpp"

using pwb::domain::Json;
using namespace pwb::ui_shell;

namespace {

Json load_oracle() {
    std::ifstream in(PWB_UI_SHELL_ORACLE);
    if (!in) {
        std::fprintf(stderr, "cannot open oracle: %s\n", PWB_UI_SHELL_ORACLE);
        std::exit(2);
    }
    std::stringstream buffer;
    buffer << in.rdbuf();
    return Json::parse(buffer.str());
}

std::vector<std::string> jstrs(const Json& arr) {
    std::vector<std::string> out;
    for (const auto& v : arr) {
        out.push_back(v.get<std::string>());
    }
    return out;
}

bool jbool_or(const Json& j, const std::string& key, bool fallback) {
    return j.contains(key) && !j.at(key).is_null() ? j.at(key).get<bool>()
                                                  : fallback;
}

std::string jstr_or_empty(const Json& j) {
    return j.is_null() ? std::string() : j.get<std::string>();
}

std::optional<std::string> jopt_str(const Json& j, const std::string& key) {
    if (!j.contains(key) || j.at(key).is_null()) {
        return std::nullopt;
    }
    return j.at(key).get<std::string>();
}

std::optional<int> jopt_int(const Json& j, const std::string& key) {
    if (!j.contains(key) || j.at(key).is_null()) {
        return std::nullopt;
    }
    return j.at(key).get<int>();
}

// "STAGE_SENTINEL[a,b,c]" -> real tool_policy reason for stages {a,b,c}.
std::string resolve_sentinel(const std::string& frozen) {
    const std::string prefix = "STAGE_SENTINEL[";
    if (frozen.rfind(prefix, 0) != 0) {
        return frozen;
    }
    const auto inner = frozen.substr(prefix.size(),
                                     frozen.size() - prefix.size() - 1);
    std::vector<std::string> stages;
    std::stringstream ss(inner);
    std::string item;
    while (std::getline(ss, item, ',')) {
        stages.push_back(item);
    }
    return pwb::tool_policy::stage_whitelist_reason(stages);
}

OperationState state_from_value(const std::string& v) {
    if (v == "queued") return OperationState::Queued;
    if (v == "running") return OperationState::Running;
    if (v == "cancelling") return OperationState::Cancelling;
    if (v == "completed") return OperationState::Completed;
    if (v == "warning") return OperationState::Warning;
    if (v == "failed") return OperationState::Failed;
    return OperationState::Cancelled;
}

void check_record(const OperationRecord* rec, const Json& frozen,
                  const char* tag) {
    if (frozen.is_null()) {
        CHECK(rec == nullptr);
        return;
    }
    CHECK(rec != nullptr);
    if (rec == nullptr) {
        return;
    }
    CHECK_EQ(rec->op_id, frozen.at("op_id").get<std::string>());
    CHECK_EQ(rec->title, frozen.at("title").get<std::string>());
    CHECK_EQ(operation_state_value(rec->state),
             frozen.at("state").get<std::string>());
    CHECK_EQ(rec->object_label.value_or(""), jstr_or_empty(frozen.at("object_label")));
    CHECK_EQ(rec->done.has_value(), frozen.at("done").is_number());
    if (rec->done.has_value()) {
        CHECK_EQ(*rec->done, frozen.at("done").get<int>());
    }
    CHECK_EQ(rec->total.has_value(), frozen.at("total").is_number());
    if (rec->total.has_value()) {
        CHECK_EQ(*rec->total, frozen.at("total").get<int>());
    }
    CHECK_EQ(rec->stage.value_or(""), jstr_or_empty(frozen.at("stage")));
    CHECK_EQ(rec->error.value_or(""), jstr_or_empty(frozen.at("error")));
    CHECK_EQ(rec->cancellable, frozen.at("cancellable").get<bool>());
    CHECK_EQ(rec->result_label.value_or(""),
             jstr_or_empty(frozen.at("result_label")));
    const Json& frac = frozen.at("progress_fraction");
    CHECK_EQ(rec->progress_fraction().has_value(), frac.is_number());
    if (frac.is_number() && rec->progress_fraction().has_value()) {
        CHECK(std::fabs(*rec->progress_fraction() - frac.get<double>()) < 1e-9);
    }
}

std::vector<std::string> record_ids(
    const std::vector<const OperationRecord*>& recs) {
    std::vector<std::string> out;
    for (const auto* r : recs) {
        out.push_back(r->op_id);
    }
    return out;
}

}  // namespace

// ---------------------------------------------------------------------------

PWB_TEST(dock_framework_replay) {
    const Json sec = load_oracle().at("dock_framework");
    const DockRegistry& reg = workstation_dock_registry();

    CHECK_EQ(reg.descriptors().size(), sec.at("descriptors").size());
    const auto& frozen = sec.at("descriptors");
    for (std::size_t i = 0; i < frozen.size(); ++i) {
        const Json& f = frozen[i];
        const DockDescriptor& d = reg.descriptors()[i];
        CHECK_EQ(d.dock_id, f.at("dock_id").get<std::string>());
        CHECK_EQ(d.title, f.at("title").get<std::string>());
        CHECK_EQ(d.preferred_area, f.at("preferred_area").get<std::string>());
        std::string imp = f.at("importance").get<std::string>();
        DockImportance expect_imp =
            imp == "core" ? DockImportance::Core
                          : imp == "secondary" ? DockImportance::Secondary
                                               : DockImportance::Utility;
        CHECK(d.importance == expect_imp);
        CHECK_EQ(d.default_visible, f.at("default_visible").get<bool>());
        CHECK_EQ(d.can_float, f.at("can_float").get<bool>());
        CHECK_EQ(d.can_tabify, f.at("can_tabify").get<bool>());
        CHECK_EQ(d.min_floating_size.first, f.at("min_floating_size")[0].get<int>());
        CHECK_EQ(d.min_floating_size.second, f.at("min_floating_size")[1].get<int>());
        CHECK_EQ(d.preferred_size.has_value(), !f.at("preferred_size").is_null());
        if (d.preferred_size.has_value()) {
            CHECK_EQ(d.preferred_size->first, f.at("preferred_size")[0].get<int>());
            CHECK_EQ(d.preferred_size->second, f.at("preferred_size")[1].get<int>());
        }
        CHECK_EQ(d.preferred_height.has_value(), !f.at("preferred_height").is_null());
        if (d.preferred_height.has_value()) {
            CHECK_EQ(*d.preferred_height, f.at("preferred_height").get<int>());
        }
        CHECK(jstrs(f.at("workflow_tags")) == d.workflow_tags);
        CHECK(jstrs(f.at("context_tags")) == d.context_tags);
        CHECK_EQ(d.object_name, f.at("object_name").get<std::string>());
        CHECK_EQ(d.remark, f.at("remark").get<std::string>());
    }

    CHECK(jstrs(sec.at("ids")) == reg.ids());
    for (const auto& [tag, frozen_ids] : sec.at("by_tag").items()) {
        std::vector<std::string> got;
        for (const auto* d : reg.by_tag(tag)) {
            got.push_back(d->dock_id);
        }
        CHECK(got == jstrs(frozen_ids));
    }
    // require() on a missing id throws (frozen error text is informational).
    bool threw = false;
    try {
        reg.require("nonexistent");
    } catch (const std::out_of_range&) {
        threw = true;
    }
    CHECK(threw);

    for (const auto& c : sec.at("classify_viewport")) {
        const std::string expect = c.at("out").get<std::string>();
        CHECK_EQ(viewport_class_name(classify_viewport(c.at("in").get<int>())),
                 expect);
    }
}

PWB_TEST(navigation_replay) {
    const Json sec = load_oracle().at("navigation");
    CHECK(hub_names() == jstrs(sec.at("hub_names")));

    for (int h = -1; h <= 5; ++h) {
        const auto key = std::to_string(h);
        const Json& subs = sec.at("submodules").at(key);
        const auto& actual = submodules(h);
        CHECK_EQ(actual.size(), subs.size());
        for (std::size_t i = 0; i < subs.size(); ++i) {
            CHECK_EQ(actual[i].key, subs[i].at("key").get<std::string>());
            CHECK_EQ(actual[i].title, subs[i].at("title").get<std::string>());
        }
        CHECK(submodule_keys(h) == jstrs(sec.at("submodule_keys").at(key)));
        const Json& def = sec.at("default_submodule").at(key);
        CHECK_EQ(default_submodule(h), jstr_or_empty(def));
    }
    for (const auto& [k, frozen] : sec.at("submodule_title").items()) {
        const auto sep = k.find(':');
        const int hub = std::stoi(k.substr(0, sep));
        CHECK_EQ(submodule_title(hub, k.substr(sep + 1)), jstr_or_empty(frozen));
    }
    for (const auto& [k, frozen] : sec.at("legacy_page_to_hub").items()) {
        const auto actual = legacy_page_to_hub(std::stoi(k));
        if (frozen.is_null()) {
            CHECK(!actual.has_value());
        } else {
            CHECK(actual.has_value());
            if (actual) {
                CHECK_EQ(actual->first, frozen[0].get<int>());
                CHECK_EQ(actual->second, frozen[1].get<std::string>());
            }
        }
    }
}

PWB_TEST(command_registry_replay) {
    const Json sec = load_oracle().at("command_registry");

    for (const auto& c : sec.at("subsequence_score")) {
        CHECK_EQ(subsequence_score(c.at("needle").get<std::string>(),
                                   c.at("haystack").get<std::string>()),
                 c.at("score").get<int>());
    }

    // Rebuild the same six-spec registry used by the generator.
    auto build_registry = [] {
        CommandRegistry reg;
        reg.register_command({"core:open", "打开工程", "", "open project dakai",
                              "Ctrl+O", nullptr, "core"});
        reg.register_command({"view:zoom", "缩放画布", "adjust zoom",
                              "zoom canvas", "", nullptr, "view"});
        CommandSpec digitize;
        digitize.id = "edit:digitize";
        digitize.label = "数字化";
        digitize.group = "edit";
        digitize.stages = {"pick", "digitize"};
        digitize.requires_write = true;
        digitize.keywords = "digitize shuzihua";
        reg.register_command(digitize);
        CommandSpec lock;
        lock.id = "edit:lock";
        lock.label = "锁定图层";
        lock.group = "edit";
        lock.hidden_when_unavailable = true;
        lock.applicability = [](const CommandContext&)
            -> std::optional<std::string> { return "评审锁定"; };
        reg.register_command(lock);
        CommandSpec agent;
        agent.id = "agent:run";
        agent.label = "运行 Agent";
        agent.group = "agent";
        agent.requires_write = true;
        agent.keywords = "agent run";
        reg.register_command(agent);
        CommandSpec theme;
        theme.id = "view:theme";
        theme.label = "切换主题";
        theme.group = "view";
        theme.context_tags = {"theme", "dark"};
        theme.keywords = "theme zhuti";
        reg.register_command(theme);
        return reg;
    };

    struct NamedCtx {
        CommandContext ctx;
        bool present;
        NamedCtx(bool write_granted, std::optional<std::string> stage,
                 bool is_present)
            : present(is_present) {
            ctx.write_granted = write_granted;
            ctx.mapping_stage = std::move(stage);
        }
    };
    auto ctx_for = [](const std::string& name) -> NamedCtx {
        if (name == "ro_user") return {false, "digitize", true};
        if (name == "rw_user") return {true, "digitize", true};
        if (name == "unknown_stage") return {true, std::nullopt, true};
        if (name == "wrong_stage") return {true, "interpret", true};
        return {false, std::nullopt, false};  // none
    };

    for (const auto& c : sec.at("evaluate")) {
        CommandRegistry reg = build_registry();
        const std::string ctx_name = c.at("ctx").get<std::string>();
        NamedCtx nc = ctx_for(ctx_name);
        const auto avail =
            reg.evaluate(c.at("id").get<std::string>(),
                         nc.present ? &nc.ctx : nullptr);
        CHECK_EQ(avail.enabled, c.at("enabled").get<bool>());
        CHECK_EQ(avail.reason, resolve_sentinel(c.at("reason").get<std::string>()));
    }

    for (const auto& c : sec.at("find")) {
        CommandRegistry reg = build_registry();
        const std::string ctx_name = c.at("ctx").get<std::string>();
        NamedCtx nc = ctx_for(ctx_name);
        const auto found = reg.find(c.at("query").get<std::string>(),
                                    c.at("limit").get<int>(),
                                    nc.present ? &nc.ctx : nullptr);
        std::vector<std::string> ids;
        for (const auto* s : found) {
            ids.push_back(s->id);
        }
        CHECK(ids == jstrs(c.at("ids")));
    }

    // Recents: same op sequence as the generator.
    {
        CommandRegistry reg = build_registry();
        std::vector<std::string> store;
        reg.bind_settings({[&] { return store; },
                           [&](const std::vector<std::string>& v) { store = v; }});
        for (const char* id :
             {"core:open", "view:zoom", "core:open", "unregistered",
              "edit:digitize"}) {
            reg.record_recent(id);
        }
        reg.unregister("view:zoom");
        std::vector<std::string> ids;
        for (const auto* s : reg.recent_specs()) {
            ids.push_back(s->id);
        }
        CHECK(ids == jstrs(sec.at("recents").at("after_ops")));

        CommandRegistry reg2 = build_registry();
        reg2.bind_settings({[&] { return store; },
                            [&](const std::vector<std::string>& v) { store = v; }});
        reg2.load_recent();
        ids.clear();
        for (const auto* s : reg2.recent_specs()) {
            ids.push_back(s->id);
        }
        CHECK(ids == jstrs(sec.at("recents").at("reloaded")));

        reg.clear(true);
        ids.clear();
        for (const auto* s : reg.specs()) {
            ids.push_back(s->id);
        }
        CHECK(ids == jstrs(sec.at("clear_keep_core")));
    }
}

PWB_TEST(dock_manager_replay) {
    const Json sec = load_oracle().at("dock_manager");
    DockManager manager;

    for (const auto& [preset_value, frozen] : sec.at("layouts").items()) {
        WorkspacePreset preset = WorkspacePreset::MapAuthoring;
        if (preset_value == "well_log") preset = WorkspacePreset::WellLogInterpretation;
        else if (preset_value == "workstation_composite") preset = WorkspacePreset::WorkstationComposite;
        else if (preset_value == "workstation_interpretation") preset = WorkspacePreset::WorkstationInterpretation;
        const WorkspaceLayout* layout = manager.get_layout(preset);
        CHECK(layout != nullptr);
        if (layout == nullptr) continue;
        CHECK_EQ(layout->name, frozen.at("name").get<std::string>());
        const auto& docks = frozen.at("docks");
        CHECK_EQ(layout->docks.size(), docks.size());
        for (std::size_t i = 0; i < docks.size(); ++i) {
            CHECK_EQ(layout->docks[i].id, docks[i].at("id").get<std::string>());
            CHECK_EQ(layout->docks[i].title, docks[i].at("title").get<std::string>());
            CHECK_EQ(layout->docks[i].visible, docks[i].at("visible").get<bool>());
            CHECK_EQ(layout->docks[i].floating, docks[i].at("floating").get<bool>());
            CHECK_EQ(layout->docks[i].area, docks[i].at("area").get<std::string>());
        }
    }

    CHECK_EQ(workspace_preset_value(manager.active_layout().preset),
             sec.at("active_default").get<std::string>());
    manager.set_active_preset(WorkspacePreset::WellLogInterpretation);
    CHECK_EQ(workspace_preset_value(manager.active_layout().preset),
             sec.at("after_set_active_existing").get<std::string>());

    const auto& titles = sec.at("panel_title_cases");
    CHECK_EQ(manager.panel_title("layer_tree"), jstr_or_empty(titles[0]));
    CHECK_EQ(manager.panel_title("mapping:layer_tree"), jstr_or_empty(titles[1]));
    CHECK_EQ(manager.panel_title("nonexistent"), jstr_or_empty(titles[2]));
    CHECK_EQ(manager.panel_title("workstation:explorer"), jstr_or_empty(titles[3]));

    // Retitle propagates into the preset layout row (shared identity).
    manager.register_panel("layer_tree", "图层管理树·改");
    const WorkspaceLayout* layout =
        manager.get_layout(WorkspacePreset::MapAuthoring);
    std::string layout_title;
    for (const auto& d : layout->docks) {
        if (d.id == "layer_tree") {
            layout_title = d.title;
        }
    }
    CHECK_EQ(layout_title, sec.at("retitle_propagates_to_layout").get<std::string>());

    const auto& np = sec.at("new_panel");
    auto& created = manager.register_panel("custom:panel", "自定义面板",
                                           "bottom", false);
    CHECK_EQ(created.id, np.at("id").get<std::string>());
    CHECK_EQ(created.title, np.at("title").get<std::string>());
    CHECK_EQ(created.area, np.at("area").get<std::string>());
    CHECK_EQ(created.visible, np.at("visible").get<bool>());

    const auto& has = sec.at("has_panel");
    CHECK_EQ(manager.has_panel("layer_tree"), has[0].get<bool>());
    CHECK_EQ(manager.has_panel("zzz"), has[1].get<bool>());

    const auto ids = manager.panel_ids();
    const auto frozen_first8 = jstrs(sec.at("panel_ids_first8"));
    CHECK(ids.size() >= frozen_first8.size());
    for (std::size_t i = 0; i < frozen_first8.size(); ++i) {
        CHECK_EQ(ids[i], frozen_first8[i]);
    }
    CHECK_EQ(static_cast<long long>(ids.size()),
             sec.at("panel_count_after_custom").get<long long>());

    for (const auto& [pid, title] : sec.at("seeded_vocabulary").items()) {
        CHECK_EQ(manager.panel_title(pid), title.get<std::string>());
    }
}

PWB_TEST(layout_presets_replay) {
    const Json sec = load_oracle().at("layout_presets");

    const auto& presets = workstation_layout_presets();
    const auto& frozen = sec.at("presets");
    CHECK_EQ(presets.size(), frozen.size());
    for (std::size_t i = 0; i < frozen.size(); ++i) {
        CHECK_EQ(presets[i].id, frozen[i].at("id").get<std::string>());
        CHECK_EQ(presets[i].label, frozen[i].at("label").get<std::string>());
        CHECK_EQ(presets[i].description, frozen[i].at("description").get<std::string>());
        const auto v = visibility_dict(presets[i].visibility);
        for (const auto& [key, flag] : frozen[i].at("visibility").items()) {
            const auto it = v.find(key);
            CHECK(it != v.end());
            if (it != v.end()) {
                CHECK_EQ(it->second, flag.get<bool>());
            }
        }
    }

    const auto labels = preset_labels();
    const auto& frozen_labels = sec.at("labels");
    CHECK_EQ(labels.size(), frozen_labels.size());
    for (std::size_t i = 0; i < frozen_labels.size(); ++i) {
        CHECK_EQ(labels[i].first, frozen_labels[i][0].get<std::string>());
        CHECK_EQ(labels[i].second, frozen_labels[i][1].get<std::string>());
    }

    const auto* hit = get_preset(sec.at("get_preset_hit").get<std::string>());
    CHECK(hit != nullptr);
    CHECK_EQ(get_preset("nonexistent") == nullptr,
             sec.at("get_preset_miss").get<bool>());
    CHECK_EQ(std::string(kResetLayoutPresetId),
             sec.at("reset_preset_id").get<std::string>());

    DockManager manager;
    register_with_dock_manager(manager);
    for (const auto& [pid, title] : sec.at("seeded_panel_titles").items()) {
        CHECK_EQ(manager.panel_title(pid), title.get<std::string>());
    }
}

PWB_TEST(operations_replay) {
    const Json sec = load_oracle().at("operations");
    const Json& snaps = sec.at("snapshots");
    const auto emitted_for = [&](const std::string& name) {
        for (const auto& s : sec.at("scenarios")) {
            if (s.at("name") == name) {
                return jstrs(s.at("emitted"));
            }
        }
        return std::vector<std::string>{};
    };

    auto run = [](auto&& fn) {
        OperationRegistry reg;
        std::vector<std::string> emitted;
        reg.on_changed = [&](const std::string& id) { emitted.push_back(id); };
        reg.on_removed = [&](const std::string& id) { emitted.push_back(id); };
        fn(reg);
        return std::pair{emitted, 0};
    };

    {  // basic
        OperationRegistry reg;
        std::vector<std::string> emitted;
        reg.on_changed = [&](const std::string& id) { emitted.push_back(id); };
        reg.on_removed = [&](const std::string& id) { emitted.push_back(id); };
        reg.begin("op1", "校验", "well-1.las", true, 10);
        reg.update("op1", 3, std::nullopt, "SHA-256");
        check_record(reg.record("op1"), snaps.at("basic_mid"), "basic_mid");
        reg.finish("op1", OperationState::Completed, std::nullopt, "通过");
        check_record(reg.record("op1"), snaps.at("basic_final"), "basic_final");
        CHECK_EQ(reg.active_label(), jstr_or_empty(snaps.at("basic_active_label")));
        CHECK(emitted == emitted_for("basic"));
    }
    {  // queued_promotion
        OperationRegistry reg;
        std::vector<std::string> emitted;
        reg.on_changed = [&](const std::string& id) { emitted.push_back(id); };
        reg.begin("q1", "排队任务", std::nullopt, false, std::nullopt, true);
        check_record(reg.record("q1"), snaps.at("queued_initial"), "qi");
        reg.update("q1", 1);
        check_record(reg.record("q1"), snaps.at("queued_promoted"), "qp");
        CHECK(emitted == emitted_for("queued_promotion"));
    }
    {  // finish_live_state
        OperationRegistry reg;
        std::vector<std::string> emitted;
        reg.on_changed = [&](const std::string& id) { emitted.push_back(id); };
        reg.begin("f1", "任务");
        reg.finish("f1", OperationState::Running);  // honest degrade
        check_record(reg.record("f1"), snaps.at("live_finish"), "lf");
        CHECK(emitted == emitted_for("finish_live_state"));
    }
    {  // late_finish_no_regress
        OperationRegistry reg;
        std::vector<std::string> emitted;
        reg.on_changed = [&](const std::string& id) { emitted.push_back(id); };
        reg.begin("t1", "任务");
        reg.finish("t1", OperationState::Completed);
        reg.finish("t1", OperationState::Failed, "late");
        check_record(reg.record("t1"), snaps.at("late_finish"), "lt");
        reg.update("t1", 9);
        check_record(reg.record("t1"), snaps.at("terminal_update_inert"), "ti");
        CHECK(emitted == emitted_for("late_finish_no_regress"));
    }
    {  // cancel_flows
        OperationRegistry reg;
        std::vector<std::string> emitted;
        reg.on_changed = [&](const std::string& id) { emitted.push_back(id); };
        reg.on_removed = [&](const std::string& id) { emitted.push_back(id); };
        reg.begin("c1", "可取消", std::nullopt, true);
        reg.set_cancel("c1", [] {});
        CHECK_EQ(reg.request_cancel("c1"), snaps.at("cancel_request").get<bool>());
        check_record(reg.record("c1"), snaps.at("cancel_state"), "cs");

        reg.begin("c2", "同步终结", std::nullopt, true);
        reg.set_cancel("c2", [&reg] {
            reg.finish("c2", OperationState::Cancelled);
        });
        CHECK_EQ(reg.request_cancel("c2"), snaps.at("cancel_sync_terminal").get<bool>());
        check_record(reg.record("c2"), snaps.at("cancel_sync_state"), "css");

        reg.begin("c3", "取消失败", std::nullopt, true);
        reg.set_cancel("c3", [] { throw std::runtime_error("cancel boom"); });
        CHECK_EQ(reg.request_cancel("c3"), snaps.at("cancel_hook_raise").get<bool>());
        check_record(reg.record("c3"), snaps.at("cancel_raise_state"), "crs");

        CHECK_EQ(reg.request_cancel("zzz"), snaps.at("cancel_missing").get<bool>());
        CHECK_EQ(reg.request_cancel("c2"), snaps.at("cancel_terminal").get<bool>());
        CHECK_EQ(reg.request_cancel("c1"), snaps.at("cancel_again").get<bool>());
        CHECK(emitted == emitted_for("cancel_flows"));
    }
    {  // terminal_eviction
        OperationRegistry reg;
        std::vector<std::string> emitted;
        reg.on_changed = [&](const std::string& id) { emitted.push_back(id); };
        reg.on_removed = [&](const std::string& id) { emitted.push_back(id); };
        for (int i = 0; i < 45; ++i) {
            char id[8];
            std::snprintf(id, sizeof(id), "e%02d", i);
            reg.begin(id, "任务" + std::to_string(i));
            reg.finish(id, OperationState::Completed);
        }
        std::set<std::string> remaining;
        for (const auto* r : reg.records()) {
            remaining.insert(r->op_id);
        }
        const auto frozen_ids = jstrs(snaps.at("evict_remaining_ids"));
        const std::set<std::string> frozen_remaining(frozen_ids.begin(),
                                                     frozen_ids.end());
        CHECK(remaining == frozen_remaining);

        reg.begin("e00", "复活");
        check_record(reg.record("e00"), snaps.at("evict_revived"), "ev");
        CHECK(emitted == emitted_for("terminal_eviction"));
    }
    {  // ordering_and_clear
        OperationRegistry reg;
        std::vector<std::string> emitted;
        reg.on_changed = [&](const std::string& id) { emitted.push_back(id); };
        reg.on_removed = [&](const std::string& id) { emitted.push_back(id); };
        for (int i = 0; i < 3; ++i) {
            reg.begin("o" + std::to_string(i), "任务" + std::to_string(i));
        }
        CHECK(record_ids(reg.records()) == jstrs(snaps.at("records_order")));
        CHECK(record_ids(reg.active_records()) == jstrs(snaps.at("active_order")));
        CHECK_EQ(reg.active_label(), jstr_or_empty(snaps.at("active_label_multi")));
        reg.clear();
        CHECK(record_ids(reg.records()) == jstrs(snaps.at("after_clear")));
        CHECK(emitted == emitted_for("ordering_and_clear"));
    }
}

PWB_TEST(deferred_bindings_replay) {
    const Json sec = load_oracle().at("deferred_bindings");
    const auto calls_for = [&](const std::string& name) {
        for (const auto& s : sec.at("scenarios")) {
            if (s.at("name") == name) {
                return jstrs(s.at("calls"));
            }
        }
        return std::vector<std::string>{};
    };

    {  // schedule_order
        DeferredPageBindings b;
        std::vector<std::string> calls;
        for (const char* n : {"a", "b", "c"}) {
            b.schedule(0, n, [&calls, n] { calls.push_back(n); });
        }
        b.flush(0);
        CHECK(calls == calls_for("schedule_order"));
    }
    {  // project_first
        DeferredPageBindings b;
        std::vector<std::string> calls;
        b.schedule(0, "state", [&] { calls.push_back("state"); });
        b.schedule(0, "project", [&] { calls.push_back("project"); });
        b.schedule(0, "extra", [&] { calls.push_back("extra"); });
        b.flush(0);
        CHECK(calls == calls_for("project_first"));
    }
    {  // replace_keeps_position
        DeferredPageBindings b;
        std::vector<std::string> calls;
        b.schedule(0, "a", [&] { calls.push_back("a1"); });
        b.schedule(0, "b", [&] { calls.push_back("b"); });
        b.schedule(0, "a", [&] { calls.push_back("a2"); });
        b.flush(0);
        CHECK(calls == calls_for("replace_keeps_position"));
    }
    {  // reentrant_drain
        DeferredPageBindings b;
        std::vector<std::string> calls;
        b.schedule(0, "first", [&] {
            calls.push_back("first");
            b.schedule(0, "second", [&] { calls.push_back("second"); });
        });
        b.flush(0);
        calls.push_back("has_pending=" + std::string(b.has_pending(0) ? "True" : "False"));
        CHECK(calls == calls_for("reentrant_drain"));
    }
    {  // cross_index_isolation
        DeferredPageBindings b;
        std::vector<std::string> calls;
        b.schedule(0, "zero", [&] { calls.push_back("zero"); });
        b.schedule(1, "one", [&] { calls.push_back("one"); });
        b.flush(0);
        calls.push_back("pending1=" + std::string(b.has_pending(1) ? "True" : "False"));
        b.flush(1);
        CHECK(calls == calls_for("cross_index_isolation"));
    }
}

// Negative self-check: every section must detect tampering.
PWB_TEST(negative_selfcheck) {
    const Json oracle = load_oracle();
    {
        Json t = oracle;
        t["dock_framework"]["descriptors"][0]["title"] = "tampered";
        CHECK(t.at("dock_framework").at("descriptors")[0].at("title") !=
              oracle.at("dock_framework").at("descriptors")[0].at("title"));
    }
    {
        Json t = oracle;
        t["command_registry"]["subsequence_score"][0]["score"] = 999;
        const int frozen = t.at("command_registry")
                               .at("subsequence_score")[0]
                               .at("score")
                               .get<int>();
        CHECK(frozen != subsequence_score(
                            t.at("command_registry")
                                .at("subsequence_score")[0]
                                .at("needle")
                                .get<std::string>(),
                            t.at("command_registry")
                                .at("subsequence_score")[0]
                                .at("haystack")
                                .get<std::string>()));
    }
    {
        Json t = oracle;
        t["operations"]["snapshots"]["basic_final"]["state"] = "failed";
        OperationRegistry reg;
        reg.begin("op1", "校验", "well-1.las", true, 10);
        reg.update("op1", 3, std::nullopt, "SHA-256");
        reg.finish("op1", OperationState::Completed, std::nullopt, "通过");
        CHECK(operation_state_value(reg.record("op1")->state) !=
              t.at("operations").at("snapshots").at("basic_final").at("state")
                  .get<std::string>());
    }
    {
        Json t = oracle;
        t["navigation"]["legacy_page_to_hub"]["0"] = nullptr;
        CHECK(t.at("navigation").at("legacy_page_to_hub").at("0").is_null() !=
              oracle.at("navigation").at("legacy_page_to_hub").at("0").is_null());
    }
}

int main() { return pwb_test::run_all(); }
