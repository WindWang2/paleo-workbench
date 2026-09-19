// mapping_document.bridge_session — CONV-27d bridge edit domain vs the frozen
// Python oracle + C++-contract sections.
//
// Oracle replay (fixtures/map_document_bridge_oracle.json, produced by
// tools/oracle/generate_map_document_bridge_fixtures.py from the real Python
// product code):
//   * session_set_cases — EditSessionSet lifecycle / join gate / mutex
//     messages / stack-bound suppression window;
//   * gesture_cases — EditGestureManager plans, marks, audit stream;
//   * native_cases — NativeEditSessionController against fakes mirroring
//     tests/test_topo_m1_native_editing.py (bridge calls, layer write-backs,
//     commit gates, mid-commit failure compensation);
//   * snapshot_cases — document_render_snapshot grouping/styles/extents;
//     content-derived revision VALUES are C++-contract (the Python small-
//     collection path is process-local hash()) and only checked for
//     determinism + distinctness.
//
// C++-contract sections: deterministic content digest, LRU reuse via cache
// owner identity, negative self-checks (a deliberately corrupted expectation
// must be detected by this harness itself).

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping_document/edit_gesture_manager.hpp>
#include <pwb/mapping_document/edit_session_set.hpp>
#include <pwb/mapping_document/native_edit_session.hpp>
#include <pwb/mapping_document/render_snapshot.hpp>

using pwb::domain::Json;
using namespace pwb::mapping_document;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

bool semantic_equal(const Json& got, const Json& want) {
    return pwb::domain::json_semantically_equal(got, want);
}

void expect_equal(const Json& got, const Json& want, const std::string& what) {
    const pwb::domain::JsonDiff diff =
        pwb::domain::json_semantic_diff(got, want);
    check(diff.equal, what + " [" + diff.path + ": " + diff.reason +
                          "] got=" + got.dump() + " want=" + want.dump());
}

const Json& fixture() {
    static const Json* cached = [] {
        std::ifstream stream(PWB_MAPPING_DOCUMENT_BRIDGE_FIXTURE,
                             std::ios::binary);
        if (!stream.good()) {
            std::fprintf(stderr, "FAIL cannot open %s\n",
                         PWB_MAPPING_DOCUMENT_BRIDGE_FIXTURE);
            std::exit(1);
        }
        std::ostringstream buffer;
        buffer << stream.rdbuf();
        return new Json(Json::parse(buffer.str()));
    }();
    return *cached;
}

// ---------------------------------------------------------------------------
// Fakes mirroring the Python-side doubles in the fixture generator
// ---------------------------------------------------------------------------

class FakeNativeStack : public NativeEditBridgeStack {
public:
    std::string name;
    std::set<std::string> editing;
    std::vector<Json> calls;
    std::map<std::string, std::vector<Json>> mirror;
    std::map<std::string, Json> pending_delta;
    std::set<std::string> fail_commit;
    std::function<void(const std::string&, const Json&)> committed_callback;
    bool supports = true;
    // DirtyProbe shape: null = no query surface.
    bool has_dirty_probe = false;
    std::map<std::string, bool> dirty_state;
    bool has_restore = false;

    explicit FakeNativeStack(std::string n) : name(std::move(n)) {}

    bool supports_native_editing() const override { return supports; }

    std::string start_mirror_layer_editing(const std::string& doc_id) override {
        calls.push_back(make_call("start", doc_id));
        editing.insert(doc_id);
        return "";
    }
    std::string roll_back_mirror_layer(const std::string& doc_id) override {
        calls.push_back(make_call("rollback", doc_id));
        editing.erase(doc_id);
        return "";
    }
    std::string commit_mirror_layer(const std::string& doc_id) override {
        if (editing.count(doc_id) == 0) return "layer not editing";
        if (fail_commit.count(doc_id) != 0) {
            calls.push_back(make_call("commit-failed", doc_id));
            return "simulated commit failure";
        }
        calls.push_back(make_call("commit", doc_id));
        editing.erase(doc_id);
        // Python: delta = self.pending_delta.pop(doc_id, {"doc_id": doc_id}).
        Json delta = pending_delta.count(doc_id) != 0
                         ? pending_delta.at(doc_id)
                         : Json::object();
        delta["doc_id"] = doc_id;
        if (committed_callback) committed_callback(doc_id, delta.dump());
        return "";
    }
    Json mirror_features_json(const std::string& doc_id, int /*limit*/) override {
        Json out = Json::object();
        out["exists"] = mirror.count(doc_id) != 0;
        Json features = Json::array();
        auto it = mirror.find(doc_id);
        if (it != mirror.end()) {
            for (const Json& f : it->second) features.push_back(f);
        }
        out["features"] = std::move(features);
        return out;
    }
    std::string undo_mirror_edit(const std::string& doc_id) override {
        calls.push_back(make_call("undo", doc_id));
        return "";
    }
    std::string redo_mirror_edit(const std::string& doc_id) override {
        calls.push_back(make_call("redo", doc_id));
        return "";
    }
    void set_committed_callback(
        std::uintptr_t /*canvas*/,
        const std::function<void(const std::string&, const Json&)>& callback)
        override {
        committed_callback = callback;
    }

