// workflow_engine.store — CONV-32 oracle replay: C++ WorkflowRunStore +
// describe_reproduction vs the frozen Python fixture
// (workflow_store_oracle.json, generated from the REAL implementation by
// tools/oracle/generate_workflow_store_fixtures.py). Covers the 15 frozen
// cases: round-trip, exact checkpoint bytes, updated_at stamping, frozen
// error message texts, list ordering/tmp invisibility, corrupt-run
// skipping, cache-index gates, newest-first + incremental indexing,
// find_reusable_node hit/miss/revalidation, lineage, reproduction
// descriptions, default_store_root. Negative self-checks tamper frozen
// expectations in memory and assert the comparators catch them.

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/workflow_engine/store.hpp>
#include <pwb/workflow_spec/model.hpp>

using pwb::domain::Json;
namespace we = pwb::workflow_engine;
namespace ws = pwb::workflow_spec;

namespace {

int g_failures = 0;
int g_checks = 0;
int g_negative = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
    }
}

// A negative self-check: `detected` must be TRUE (the tampered expectation
// must trip the comparator). A missed tamper is a harness failure.
void negative_check(bool detected, const std::string& what) {
    ++g_negative;
    if (!detected) {
        ++g_failures;
        std::fprintf(stderr, "FAIL negative self-check missed: %s\n",
                     what.c_str());
    }
}

// ------------------------------------------------------------- helpers --

std::string read_file(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    std::ostringstream buffer;
    buffer << in.rdbuf();
    return buffer.str();
}

void write_file(const std::filesystem::path& path, const std::string& text) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out << text;
}

std::filesystem::path make_root() {
    static std::vector<std::filesystem::path> roots;
    static const bool cleanup_registered =
        std::atexit([] {
            for (const std::filesystem::path& root : roots) {
                std::error_code ec;
                std::filesystem::remove_all(root, ec);
            }
        }) == 0;
    (void)cleanup_registered;
    std::string tmpl = "/tmp/pwb-store-test-XXXXXX";
    if (char* dir = ::mkdtemp(tmpl.data())) {
        const std::filesystem::path root(dir);
        roots.push_back(root);
        return root;
    }
    std::fprintf(stderr, "FAIL cannot create temp store root\n");
    std::exit(2);
}

std::string replace_all(std::string text, const std::string& needle,
                        const std::string& with) {
    if (needle.empty()) return text;
    std::size_t pos = 0;
    while ((pos = text.find(needle, pos)) != std::string::npos) {
        text.replace(pos, needle.size(), with);
        pos += with.size();
    }
    return text;
}

// Settable clock: the knob stands in for Python's patched time.time, and
// one store keeps ONE index across all saves (Python's store does).
struct ClockKnob {
    double value = 0.0;
};

we::WorkflowRunStore::Clock knob_clock(std::shared_ptr<ClockKnob> knob) {
    return [knob] { return knob->value; };
}

we::WorkflowRunStore::Clock fixed(double value) {
    return [value] { return value; };
}

// Recursive ordered key-sequence walk: pins the Python dict KEY ORDER the
// ordered_json parse of the fixture preserves.
void collect_key_orders(const Json& value,
                        std::vector<std::vector<std::string>>& out) {
    if (value.is_object()) {
        std::vector<std::string> keys;
        for (const auto& [key, item] : value.items()) {
            keys.push_back(key);
        }
        out.push_back(std::move(keys));
        for (const auto& [key, item] : value.items()) {
            collect_key_orders(item, out);
        }
    } else if (value.is_array()) {
        for (const auto& item : value) {
            collect_key_orders(item, out);
        }
    }
}

bool key_orders_equal(const Json& left, const Json& right) {
    std::vector<std::vector<std::string>> a;
    std::vector<std::vector<std::string>> b;
    collect_key_orders(left, a);
    collect_key_orders(right, b);
    return a == b;
}

// Value-wise oracle comparison (the domain json_semantic_diff flags
// nlohmann number_unsigned, produced by parsing the fixture's positive
// ints, against number_integer, produced by the C++ int fields — both are
// Python ints). Signed/unsigned unify, floats compare exactly, int vs
// float stays a type difference (Python 1 vs 1.0), null/missing never
// coerce.
struct ValueDiff {
    bool equal = true;
    std::string path;
    std::string reason;
};