    // DirtyProbeStack / AttributeWriteStack shapes (opt-in via flags).
    std::optional<bool> mirror_layer_dirty(const std::string& doc_id) override {
        if (!has_dirty_probe) return std::nullopt;
        return dirty_state.count(doc_id) != 0 && dirty_state.at(doc_id);
    }
    bool has_attribute_write() const override { return attr_write; }
    std::string set_mirror_feature_attributes(const std::string& doc_id,
                                              const Json& ids,
                                              const Json& values) override {
        Json call = Json::array();
        call.push_back("set_attrs");
        call.push_back(doc_id);
        call.push_back(ids);
        call.push_back(values);
        calls.push_back(std::move(call));
        return "";
    }
    bool attr_write = false;
    bool has_restore_snapshot() const override { return has_restore; }
    std::string restore_mirror_snapshot(const std::string& doc_id,
                                        const Json& snapshot) override {
        calls.push_back(make_call("restore", doc_id));
        auto features = snapshot.find("features");
        mirror[doc_id] =
            features != snapshot.end() && features->is_array()
                ? *features
                : Json::array();
        editing.insert(doc_id);
        return "";
    }

private:
    static Json make_call(const char* kind, const std::string& doc_id) {
        Json call = Json::array();
        call.push_back(kind);
        call.push_back(doc_id);
        return call;
    }
};

class FakeLayer : public ICommittedDeltaSink {
public:
    std::string layer_id;
    std::string layer_name;
    std::string layer_crs;
    std::vector<Json> calls;

    FakeLayer(std::string id, std::string name, std::string crs)
        : layer_id(std::move(id)), layer_name(std::move(name)),
          layer_crs(std::move(crs)) {}

    const std::string& id() const override { return layer_id; }
    const std::string& name() const override { return layer_name; }
    const std::string& crs() const override { return layer_crs; }
    void apply_committed_delta(const Json& delta, const std::string& session_id,
                               const std::string& source_tool,
                               const Json& gestures) override {
        Json entry = Json::object();
        entry["delta"] = delta;
        entry["session_id"] = session_id;
        entry["source_tool"] = source_tool;
        entry["gestures"] = gestures;
        calls.push_back(std::move(entry));
    }
};

class FakeTopologyGate : public ICommitTopologyGate {
public:
    bool enabled_ = true;
    bool has_checker = false;
    std::vector<Json> checker_issues;
    std::map<std::string, long long> validate_issues;
    std::vector<std::pair<std::string, long long>> validations;

    bool enabled() const override { return enabled_; }
    RunResult run_for_commit(NativeEditBridgeStack& /*stack*/,
                             std::uintptr_t /*canvas*/,
                             const std::vector<std::string>& /*layer_ids*/)
        override {
        if (!has_checker) return {};
        return RunResult{true, checker_issues};
    }
    std::vector<Json> validate_records(
        const std::string& layer_id,
        const std::vector<Json>& /*records*/) override {
        std::vector<Json> issues;
        auto it = validate_issues.find(layer_id);
        const long long count = it == validate_issues.end() ? 0 : it->second;
        for (long long i = 0; i < count; ++i) {
            Json issue = Json::object();
            issue["layer_id"] = layer_id;
            issue["feature_id"] = "bad-" + std::to_string(i);
            issue["message"] = "err";
            issues.push_back(std::move(issue));
        }
        return issues;
    }
    void record_validation(const std::string& layer_id,
                           std::size_t issue_count) override {
        validations.emplace_back(layer_id,
                                 static_cast<long long>(issue_count));
    }
};

// ---------------------------------------------------------------------------
// Context construction from the frozen build specs
// ---------------------------------------------------------------------------

struct BridgeContext {
    std::map<std::string, std::unique_ptr<FakeNativeStack>> stacks;
    std::map<std::string, std::unique_ptr<FakeLayer>> layers;
    std::map<std::string, EditGate> gates;
    std::map<std::string, std::unique_ptr<FakeTopologyGate>> topologies;
    std::map<std::string, GeologyGate> geologies;
};

std::string scalar_text(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_null()) return "";
    return value.dump();
}

void build_context(const Json& build, BridgeContext& ctx) {
    for (const Json& spec : build) {
        const std::string kind = spec.value("kind", "");
        const std::string name = spec.value("name", "");
        if (kind == "stack") {
            auto stack = std::make_unique<FakeNativeStack>(name);
            const std::string shape = spec.value("shape", "fake");
            if (shape == "old") stack->supports = false;
            if (shape == "attrs") stack->attr_write = true;
            if (shape == "dirty") stack->has_dirty_probe = true;
            if (shape == "restorable") stack->has_restore = true;
            auto mirror = spec.find("mirror");
            if (mirror != spec.end() && mirror->is_object()) {
                for (auto it = mirror->begin(); it != mirror->end(); ++it) {
                    std::vector<Json> features;
                    for (const Json& f : it.value()) features.push_back(f);
                    stack->mirror[it.key()] = std::move(features);
                }
            }
            auto deltas = spec.find("pending_delta");
            if (deltas != spec.end() && deltas->is_object()) {
                for (auto it = deltas->begin(); it != deltas->end(); ++it) {
                    stack->pending_delta[it.key()] = it.value();
                }
            }
            auto fails = spec.find("fail_commit");
            if (fails != spec.end() && fails->is_array()) {
                for (const Json& id : *fails) {
                    stack->fail_commit.insert(id.get<std::string>());
                }
            }
            ctx.stacks[name] = std::move(stack);
        } else if (kind == "layer") {
            const std::string layer_id = spec.value("layer_id", name);
            ctx.layers[name] = std::make_unique<FakeLayer>(
                layer_id, spec.value("display", std::string("")),
                spec.value("crs", std::string("")));
        } else if (kind == "gate") {
            const std::string gate_name = name;
            if (spec.value("allow_all", false)) {
                ctx.gates[gate_name] =
                    [](const std::string&) { return std::pair(true, ""); };
            } else {
                std::vector<std::string> allow;
                auto allow_it = spec.find("allow");
                if (allow_it != spec.end() && allow_it->is_array()) {
                    for (const Json& id : *allow_it) {
                        allow.push_back(id.get<std::string>());
                    }
                }
                const std::string reason =
                    spec.value("reason", std::string("门禁拒绝"));
                ctx.gates[gate_name] =
                    [allow, reason](const std::string& layer_id) {
                        if (std::find(allow.begin(), allow.end(), layer_id) !=
                            allow.end()) {
                            return std::pair(true, std::string());
                        }
                        return std::pair(false, reason);
                    };
            }
        } else if (kind == "topology") {
            auto gate = std::make_unique<FakeTopologyGate>();
            gate->enabled_ = spec.value("enabled", true);
            auto checker = spec.find("checker_issues");
            if (checker != spec.end() && checker->is_array()) {
                gate->has_checker = true;
                for (const Json& issue : *checker) gate->checker_issues.push_back(issue);
            }
            auto issues = spec.find("validate_issues");
            if (issues != spec.end() && issues->is_object()) {
                for (auto it = issues->begin(); it != issues->end(); ++it) {
                    gate->validate_issues[it.key()] = it->get<long long>();
                }
            }
            ctx.topologies[name] = std::move(gate);
        } else if (kind == "geology") {
            Json violations = Json::array();
            auto v = spec.find("violations");
            if (v != spec.end() && v->is_array()) violations = *v;
            ctx.geologies[name] =
                [violations](const std::map<std::string, std::vector<Json>>&
                             /*records*/) { return violations; };
        }
    }
}

Json calls_to_json(const std::vector<Json>& calls) {
    Json out = Json::array();
    for (const Json& call : calls) out.push_back(call);
    return out;
}

// ---------------------------------------------------------------------------
// Session-set replay
// ---------------------------------------------------------------------------