ValueDiff value_diff(const Json& left, const Json& right,
                     const std::string& path) {
    if (left.is_object() && right.is_object()) {
        for (const auto& [key, item] : left.items()) {
            if (!right.contains(key)) {
                return {false, path + "." + key, "key missing on right"};
            }
            const ValueDiff child =
                value_diff(item, right.at(key), path + "." + key);
            if (!child.equal) return child;
        }
        for (const auto& [key, item] : right.items()) {
            if (!left.contains(key)) {
                return {false, path + "." + key, "key missing on left"};
            }
        }
        return {};
    }
    if (left.is_array() && right.is_array()) {
        if (left.size() != right.size()) {
            return {false, path, "array length differs"};
        }
        for (std::size_t i = 0; i < left.size(); ++i) {
            const ValueDiff child = value_diff(
                left[i], right[i], path + "[" + std::to_string(i) + "]");
            if (!child.equal) return child;
        }
        return {};
    }
    // is_number_integer() covers signed AND unsigned (both Python ints).
    if (left.is_number_integer() && right.is_number_integer()) {
        if (left.get<long long>() == right.get<long long>()) return {};
        return {false, path, "int value differs"};
    }
    if (left.is_number_float() && right.is_number_float()) {
        if (left.get<double>() == right.get<double>()) return {};
        return {false, path, "float value differs"};
    }
    if (left.type() == right.type() && left == right) return {};
    return {false, path, "type differs"};
}

bool values_equal(const Json& left, const Json& right) {
    return value_diff(left, right, "$").equal;
}

void check_json(const Json& frozen, const Json& got, const std::string& label) {
    const ValueDiff diff = value_diff(frozen, got, "$");
    check(diff.equal,
          label + ": values" +
              (diff.equal ? "" : " — " + diff.path + ": " + diff.reason));
    check(key_orders_equal(frozen, got), label + ": key order");
}

bool strings_equal(const Json& frozen_array,
                   const std::vector<std::string>& got) {
    if (!frozen_array.is_array() || frozen_array.size() != got.size()) {
        return false;
    }
    for (std::size_t i = 0; i < got.size(); ++i) {
        if (!frozen_array[i].is_string() ||
            frozen_array[i].get<std::string>() != got[i]) {
            return false;
        }
    }
    return true;
}

Json pairs_to_json(
    const std::vector<std::pair<std::string, std::string>>& pairs) {
    Json out = Json::array();
    for (const auto& [run_id, node_id] : pairs) {
        out.push_back(Json::array({run_id, node_id}));
    }
    return out;
}

std::string at_string(const Json& value, std::size_t index) {
    return value.at(index).get<std::string>();
}

// ------------------------------------------------------------- catalog --

struct TableCatalog : we::CatalogLike {
    std::map<std::string, std::optional<we::VersionRefLike>> resolved;
    bool has_verify = false;
    std::map<std::string, std::string> integrity_status;  // default "verified"

    std::optional<we::VersionRefLike> resolve_version(
        const std::string& id) override {
        const auto it = resolved.find(id);
        if (it == resolved.end()) {
            throw std::runtime_error("unknown version '" + id + "'");
        }
        return it->second;
    }

    std::optional<std::string> verify_integrity(const std::string& id) override {
        if (!has_verify) return std::nullopt;  // Python: no attribute
        const auto it = integrity_status.find(id);
        return it == integrity_status.end() ? std::string("verified")
                                            : it->second;
    }
};

// ---------------------------------------------------------------- runs --

constexpr const char* kRichRunId = "aaaabbbbccccdddd";