Json session_set_state(const EditSessionSet& subject) {
    auto [allowed, reason] = subject.allows_crs_change();
    Json state = Json::object();
    Json ids = Json::array();
    for (const std::string& id : subject.layer_ids()) ids.push_back(id);
    state["layer_ids"] = ids;
    state["is_open"] = subject.is_open();
    state["frozen_crs"] = subject.frozen_crs();
    Json crs_verdict = Json::array();
    crs_verdict.push_back(allowed);
    crs_verdict.push_back(reason);
    state["allows_crs_change"] = crs_verdict;
    return state;
}

void replay_session_set_cases() {
    for (const Json& oracle_case : fixture()["session_set_cases"]) {
        const std::string case_name = oracle_case.value("name", "");
        EditSessionSet subject;
        // Identity tokens mirroring the generator's `object()` stacks: one
        // live dummy per name, identity = address.
        std::map<std::string, const void*> stacks;
        std::vector<int> tokens(oracle_case["stack_names"].size());
        std::size_t token_index = 0;
        for (const Json& stack_name : oracle_case["stack_names"]) {
            stacks[stack_name.get<std::string>()] = &tokens[token_index++];
        }
        for (const Json& entry : oracle_case["results"]) {
            const Json& op = entry["op"];
            const std::string kind = op.value("op", "");
            const std::string what = case_name + "/" + kind;
            if (kind == "open") {
                subject.open(op.value("layer_id", ""),
                             op.value("crs", std::string()),
                             stacks.at(op.value("stack", "")));
            } else if (kind == "request_join") {
                EditSessionSet::Gate gate;
                const Json& gate_spec = op.value("gate", Json());
                if (!gate_spec.is_null()) {
                    std::set<std::string> accepted;
                    for (const Json& id : gate_spec.value("accepted", Json())) {
                        accepted.insert(id.get<std::string>());
                    }
                    std::map<std::string, std::string> reasons;
                    const Json reason_spec =
                        gate_spec.value("reason", Json());
                    for (auto it = reason_spec.begin();
                         it != reason_spec.end(); ++it) {
                        reasons[it.key()] = it.value().get<std::string>();
                    }
                    gate = [accepted, reasons](const std::string& layer_id) {
                        if (accepted.count(layer_id) != 0) {
                            return std::pair(true, std::string());
                        }
                        auto reason = reasons.find(layer_id);
                        return std::pair(
                            false, reason == reasons.end() ? std::string()
                                                           : reason->second);
                    };
                }
                std::vector<std::string> ids;
                for (const Json& id : op["layer_ids"]) ids.push_back(id.get<std::string>());
                Json decisions = Json::array();
                for (const JoinDecision& decision :
                     subject.request_join(ids, gate)) {
                    Json d = Json::object();
                    d["layer_id"] = decision.layer_id;
                    d["accepted"] = decision.accepted;
                    d["reason"] = decision.reason;
                    decisions.push_back(std::move(d));
                }
                expect_equal(decisions, entry.value("decisions", Json()),
                             what + "/decisions");
            } else if (kind == "discard") {
                subject.discard(op.value("layer_id", ""));
            } else if (kind == "close") {
                Json closed = Json::array();
                for (const std::string& id : subject.close()) closed.push_back(id);
                expect_equal(closed, entry.value("closed_layers", Json()),
                             what + "/closed_layers");
            } else if (kind == "active_layer_ids") {
                Json active = Json::array();
                for (const std::string& id : subject.active_layer_ids(
                         stacks.at(op.value("stack", "")))) {
                    active.push_back(id);
                }
                expect_equal(active, entry.value("active_layer_ids", Json()),
                             what + "/active_layer_ids");
            } else if (kind == "allows_crs_change") {
                auto [allowed, reason] = subject.allows_crs_change();
                check(allowed == entry["allowed"].get<bool>() &&
                          reason == entry["reason"].get<std::string>(),
                      what + "/verdict");
            } else if (kind == "allows_schema_change") {
                auto [allowed, reason] =
                    subject.allows_schema_change(op.value("layer_id", ""));
                check(allowed == entry["allowed"].get<bool>() &&
                          reason == entry["reason"].get<std::string>(),
                      what + "/verdict");
            }
            expect_equal(session_set_state(subject), entry["state"],
                         what + "/state");
        }
    }
}

// ---------------------------------------------------------------------------
// Gesture replay
// ---------------------------------------------------------------------------

void replay_gesture_cases() {
    for (const Json& oracle_case : fixture()["gesture_cases"]) {
        const std::string case_name = oracle_case.value("name", "");
        EditGestureManager manager;
        for (const Json& entry : oracle_case["results"]) {
            const Json& op = entry["op"];
            const std::string kind = op.value("op", "");
            const std::string what = case_name + "/" + kind;
            if (kind == "finish") {
                std::vector<std::string> ids;
                for (const Json& id : op["layer_ids"]) ids.push_back(id.get<std::string>());
                const GestureRecord record = manager.finish(
                    op.value("gesture_id", ""), op.value("undo_text", ""), ids);
                Json frozen = Json::object();
                frozen["gesture_id"] = record.gesture_id;
                frozen["undo_text"] = record.undo_text;
                frozen["layer_ids"] = record.layer_ids;
                frozen["undone"] = record.undone;
                expect_equal(frozen, entry["record"], what + "/record");
            } else if (kind == "undo_plan" || kind == "redo_plan") {
                const std::vector<std::string> plan =
                    kind == "undo_plan" ? manager.undo_plan()
                                        : manager.redo_plan();
                Json frozen = plan;
                expect_equal(frozen, entry["plan"], what + "/plan");
            } else if (kind == "mark_undone") {
                manager.mark_undone(op.value("gesture_id", ""));
            } else if (kind == "mark_redone") {
                manager.mark_redone(op.value("gesture_id", ""));
            } else if (kind == "current_gesture_id") {
                check(manager.current_gesture_id() ==
                          entry["gesture_id"].get<std::string>(),
                      what + "/gesture_id");
            } else if (kind == "clear") {
                manager.clear();
            }
            expect_equal(manager.audit_records(), entry["audit"], what + "/audit");
        }
    }
}

// ---------------------------------------------------------------------------
// Native controller replay
// ---------------------------------------------------------------------------

Json capture_context(const BridgeContext& ctx) {
    Json out = Json::object();
    for (const auto& [name, stack] : ctx.stacks) {
        out[name] = calls_to_json(stack->calls);
    }
    return out;
}

Json layer_calls_json(const BridgeContext& ctx) {
    Json out = Json::object();
    for (const auto& [name, layer] : ctx.layers) {
        out[name] = calls_to_json(layer->calls);
    }
    return out;
}