ws::WorkflowRun make_rich_run(const ws::WorkflowSpec& spec) {
    ws::WorkflowRun run = ws::create_run(
        spec, Json{{"horizon", "H2"}, {"grid_n", 16}}, kRichRunId, 1000.0);
    run.project_name = "Demo Project";
    run.project_path = "/opt/fake/demo.paleo.json";
    run.state = ws::RunState::completed;

    ws::NodeRun* ex = run.find_node_run("extract");
    ex->state = ws::NodeState::succeeded;
    ex->attempt = 1;
    ex->action_status = "ok";
    ex->cache_identity = "ident-rich-extract";
    ex->input_version_ids = {};
    ex->output_version_ids = {"ver-extract-0001"};
    Json nested_k = Json::array({1, 2.5, std::string("\xc3\xbc")});
    ex->parameters = Json{{"factor_name", "gr"},
                          {"target_horizon", "H2"},
                          {"nested", Json{{"k", std::move(nested_k)}}}};
    ex->outputs = Json{{"point_count", 3}};
    ex->receipt = Json{
        {"provider_id", "prov://native/extract"},
        {"provider_version", "1.2.3"},
        {"action_version", "4.5.6"},
        {"cache_identity", "ident-receipt-extract"},
        {"environment",
         Json{{"python", "3.11.9"}, {"platform", "linux"}, {"build", "par0"}}},
    };
    ex->started_at = Json(1000.5);
    ex->finished_at = Json(1001.25);

    ws::NodeRun* it = run.find_node_run("interp");
    it->state = ws::NodeState::succeeded;
    it->attempt = 2;
    it->from_cache = true;
    it->cache_identity = "ident-rich-interp";
    it->input_version_ids = {"ver-extract-0001"};
    it->output_version_ids = {"ver-interp-0002"};
    it->parameters = Json{{"samples", Json::array()}, {"grid_n", 16}};
    it->outputs = Json{{"grid_z", Json::array({Json::array({1.0, 2.0})})}};
    // "report" stays PENDING (create_run seeded it).
    return run;
}

ws::WorkflowRun mini_run(const ws::WorkflowSpec& spec,
                         const std::string& run_id, double now = 1000.0) {
    return ws::create_run(spec, Json::object(), run_id, now);
}

ws::WorkflowRun succeed_solo(ws::WorkflowRun run,
                             const std::string& identity,
                             std::vector<std::string> outputs) {
    run.state = ws::RunState::completed;
    ws::NodeRun* solo = run.find_node_run("solo");
    solo->state = ws::NodeState::succeeded;
    solo->attempt = 1;
    solo->cache_identity = identity;
    solo->output_version_ids = std::move(outputs);
    return run;
}