void replay_native_cases() {
    for (const Json& oracle_case : fixture()["native_cases"]) {
        const std::string case_name = oracle_case.value("name", "");
        BridgeContext ctx;
        build_context(oracle_case.value("build", Json()), ctx);
        NativeEditSessionController controller;
        for (const Json& entry : oracle_case["results"]) {
            const std::string kind = entry.value("op", "");
            const std::string what = case_name + "/" + kind;
            const Json& op = entry.value("args", Json());
            if (kind == "bridge_supports") {
                check(controller.bridge_supports(
                          *ctx.stacks.at(op.value("stack", ""))) ==
                          entry["supported"].get<bool>(),
                      what);
            } else if (kind == "open") {
                auto [ok, reason] = controller.open(
                    *ctx.stacks.at(op.value("stack", "")),
                    *ctx.layers.at(op.value("layer", "")),
                    op.contains("gate")
                        ? ctx.gates.at(op.value("gate", ""))
                        : nullptr,
                    static_cast<std::uintptr_t>(op.value("canvas", 0)));
                check(ok == entry["ok"].get<bool>(), what + "/ok");
                check(reason == entry["reason"].get<std::string>(),
                      what + "/reason");
                Json sessions = controller.session_layer_ids();
                expect_equal(sessions, entry["sessions"], what + "/sessions");
                Json editing = Json::array();
                for (const std::string& id : ctx.stacks.at(op.value("stack", ""))
                                                ->editing) {
                    editing.push_back(id);
                }
                expect_equal(editing, entry["bridge_editing"],
                             what + "/bridge_editing");
            } else if (kind == "rollback") {
                auto [ok, reason] = controller.rollback(op.value("layer_id", ""));
                check(ok == entry["ok"].get<bool>(), what + "/ok");
                check(reason == entry["reason"].get<std::string>(),
                      what + "/reason");
                expect_equal(Json(controller.session_layer_ids()),
                             entry["sessions"], what + "/sessions");
            } else if (kind == "readback_features") {
                const std::vector<Json> records = controller.readback_features(
                    *ctx.stacks.at(op.value("stack", "")),
                    op.value("layer_id", ""));
                Json frozen = Json::array();
                for (const Json& record : records) frozen.push_back(record);
                expect_equal(frozen, entry["records"], what + "/records");
            } else if (kind == "set_feature_attributes") {
                std::vector<std::string> ids;
                for (const Json& id : op["feature_ids"]) ids.push_back(id.get<std::string>());
                auto [ok, reason] = controller.set_feature_attributes(
                    op.value("layer_id", ""), ids, op.value("attributes", Json()));
                check(ok == entry["ok"].get<bool>(), what + "/ok");
                check(reason == entry["reason"].get<std::string>(),
                      what + "/reason");
            } else if (kind == "pending_changes") {
                const std::optional<bool> pending =
                    controller.pending_changes(op.value("layer_id", ""));
                const Json& want = entry["pending"];
                if (want.is_null()) {
                    check(pending == std::nullopt, what + "/pending");
                } else {
                    check(pending != std::nullopt && *pending == want.get<bool>(),
                          what + "/pending");
                }
            } else if (kind == "commit_all") {
                std::vector<std::string> committed_calls;
                OnCommitted on_committed;
                if (op.value("observe_committed", false)) {
                    on_committed = [&committed_calls](const ICommittedDeltaSink& layer) {
                        committed_calls.push_back(layer.id());
                    };
                }
                FakeTopologyGate* topology = nullptr;
                if (op.contains("topology")) {
                    topology = ctx.topologies.at(op.value("topology", "")).get();
                }
                GeologyGate geology;
                if (op.contains("geology")) {
                    geology = ctx.geologies.at(op.value("geology", ""));
                }
                auto [ok, reason] = controller.commit_all(
                    op.contains("gate") ? ctx.gates.at(op.value("gate", ""))
                                        : nullptr,
                    topology, geology, on_committed);
                check(ok == entry["ok"].get<bool>(), what + "/ok");
                check(reason == entry["reason"].get<std::string>(),
                      what + "/reason got=[" + reason + "]");
                expect_equal(Json(controller.session_layer_ids()),
                             entry["sessions"], what + "/sessions");
                expect_equal(Json(committed_calls),
                             entry.value("on_committed", Json()),
                             what + "/on_committed got=" + Json(committed_calls).dump());
                if (entry.contains("validations")) {
                    Json validations = Json::array();
                    for (const auto& [layer_id, count] :
                         topology->validations) {
                        Json pair = Json::array();
                        pair.push_back(layer_id);
                        // nlohmann parses positive JSON ints as unsigned;
                        // match that type so semantic comparison is exact.
                        pair.push_back(static_cast<std::uint64_t>(count));
                        validations.push_back(std::move(pair));
                    }
                    expect_equal(validations, entry["validations"],
                                 what + "/validations");
                }
            } else if (kind == "undo_gesture") {
                check(controller.undo_gesture() == entry["ok"].get<bool>(), what);
            } else if (kind == "redo_gesture") {
                check(controller.redo_gesture() == entry["ok"].get<bool>(), what);
            } else if (kind == "compensations") {
                Json comp = controller.compensations();
                expect_equal(comp, entry["compensations"], what);
            } else if (kind == "handle_committed") {
                controller.handle_committed(op.value("doc_id", ""),
                                            op.value("delta", Json()));
            }
            expect_equal(capture_context(ctx), entry["bridge_calls"],
                         what + "/bridge_calls");
            expect_equal(layer_calls_json(ctx), entry["layer_calls"],
                         what + "/layer_calls");
            expect_equal(session_set_state(controller.session_set()),
                         entry["session_set"], what + "/session_set");
        }
    }
}

// ---------------------------------------------------------------------------
// Snapshot replay
// ---------------------------------------------------------------------------

void expect_extent_close(const Extent& got, const Json& want,
                         const std::string& what) {
    bool ok = want.is_array() && want.size() == 4;
    for (int i = 0; ok && i < 4; ++i) {
        ok = std::abs(got[static_cast<std::size_t>(i)] -
                      want[static_cast<std::size_t>(i)].get<double>()) < 1e-12;
    }
    check(ok, what);
}

void replay_snapshot_cases() {
    for (const Json& oracle_case : fixture()["snapshot_cases"]) {
        const std::string case_name = oracle_case.value("name", "");
        const Json& document = oracle_case.contains("document")
                                   ? oracle_case["document"]
                                   : Json();
        RenderSnapshotOptions options;
        options.project_crs = oracle_case.value("project_crs", std::string());
        Json style_defaults = oracle_case["style_defaults"];
        StyleDefaultProvider provider =
            [style_defaults](const std::string& kind) {
                return style_defaults.value(kind, Json::object());
            };
        const Json& frozen = oracle_case["layers"];
        // First pass: visibility / records / revisions options.
        const Json visibility = oracle_case.value("visibility", Json());
        for (auto it = visibility.begin(); it != visibility.end(); ++it) {
            options.visibility[it.key()] = it.value().get<bool>();
        }
        // The Python options are None when absent — frozen as JSON null;
        // only a non-null payload overrides the document import.
        if (oracle_case.contains("records") && oracle_case["records"].is_array()) {
            options.records = oracle_case["records"];
        }
        if (oracle_case.contains("data_revisions") &&
            oracle_case["data_revisions"].is_object()) {
            for (auto it = oracle_case["data_revisions"].begin();
                 it != oracle_case["data_revisions"].end(); ++it) {
                options.data_revisions[it.key()] = it.value().get<long long>();
            }
        }
        if (oracle_case.contains("layer_revisions") &&
            oracle_case["layer_revisions"].is_object()) {
            for (auto it = oracle_case["layer_revisions"].begin();
                 it != oracle_case["layer_revisions"].end(); ++it) {
                options.layer_revisions[it.key()] = it.value().get<long long>();
            }
        }
        const RenderSnapshot snapshot =
            document_render_snapshot(document, options, provider);
        Json project_crs = snapshot.project_crs;
        expect_equal(project_crs, oracle_case["project_crs"], case_name + "/crs");
        check(snapshot.layers.size() == frozen.size(),
              case_name + "/layer count");
        for (std::size_t i = 0;
             i < snapshot.layers.size() && i < frozen.size(); ++i) {
            const RenderLayerSnapshot& layer = snapshot.layers[i];
            const Json& want = frozen[i];
            const std::string what =
                case_name + "/" + std::to_string(i) + " " + layer.id;
            check(layer.id == want["id"].get<std::string>(), what + "/id");
            check(layer.name == want["name"].get<std::string>(), what + "/name");
            check(layer.layer_type == want["layer_type"].get<std::string>(),
                  what + "/layer_type");
            check(layer.crs == want["crs"].get<std::string>(), what + "/crs");
            check(layer.visible == want["visible"].get<bool>(), what + "/visible");
            expect_extent_close(layer.extent, want["extent"], what + "/extent");
            Json features = Json::array();
            for (const Json& feature : layer.features) features.push_back(feature);
            expect_equal(features, want["features"], what + "/features");
            expect_equal(layer.style, want["style"], what + "/style");
            // Content-derived revisions: C++ contract — deterministic and
            // distinct, never compared to the (process-local) Python value.
            if (!want["data_revision"].is_null()) {
                check(layer.data_revision ==
                          want["data_revision"].get<long long>(),
                      what + "/data_revision");
            }
        }
        expect_extent_close(extent_for_snapshot(snapshot),
                            oracle_case["full_extent"], case_name + "/full_extent");
    }
}

// C++ contract: content revisions are deterministic across calls and runs,
// and they actually distinguish content.
void contract_content_revision_determinism() {
    const Json a = Json::parse(R"({"x": [1, 2.5, "s"], "y": null, "z": true})");
    const Json b = Json::parse(R"({"x": [1, 2.5, "s"], "y": null, "z": false})");
    check(stable_content_revision(a) == stable_content_revision(a),
          "content revision is deterministic");
    check(stable_content_revision(a) != stable_content_revision(b),
          "content revision distinguishes content");
    Json reordered = Json::parse(R"({"z": true, "y": null, "x": [1, 2.5, "s"]})");
    check(stable_content_revision(a) == stable_content_revision(reordered),
          "content revision ignores object key order");
    Json int_vs_float = Json::parse(R"({"x": [1, 2.50001, "s"], "y": null, "z": true})");
    check(stable_content_revision(a) != stable_content_revision(int_vs_float),
          "content revision distinguishes numeric content");
}