// save() stamps updated_at through a mutable reference; this helper keeps
// the build-and-save call sites compact.
std::filesystem::path save_run(we::WorkflowRunStore& store,
                               ws::WorkflowRun run) {
    return store.save(run);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr,
                     "usage: store_test <workflow_store_oracle.json>\n");
        return 2;
    }
    Json fixture;
    try {
        fixture = Json::parse(read_file(argv[1]));
    } catch (const std::exception& exc) {
        std::fprintf(stderr, "FAIL cannot parse fixture: %s\n", exc.what());
        return 2;
    }

    const ws::WorkflowSpec spec =
        ws::WorkflowSpec::from_dict(fixture.at("spec"));
    const ws::WorkflowSpec mini =
        ws::WorkflowSpec::from_dict(fixture.at("mini_spec"));
    check(spec.spec_hash() == fixture.at("spec_hash").get<std::string>(),
          "spec_hash parity");
    check(mini.spec_hash() == fixture.at("mini_spec_hash").get<std::string>(),
          "mini spec_hash parity");

    // ---------------------------------------------- 1. roundtrip equality --
    {
        const Json& frozen = fixture.at("case01_roundtrip");
        we::WorkflowRunStore store(make_root(), fixed(2000.0));
        ws::WorkflowRun run = make_rich_run(spec);
        store.save(run);
        const ws::WorkflowRun loaded = store.load(kRichRunId);
        check_json(frozen.at("saved_to_dict"), run.to_dict(),
                   "c01 saved to_dict");
        check_json(frozen.at("loaded_to_dict"), loaded.to_dict(),
                   "c01 loaded to_dict");
        check(ws::canonical_hash(run.to_dict()) ==
                  frozen.at("saved_hash").get<std::string>(),
              "c01 saved canonical_hash");
        check(ws::canonical_hash(loaded.to_dict()) ==
                  frozen.at("loaded_hash").get<std::string>(),
              "c01 loaded canonical_hash");
    }

    // ------------------------------------------- 2. exact checkpoint bytes --
    {
        const Json& frozen = fixture.at("case02_file_format");
        we::WorkflowRunStore store(make_root(), fixed(2000.0));
        ws::WorkflowRun run = make_rich_run(spec);
        const std::filesystem::path path = store.save(run);
        const std::string text = read_file(path);
        const std::string want = frozen.at("text").get<std::string>();
        check(text == want, "c02 exact file bytes (indent=1, no newline)");
        if (text != want) {
            std::size_t at = 0;
            while (at < text.size() && at < want.size() &&
                   text[at] == want[at]) {
                ++at;
            }
            std::fprintf(stderr, "  first byte diff at %zu\n", at);
        }
        const Json payload = Json::parse(text);
        std::vector<std::string> top_keys;
        for (const auto& [key, value] : payload.items()) top_keys.push_back(key);
        check(!top_keys.empty() && top_keys.front() == "store_version",
              "c02 store_version is FIRST key");
        check(strings_equal(frozen.at("top_keys"), top_keys),
              "c02 top key order");
        std::vector<std::string> workflow_keys;
        for (const auto& [key, value] : payload.at("workflow").items()) {
            workflow_keys.push_back(key);
        }
        check(strings_equal(frozen.at("workflow_keys"), workflow_keys),
              "c02 workflow key order");
        std::vector<std::string> node_run_keys;
        for (const auto& [key, value] : payload.at("node_runs")[0].items()) {
            node_run_keys.push_back(key);
        }
        check(strings_equal(frozen.at("node_run_keys"), node_run_keys),
              "c02 node_run key order");
        check(payload.at("store_version") == frozen.at("store_version"),
              "c02 store_version value");
    }

    // -------------------------------------------- 3. updated_at stamping --
    {
        const Json& frozen = fixture.at("case03_updated_at");
        we::WorkflowRunStore store(make_root(), fixed(2000.5));
        ws::WorkflowRun run = make_rich_run(spec);  // created_at = 1000.0
        check(values_equal(run.created_at, frozen.at("created_at")),
              "c03 injected created_at");
        store.save(run);
        check(values_equal(run.updated_at, frozen.at("updated_at")),
              "c03 updated_at stamped by clock");
        check(run.updated_at.get<double>() >= run.created_at.get<double>(),
              "c03 updated_at >= created_at");
        check(values_equal(store.load(kRichRunId).updated_at,
                           frozen.at("stamped_in_file")),
              "c03 updated_at persisted in file");
    }

    // ---------------------------------------------- 4. load missing run --
    {
        const Json& frozen = fixture.at("case04_missing");
        we::WorkflowRunStore store(make_root());
        std::string message;
        bool threw = false;
        try {
            (void)store.load(frozen.at("run_id").get<std::string>());
        } catch (const we::RunNotFound& exc) {
            threw = true;
            message = exc.what();
        }
        check(threw, "c04 RunNotFound thrown");
        check(message ==
                  replace_all(frozen.at("message").get<std::string>(),
                              "{ROOT}", store.root().string()),
              "c04 frozen message (root substituted)");
    }

    // ---------------------------------------------- 5. load corrupt file --
    {
        const Json& frozen = fixture.at("case05_corrupt");
        const std::filesystem::path root = make_root();
        we::WorkflowRunStore store(root);
        write_file(root / "run-bad1.json", frozen.at("raw").get<std::string>());
        std::string message;
        bool threw = false;
        try {
            (void)store.load(frozen.at("run_id").get<std::string>());
        } catch (const we::CorruptCheckpoint& exc) {
            threw = true;
            message = exc.what();
        }
        check(threw, "c05 CorruptCheckpoint thrown");
        // Only the prefix is frozen — parser detail wording is
        // implementation-specific (CPython vs nlohmann).
        check(message.rfind(frozen.at("message_prefix").get<std::string>(), 0) ==
                  0,
              "c05 frozen message prefix");
    }

    // ------------------------------------- 6. list ids + tmp invisibility --
    {
        const Json& frozen = fixture.at("case06_list_ids");
        const std::filesystem::path root = make_root();
        auto knob = std::make_shared<ClockKnob>();
        we::WorkflowRunStore store(root, knob_clock(knob));
        for (int i = 0; i < 3; ++i) {
            const char* ids[] = {"b", "a", "c"};
            knob->value = 1500.0 + i;
            save_run(store, mini_run(mini, ids[i]));
        }
        write_file(root / ".tmp-run-junk.json", "{}");
        check(strings_equal(frozen.at("ids"), store.list_run_ids()),
              "c06 sorted ids, stray .tmp invisible");
    }

    // ------------------------------------------ 7. list_runs skips corrupt --
    {
        const Json& frozen = fixture.at("case07_list_runs");
        const std::filesystem::path root = make_root();
        auto knob = std::make_shared<ClockKnob>();
        knob->value = 1600.0;
        we::WorkflowRunStore store(root, knob_clock(knob));
        save_run(store, mini_run(mini, "good"));
        write_file(root / "run-zcorrupt.json", "{corrupted");
        std::vector<std::string> warnings;
        store.set_log_sink([&warnings](const std::string& line) {
            warnings.push_back(line);
        });
        std::vector<std::string> ids;
        for (const ws::WorkflowRun& run : store.list_runs()) {
            ids.push_back(run.run_id);
        }
        check(strings_equal(frozen.at("ids"), ids), "c07 readable ids only");
        check(strings_equal(frozen.at("warnings"), warnings),
              "c07 frozen skip warning");
    }

    // ------------------------------------------------- 8. index gates --
    {
        const Json& frozen = fixture.at("case08_index_gates");
        auto knob = std::make_shared<ClockKnob>();
        we::WorkflowRunStore store(make_root(), knob_clock(knob));
        // RUNNING run with a succeeded node: not reusable evidence yet.
        knob->value = 1700.0;
        ws::WorkflowRun running_run =
            succeed_solo(mini_run(mini, "gaterunning"), "ident-gates", {"v-x"});
        running_run.state = ws::RunState::running;
        store.save(running_run);
        // gatecached: node reused from cache -> never indexed.
        knob->value = 1710.0;
        ws::WorkflowRun cached_run =
            succeed_solo(mini_run(mini, "gatecached"), "ident-gates", {"v-x"});
        cached_run.find_node_run("solo")->from_cache = true;
        store.save(cached_run);
        // gateempty: succeeded but no recorded outputs.
        knob->value = 1711.0;
        save_run(store,
                 succeed_solo(mini_run(mini, "gateempty"), "ident-gates", {}));
        // goodrun: the only indexable evidence.
        knob->value = 1712.0;
        save_run(store, succeed_solo(mini_run(mini, "goodrun"), "ident-gates",
                                      {"v-good-1"}));
        const int count = store.rebuild_cache_index();
        check(count == frozen.at("rebuild_count").get<int>(),
              "c08 rebuild count (gates filter)");
        check(values_equal(
                  pairs_to_json(store.candidates_for_identity(
                      frozen.at("identity").get<std::string>())),
                  frozen.at("candidates")),
              "c08 candidates for gated identity");
        check(values_equal(
                  pairs_to_json(store.candidates_for_identity("ident-none")),
                  frozen.at("empty_identity_candidates")),
              "c08 empty identity -> no candidates");
    }

    // ---------------------------------------- 9. newest-first + incremental --
    {
        const Json& frozen = fixture.at("case09_many");
        auto knob = std::make_shared<ClockKnob>();
        we::WorkflowRunStore store(make_root(), knob_clock(knob));
        for (int i = 0; i < 30; ++i) {
            char run_id[8];
            std::snprintf(run_id, sizeof(run_id), "r%02d", i);
            knob->value = 3000.0 + i;
            save_run(store, succeed_solo(mini_run(mini, run_id), "ident-many",
                                          {std::string("ver-") + run_id}));
        }
        const auto initial =
            store.candidates_for_identity(frozen.at("identity").get<std::string>());
        check(static_cast<int>(initial.size()) ==
                      frozen.at("initial_len").get<int>() &&
                  frozen.at("initial_len") == frozen.at("count"),
              "c09 initial candidate count");
        check(!initial.empty() &&
                  initial.front().first == at_string(frozen.at("initial_head"), 0) &&
                  initial.front().second == at_string(frozen.at("initial_head"), 1),
              "c09 initial head is newest (r29)");
        // Incremental index update after the (already built) index.
        knob->value = 4000.0;
        save_run(store,
                 succeed_solo(mini_run(mini, "r99"), "ident-many", {"ver-r99"}));
        const auto after =
            store.candidates_for_identity(frozen.at("identity").get<std::string>());
        check(static_cast<int>(after.size()) ==
                  frozen.at("after_r99_len").get<int>(),
              "c09 candidate count after r99");
        check(!after.empty() &&
                  after.front().first == at_string(frozen.at("after_r99_head"), 0) &&
                  after.front().second == at_string(frozen.at("after_r99_head"), 1),
              "c09 post-build save lands newest");
        const std::optional<ws::NodeRun> reusable = we::find_reusable_node(
            store, frozen.at("identity").get<std::string>());
        check(reusable.has_value(), "c09 reusable node found");
        if (reusable.has_value()) {
            check_json(frozen.at("reusable_node"), reusable->to_dict(),
                       "c09 reusable node (newest good)");
            // The reused run is the head of the newest-first walk; its node
            // carries that run's recorded outputs.
            check(reusable->output_version_ids.size() == 1 &&
                      reusable->output_version_ids[0] ==
                          "ver-" + frozen.at("reusable_run").get<std::string>(),
                  "c09 reusable run is the frozen newest run");
        }
    }

    // --------------------------------------------------- 10. pure miss --
    {
        const Json& frozen = fixture.at("case10_miss");
        auto knob = std::make_shared<ClockKnob>();
        knob->value = 1800.0;
        we::WorkflowRunStore store(make_root(), knob_clock(knob));
        save_run(store,
                 succeed_solo(mini_run(mini, "onlyrun"), "ident-only", {"v-o"}));
        check(!we::find_reusable_node(
                   store, frozen.at("identity").get<std::string>())
                   .has_value(),
              "c10 unknown identity -> no reuse");
    }

    // ------------------------------------------ 11. revalidation paths --
    {
        const Json& frozen = fixture.at("case11_revalidation");
        auto knob = std::make_shared<ClockKnob>();
        we::WorkflowRunStore store(make_root(), knob_clock(knob));
        knob->value = 2100.0;
        save_run(store,
                 succeed_solo(mini_run(mini, "fbnew"), "ident-fb", {"v-new"}));
        knob->value = 2000.0;
        save_run(store,
                 succeed_solo(mini_run(mini, "fbold"), "ident-fb", {"v-old"}));
        TableCatalog catalog_fb;
        catalog_fb.resolved["v-new"] = std::nullopt;  // unresolvable
        catalog_fb.resolved["v-old"] = we::VersionRefLike{false};
        catalog_fb.has_verify = true;
        // fbnew walks first (unresolvable); the frozen fallback run is the
        // second candidate in the newest-first walk.
        const auto fb_candidates =
            store.candidates_for_identity(frozen.at("identity").get<std::string>());
        check(fb_candidates.size() == 2 &&
                  fb_candidates[0].first == "fbnew" &&
                  fb_candidates[1].first ==
                      frozen.at("fallback_run").get<std::string>(),
              "c11 frozen fallback run is second-newest candidate");
        const std::optional<ws::NodeRun> fb = we::find_reusable_node(
            store, frozen.at("identity").get<std::string>(), &catalog_fb);
        check(fb.has_value(), "c11 fallback to older resolvable candidate");
        if (fb.has_value()) {
            check_json(frozen.at("fallback_node"), fb->to_dict(),
                       "c11 fallback node");
            check(fb->output_version_ids.size() == 1 &&
                      fb->output_version_ids[0] == "v-old",
                  "c11 fallback came from fbold");
        }
        // from_cache-only identity: never indexed -> no candidates at all.
        knob->value = 2200.0;
        ws::WorkflowRun fc =
            succeed_solo(mini_run(mini, "fconly"), "ident-fc", {"v-x"});
        fc.find_node_run("solo")->from_cache = true;
        store.save(fc);
        check(!we::find_reusable_node(store, "ident-fc").has_value(),
              "c11 from_cache-only identity -> no reuse");
        // trashed output: resolvable but trashed.
        knob->value = 2300.0;
        save_run(store, succeed_solo(mini_run(mini, "trashrun"), "ident-trash",
                                      {"v-trash"}));
        TableCatalog catalog_trash;
        catalog_trash.resolved["v-trash"] = we::VersionRefLike{true};
        check(!we::find_reusable_node(store, "ident-trash", &catalog_trash)
                   .has_value(),
              "c11 trashed output -> no reuse");
        // integrity below VERIFIED blocks reuse...
        knob->value = 2400.0;
        save_run(store, succeed_solo(mini_run(mini, "intfailrun"),
                                      "ident-intfail", {"v-int"}));
        TableCatalog catalog_intfail;
        catalog_intfail.resolved["v-int"] = we::VersionRefLike{false};
        catalog_intfail.has_verify = true;
        catalog_intfail.integrity_status["v-int"] = "FAILED";
        check(!we::find_reusable_node(store, "ident-intfail", &catalog_intfail)
                   .has_value(),
              "c11 integrity FAILED -> no reuse");
        // ...but verify_integrity=false skips the check entirely.
        const std::optional<ws::NodeRun> off = we::find_reusable_node(
            store, "ident-intfail", &catalog_intfail, /*verify_integrity=*/false);
        check(off.has_value() == frozen.at("verify_off_found").get<bool>(),
              "c11 verify_integrity=false reuses");
        if (off.has_value()) {
            check_json(frozen.at("verify_off_node"), off->to_dict(),
                       "c11 verify-off node");
        }
        // resolve_version raising -> unresolvable.
        TableCatalog catalog_raise;  // empty table: every lookup throws
        check(!we::find_reusable_node(
                   store, frozen.at("identity").get<std::string>(), &catalog_raise)
                   .has_value(),
              "c11 resolve_version raising -> no reuse");
        // newest candidate unreadable on disk (corrupted after the index
        // recorded it): cgood saved first, cbad last so it walks first.
        knob->value = 2450.0;
        save_run(store, succeed_solo(mini_run(mini, "cgood"), "ident-corrupt",
                                      {"v-c2"}));
        knob->value = 2500.0;
        save_run(store, succeed_solo(mini_run(mini, "cbad"), "ident-corrupt",
                                      {"v-c1"}));
        write_file(store.root() / "run-cbad.json", "{corrupted");
        std::vector<std::string> warnings;
        store.set_log_sink([&warnings](const std::string& line) {
            warnings.push_back(line);
        });
        const std::optional<ws::NodeRun> corrupt_fb = we::find_reusable_node(
            store, frozen.at("corrupt_identity").get<std::string>());
        check(corrupt_fb.has_value(), "c11 corrupt newest -> older wins");
        if (corrupt_fb.has_value()) {
            check_json(frozen.at("corrupt_fallback_node"), corrupt_fb->to_dict(),
                       "c11 corrupt fallback node");
            check(corrupt_fb->output_version_ids.size() == 1 &&
                      corrupt_fb->output_version_ids[0] == "v-c2" &&
                      "cgood" ==
                          frozen.at("corrupt_fallback_run").get<std::string>(),
                  "c11 frozen corrupt fallback run");
        }
        check(strings_equal(frozen.at("corrupt_candidate_warnings"), warnings),
              "c11 frozen unreadable-candidate warning");
    }

    // ---------------------------------------------------- 12. lineage --
    {
        const Json& frozen = fixture.at("case12_lineage");
        auto knob = std::make_shared<ClockKnob>();
        we::WorkflowRunStore store(make_root(), knob_clock(knob));
        ws::WorkflowRun orig = mini_run(mini, "orig", 1000.0);
        ws::WorkflowRun child = mini_run(mini, "child", 1001.0);
        child.parent_run_id = "orig";
        ws::WorkflowRun grand = mini_run(mini, "grandchild", 1002.0);
        grand.parent_run_id = "child";
        ws::WorkflowRun orphan = mini_run(mini, "orphan", 1003.0);
        orphan.parent_run_id = "vanished";
        ws::WorkflowRun acyc = mini_run(mini, "acyc", 1004.0);
        acyc.parent_run_id = "bcyc";
        ws::WorkflowRun bcyc = mini_run(mini, "bcyc", 1005.0);
        bcyc.parent_run_id = "acyc";
        ws::WorkflowRun chain[] = {orig, child, grand, orphan, acyc, bcyc};
        for (std::size_t i = 0; i < 6; ++i) {
            knob->value = 2600.0 + static_cast<double>(i);
            store.save(chain[i]);
        }
        check(strings_equal(frozen.at("grandchild"),
                            we::run_lineage(store, "grandchild")),
              "c12 chain oldest first");
        check(strings_equal(frozen.at("orphan"),
                            we::run_lineage(store, "orphan")),
              "c12 orphan parent stops walk");
        check(strings_equal(frozen.at("cycle_from_acyc"),
                            we::run_lineage(store, "acyc")),
              "c12 cycle never loops");
        const std::optional<std::string> parent =
            store.load("grandchild").parent_run_id;
        check(parent.has_value() &&
                  *parent ==
                      frozen.at("parent_after_roundtrip").get<std::string>(),
              "c12 parent_run_id survives round-trip");
    }

    // ---------------------------------------- 13. describe_reproduction --
    {
        const Json& frozen = fixture.at("case13_reproduction");
        ws::WorkflowRun run = make_rich_run(spec);
        const Json describe_a = we::describe_reproduction(run);
        const Json describe_b = we::describe_reproduction(run);
        check_json(describe_a, describe_b, "c13 deterministic twice");
        check_json(frozen.at("describe"), describe_a, "c13 describe");
        check(ws::canonical_hash(describe_a) ==
                  frozen.at("hash").get<std::string>(),
              "c13 describe canonical_hash");
        we::WorkflowRunStore store(make_root(), fixed(2000.0));
        store.save(run);
        const Json describe_post =
            we::describe_reproduction(store.load(kRichRunId));
        check_json(frozen.at("describe_after_roundtrip"), describe_post,
                   "c13 describe after save->load");
        check(ws::canonical_hash(describe_post) ==
                  frozen.at("hash_after_roundtrip").get<std::string>(),
              "c13 describe round-trip canonical_hash");
    }

    // --------------------------------------- 14. describe on empty run --
    {
        const Json& frozen = fixture.at("case14_empty");
        ws::WorkflowRun empty = mini_run(mini, "ffffffffffffffff", 1000.0);
        const Json describe_empty = we::describe_reproduction(empty);
        check_json(frozen.at("describe"), describe_empty,
                   "c14 all-PENDING describe");
        check(ws::canonical_hash(describe_empty) ==
                  frozen.at("hash").get<std::string>(),
              "c14 describe canonical_hash");
        // missing-node_run branches (parameters {} / from_cache null / ...)
        for (auto it = empty.node_runs.begin(); it != empty.node_runs.end();) {
            if (it->first == "solo") {
                it = empty.node_runs.erase(it);
            } else {
                ++it;
            }
        }
        check_json(frozen.at("describe_missing_node"),
                   we::describe_reproduction(empty),
                   "c14 missing node_run describe");
    }

    // ------------------------------------------- 15. default_store_root --
    {
        const Json& frozen = fixture.at("case15_default_root");
        check(we::default_store_root(
                  frozen.at("project_arg").get<std::string>())
                  .string() == frozen.at("with_project").get<std::string>(),
              "c15 project-derived artifacts root");
        const std::string no_project =
            replace_all(we::default_store_root().string(),
                        std::filesystem::temp_directory_path().string(),
                        "{TMP}");
        check(no_project == frozen.at("no_project").get<std::string>(),
              "c15 session temp root");
    }

    // ------------------------------------------------ negative self-checks --
    // Tamper frozen expectations in memory: every comparator below MUST
    // report a mismatch (proves the frozen comparisons have teeth).
    {
        // (1) tampered RunNotFound message text.
        std::string tampered_message =
            fixture.at("case04_missing").at("message").get<std::string>();
        tampered_message.replace(tampered_message.find("ghost"), 5, "gh0st");
        const std::filesystem::path root4 = make_root();
        we::WorkflowRunStore store4(root4);
        std::string message4;
        try {
            (void)store4.load("ghost");
        } catch (const we::RunNotFound& exc) {
            message4 = exc.what();
        }
        negative_check(
            replace_all(tampered_message, "{ROOT}", root4.string()) != message4,
            "tampered c04 message must differ");

        // (2) tampered checkpoint bytes.
        std::string tampered_text =
            fixture.at("case02_file_format").at("text").get<std::string>();
        tampered_text.replace(tampered_text.find("\"run_id\""), 8, "\"run_ld\"");
        we::WorkflowRunStore store5(make_root(), fixed(2000.0));
        ws::WorkflowRun run5 = make_rich_run(spec);
        negative_check(read_file(store5.save(run5)) != tampered_text,
                       "tampered c02 bytes must differ");

        // (3) tampered describe hash.
        std::string tampered_hash =
            fixture.at("case13_reproduction").at("hash").get<std::string>();
        tampered_hash[0] = tampered_hash[0] == '0' ? '1' : '0';
        negative_check(
            ws::canonical_hash(we::describe_reproduction(run5)) !=
                tampered_hash,
            "tampered c13 hash must differ");

        // (4) tampered key order (values untouched, so only the order
        // comparator can catch it).
        Json reordered = Json::object();
        std::vector<std::string> keys;
        for (const auto& [key, value] :
             fixture.at("case13_reproduction").at("describe").items()) {
            keys.push_back(key);
        }
        std::swap(keys[0], keys[1]);
        for (const std::string& key : keys) {
            reordered[key] =
                fixture.at("case13_reproduction").at("describe").at(key);
        }
        negative_check(!key_orders_equal(
                           reordered, we::describe_reproduction(run5)),
                       "tampered c13 key order must be caught");
    }

    if (g_failures == 0) {
        std::printf("ALL %d CHECKS PASSED (+%d negative self-checks)\n",
                    g_checks, g_negative);
        return 0;
    }
    std::printf("FAIL: %d failure(s) of %d checks (+%d negative self-checks)\n",
                g_failures, g_checks, g_negative);
    return 1;
}