// C++ contract: revision-keyed reuse without re-walking (the owner LRU), and
// no cross-owner leakage.
void contract_owner_lru_reuse() {
    Json document = Json::parse(R"({
        "id": "map_lru",
        "facies_polygons": [{"id": "p1", "kind": "facies", "name": "a",
            "geometry": {"type": "Polygon", "coordinates": [
                [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]]}}],
        "well_overlays": [], "line_features": [], "label_features": []
    })");
    StyleDefaultProvider provider = [](const std::string&) {
        return Json::object();
    };
    int owner_a = 0;
    int owner_b = 0;
    RenderSnapshotOptions base;
    base.project_crs = "EPSG:4326";
    base.data_revisions = {{"facies", 5}};
    base.cache_owner = &owner_a;
    const RenderSnapshot first = document_render_snapshot(document, base, provider);
    check(first.layers[0].data_revision == 5, "lru host revision honored");
    // Same owner + same revision → the cached tuple is reused verbatim
    // (features equal), even if the underlying document changed.
    document["facies_polygons"][0]["geometry"]["coordinates"][0][0][0] = 9.0;
    const RenderSnapshot second = document_render_snapshot(document, base, provider);
    Json first_features = first.layers[0].features;
    Json second_features = second.layers[0].features;
    check(semantic_equal(first_features, second_features),
          "lru reuses cached features for unchanged revision");
    // A different revision busts the cache (fresh walk sees the change).
    base.data_revisions = {{"facies", 6}};
    const RenderSnapshot third = document_render_snapshot(document, base, provider);
    check(third.layers[0].features[0]["geometry"]["coordinates"][0][0][0] ==
              9.0,
          "revision bump rebuilds features");
    // Another owner with the same revision does NOT reuse owner A's entries.
    base.data_revisions = {{"facies", 5}};
    base.cache_owner = &owner_b;
    const RenderSnapshot fourth = document_render_snapshot(document, base, provider);
    check(fourth.layers[0].features[0]["geometry"]["coordinates"][0][0][0] ==
              9.0,
          "lru never leaks across owners");
}

// C++ contract: previous_layers reuse matches the revision-keyed path.
void contract_previous_layers_reuse() {
    Json document = Json::parse(R"({
        "id": "map_prev",
        "facies_polygons": [{"id": "p1", "kind": "facies", "name": "a",
            "geometry": {"type": "Polygon", "coordinates": [
                [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]}}],
        "well_overlays": [], "line_features": [], "label_features": []
    })");
    StyleDefaultProvider provider = [](const std::string&) {
        return Json::object();
    };
    RenderSnapshotOptions options;
    options.project_crs = "EPSG:4326";
    options.data_revisions = {{"facies", 2}};
    const RenderSnapshot first = document_render_snapshot(document, options, provider);
    options.previous_layers = &first;
    document["facies_polygons"][0]["geometry"]["coordinates"][0][2] = 5.0;
    const RenderSnapshot second = document_render_snapshot(document, options, provider);
    check(semantic_equal(Json(first.layers[0].features),
                         Json(second.layers[0].features)),
          "previous_layers reuse keeps stale-revision features");
}

// Negative self-checks: the harness must DETECT corrupted expectations.
void negative_self_checks() {
    const Json& oracle = fixture();
    check(!oracle["session_set_cases"].empty(), "negative: fixture present");

    // A mutated reason string must not compare equal.
    const Json truthy_reason = Json("图层角色为「原始相图（RAW）」——不可直接编辑；请创建 DERIVED 草稿后编辑");
    const Json mutated_reason = Json("图层角色为「原始相图（RAW）」——不可直接编辑；请创建 DERIVED 草稿后编辑!");
    check(!semantic_equal(truthy_reason, mutated_reason),
          "negative: reason mutation detected");

    // Layer-order mutation must not compare equal.
    const Json& snapshot_case = oracle["snapshot_cases"][0];
    Json corrupted = snapshot_case["layers"];
    if (corrupted.size() >= 2) {
        std::swap(corrupted[0], corrupted[1]);
        check(!semantic_equal(corrupted, snapshot_case["layers"]),
              "negative: layer-order mutation detected");
    }

    // A suppressed join decision flip must be detected.
    Json decision = Json::object();
    decision["layer_id"] = "raw-1";
    decision["accepted"] = true;
    decision["reason"] = "";
    check(!semantic_equal(decision, Json::parse(
        R"({"layer_id": "raw-1", "accepted": false, "reason": "门禁拒绝"})")),
        "negative: join verdict mutation detected");
}

}  // namespace

int main() {
    replay_session_set_cases();
    replay_gesture_cases();
    replay_native_cases();
    replay_snapshot_cases();
    contract_content_revision_determinism();
    contract_owner_lru_reuse();
    contract_previous_layers_reuse();
    negative_self_checks();
    std::fprintf(stderr, "%d checks, %d failures\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
