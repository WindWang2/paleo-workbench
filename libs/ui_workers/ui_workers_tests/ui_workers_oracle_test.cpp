// ui_workers.oracle — replay of the frozen Python oracle fixture
// (tools/oracle/generate_ui_workers_fixtures.py ->
// fixtures/ui_workers_oracle.json) against the ported Qt-free worker
// cores. The fixture was produced by the REAL Python implementations —
// never hand-written expected values — so a mismatch is a real
// parity regression, not a test artifact.
//
// Non-finite numbers freeze as the tagged strings "nan"/"inf"/"-inf";
// grids are {"rows","cols","data"}; volumes {"n_i","n_x","n_s","data"}.
// Cases flagged expect_mismatch=true are the negative self-check: the
// harness MUST flag a drift — a match there means the harness is blind.

#include <pwb/domain/json.hpp>
#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/contour_draft.hpp>
#include <pwb/ui_workers/correlation_load.hpp>
#include <pwb/ui_workers/dtw_propagation.hpp>
#include <pwb/ui_workers/factor_prepare.hpp>
#include <pwb/ui_workers/geological_modeling.hpp>
#include <pwb/ui_workers/geomodel_primitives.hpp>
#include <pwb/ui_workers/integrity.hpp>
#include <pwb/ui_workers/stratal.hpp>
#include <pwb/ui_workers/synthetic_points.hpp>
#include <pwb/ui_workers/viz_resolve.hpp>
#include <pwb/ui_workers/well_log_load.hpp>
#include <pwb/ui_workers/worker_common.hpp>

#include <algorithm>
#include <any>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>
// PWB-V14-DATA-LINEAGE: setenv/unsetenv are POSIX-only; the MSVC CRT
// equivalent (process environment) with the same semantics for tests.
#if defined(_WIN32)
#include <stdlib.h>
inline int pwb_env_set(const char* name, const char* value, int overwrite) {
    (void)overwrite;
    return _putenv_s(name, value);
}
inline int pwb_env_unset(const char* name) { return _putenv_s(name, ""); }
#else
#include <stdlib.h>
inline int pwb_env_set(const char* name, const char* value, int overwrite) {
    return ::setenv(name, value, overwrite);
}
inline int pwb_env_unset(const char* name) { return ::unsetenv(name); }
#endif


namespace {

using pwb::domain::Json;
namespace uw = pwb::ui_workers;
namespace job = pwb::job;

int g_failures = 0;
int g_checks = 0;
int g_selfcheck = 0;  // expect_mismatch cases that correctly flagged

std::string g_case_id;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL [%s] %s\n", g_case_id.c_str(),
                     what.c_str());
        ++g_failures;
    }
}

// Same int/float normalization as the geomodel oracle: dump/parse
// roundtrip unifies signed-vs-unsigned (int-vs-float stays real).
Json norm(const Json& v) { return Json::parse(v.dump()); }

bool sem_eq(const Json& a, const Json& b, std::string* diff_path = nullptr) {
    const auto diff = pwb::domain::json_semantic_diff(norm(a), norm(b));
    if (diff_path != nullptr && !diff.equal) {
        *diff_path = diff.path + " (" + diff.reason + ")";
    }
    return diff.equal;
}

// ---------------------------------------------------------------------------
// Frozen-number decoding ("nan"/"inf"/"-inf" tagged strings).
// ---------------------------------------------------------------------------

double num_of(const Json& v) {
    if (v.is_string()) {
        const auto s = v.get<std::string>();
        if (s == "nan") return std::numeric_limits<double>::quiet_NaN();
        if (s == "inf") return std::numeric_limits<double>::infinity();
        if (s == "-inf") return -std::numeric_limits<double>::infinity();
        return std::numeric_limits<double>::quiet_NaN();
    }
    return v.get<double>();
}

bool num_eq_json(const Json& expected, double actual,
                 double rel_tol = 1e-9) {
    if (expected.is_string()) {
        const auto s = expected.get<std::string>();
        if (s == "nan") return std::isnan(actual);
        if (s == "inf") return actual == std::numeric_limits<double>::infinity();
        if (s == "-inf")
            return actual == -std::numeric_limits<double>::infinity();
        return false;
    }
    const double e = expected.get<double>();
    if (std::isnan(e)) return std::isnan(actual);
    return std::fabs(actual - e) <=
           rel_tol * std::max(1.0, std::fabs(e));
}

bool nums_eq(const Json& expected, const std::vector<double>& actual,
             const std::string& what, double rel_tol = 1e-9) {
    if (!expected.is_array() || expected.size() != actual.size()) {
        check(false, what + ": size mismatch");
        return false;
    }
    for (std::size_t i = 0; i < actual.size(); ++i) {
        if (!num_eq_json(expected[i], actual[i], rel_tol)) {
            check(false, what + ": element " + std::to_string(i) +
                             " expected " + expected[i].dump() + " got " +
                             std::to_string(actual[i]));
            return false;
        }
    }
    return true;
}

uw::Grid2D grid_of(const Json& j) {
    uw::Grid2D g;
    g.rows = j.at("rows").get<std::size_t>();
    g.cols = j.at("cols").get<std::size_t>();
    g.data.reserve(g.rows * g.cols);
    for (const auto& v : j.at("data")) g.data.push_back(num_of(v));
    return g;
}

uw::Volume3D volume_of(const Json& j) {
    uw::Volume3D v;
    v.n_i = j.at("n_i").get<std::size_t>();
    v.n_x = j.at("n_x").get<std::size_t>();
    v.n_s = j.at("n_s").get<std::size_t>();
    v.data.reserve(v.n_i * v.n_x * v.n_s);
    for (const auto& x : j.at("data")) {
        v.data.push_back(static_cast<float>(num_of(x)));
    }
    return v;
}

bool grid_eq(const Json& expected, const uw::Grid2D& actual,
             const std::string& what, double rel_tol = 1e-9) {
    if (expected.at("rows").get<std::size_t>() != actual.rows ||
        expected.at("cols").get<std::size_t>() != actual.cols) {
        check(false, what + ": shape mismatch");
        return false;
    }
    return nums_eq(expected.at("data"), actual.data, what, rel_tol);
}

bool volume_eq(const Json& expected, const uw::Volume3D& actual,
               const std::string& what) {
    if (expected.at("n_i").get<std::size_t>() != actual.n_i ||
        expected.at("n_x").get<std::size_t>() != actual.n_x ||
        expected.at("n_s").get<std::size_t>() != actual.n_s) {
        check(false, what + ": shape mismatch");
        return false;
    }
    // float32 payloads: the frozen decimals are the exact f32 values —
    // compare through float, tight tolerance for trig-derived entries.
    if (expected.at("data").size() != actual.data.size()) {
        check(false, what + ": size mismatch");
        return false;
    }
    for (std::size_t i = 0; i < actual.data.size(); ++i) {
        const auto& e = expected.at("data")[i];
        if (e.is_string()) {
            if (num_eq_json(e, actual.data[i])) continue;
            check(false, what + ": element " + std::to_string(i));
            return false;
        }
        const float ef = e.get<float>();
        if (ef == actual.data[i]) continue;
        if (std::fabs(static_cast<double>(ef) -
                      static_cast<double>(actual.data[i])) <=
            1e-6 * std::max(1.0, std::fabs(static_cast<double>(ef)))) {
            continue;
        }
        check(false, what + ": element " + std::to_string(i) +
                         " expected " + e.dump() + " got " +
                         std::to_string(actual.data[i]));
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// JSON -> std::any (parameters/grid_metadata bags).
// ---------------------------------------------------------------------------

std::any any_from_json(const Json& v) {
    if (v.is_null()) return std::any{};
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number_integer() || v.is_number_unsigned()) {
        return v.get<std::int64_t>();
    }
    if (v.is_number_float()) return v.get<double>();
    if (v.is_string()) return v.get<std::string>();
    if (v.is_array()) {
        std::vector<std::any> out;
        out.reserve(v.size());
        for (const auto& item : v) out.push_back(any_from_json(item));
        return out;
    }
    if (v.is_object()) {
        std::map<std::string, std::any> out;
        for (const auto& [k, item] : v.items()) {
            out[k] = any_from_json(item);
        }
        return out;
    }
    return std::any{};
}

// std::any -> Json for wire-shape comparisons (line_features, drafts).
Json json_from_any(const std::any& v) {
    if (!v.has_value()) return nullptr;
    if (const auto* s = std::any_cast<std::string>(&v)) return *s;
    if (const auto* c = std::any_cast<const char*>(&v)) return *c;
    if (const auto* b = std::any_cast<bool>(&v)) return *b;
    if (const auto* d = std::any_cast<double>(&v)) return *d;
    if (const auto* f = std::any_cast<float>(&v)) {
        return static_cast<double>(*f);
    }
    if (const auto* i = std::any_cast<int>(&v)) return *i;
    if (const auto* i64 = std::any_cast<std::int64_t>(&v)) return *i64;
    if (const auto* u = std::any_cast<unsigned>(&v)) return *u;
    if (const auto* vec = std::any_cast<std::vector<std::any>>(&v)) {
        Json out = Json::array();
        for (const auto& item : *vec) out.push_back(json_from_any(item));
        return out;
    }
    if (const auto* vec =
            std::any_cast<std::vector<double>>(&v)) {
        Json out = Json::array();
        for (double item : *vec) out.push_back(item);
        return out;
    }
    if (const auto* m =
            std::any_cast<std::map<std::string, std::any>>(&v)) {
        Json out = Json::object();
        for (const auto& [k, item] : *m) out[k] = json_from_any(item);
        return out;
    }
    return "<unserializable>";
}

std::map<std::string, std::any> any_map_of(const Json& v) {
    std::map<std::string, std::any> out;
    if (v.is_object()) {
        for (const auto& [k, item] : v.items()) {
            out[k] = any_from_json(item);
        }
    }
    return out;
}

// ---------------------------------------------------------------------------
// Slice builders.
// ---------------------------------------------------------------------------

uw::FactorTaskSlice task_from_json(const Json& j) {
    uw::FactorTaskSlice t;
    t.id = j.value("id", std::string{});
    t.name = j.value("name", std::string{});
    t.status = j.value("status", std::string{});
    t.target_horizon = j.value("target_horizon", std::string{});
    t.factor_type = j.value("factor_type", std::string{});
    t.method = j.value("method", std::string{});
    t.source_kind = j.value("source_kind", std::string{});
    if (j.contains("seed") && !j.at("seed").is_null()) {
        t.seed = j.at("seed").get<int>();
    }
    if (j.contains("parameters")) {
        t.parameters = any_map_of(j.at("parameters"));
    }
    if (j.contains("grid_metadata")) {
        t.grid_metadata = any_map_of(j.at("grid_metadata"));
    }
    t.input_snapshot_hash = j.value("input_snapshot_hash", std::string{});
    t.grid_artifact_path = j.value("grid_artifact_path", std::string{});
    return t;
}

uw::ContourDraftSlice draft_from_scope_json(const Json& j) {
    uw::ContourDraftSlice d;
    // The Python _draft() defaults — the oracle freezes only the scope
    // fields; everything else reproduces the helper verbatim.
    d.id = j.value("id", std::string{});
    d.name = "d";
    d.target_horizon = j.value("target_horizon", std::string{});
    d.factor_type = j.value("factor_type", std::string{});
    if (j.contains("linked_factor_task_id") &&
        !j.at("linked_factor_task_id").is_null()) {
        d.linked_factor_task_id =
            j.at("linked_factor_task_id").get<std::string>();
    }
    d.levels = {1.0};
    d.source_grid_n = 4;
    d.source_backend = "idw";
    d.source_value_range = {0.0, 1.0};
    d.status = "draft";
    d.generator_version = uw::kContourDraftGeneratorVersion;
    return d;
}

Json draft_to_json(const uw::ContourDraftSlice& d) {
    Json j;
    j["id"] = d.id;
    j["name"] = d.name;
    j["target_horizon"] = d.target_horizon;
    j["factor_type"] = d.factor_type;
    j["linked_factor_task_id"] = d.linked_factor_task_id.empty()
                                     ? Json(nullptr)
                                     : Json(d.linked_factor_task_id);
    Json levels = Json::array();
    for (double l : d.levels) levels.push_back(l);
    j["levels"] = levels;
    Json segs = Json::array();
    for (const auto& s : d.segments) {
        Json sj;
        sj["id"] = s.id;
        sj["level"] = s.level;
        Json coords = Json::array();
        for (const auto& [x, y] : s.coordinates) {
            coords.push_back(Json::array({x, y}));
        }
        sj["coordinates"] = coords;
        sj["closed"] = s.closed;
        Json props = Json::object();
        for (const auto& [k, v] : s.properties) {
            props[k] = json_from_any(v);
        }
        sj["properties"] = props;
        segs.push_back(std::move(sj));
    }
    j["segments"] = segs;
    j["source_grid_n"] = d.source_grid_n;
    j["source_backend"] = d.source_backend;
    j["source_value_range"] =
        Json::array({d.source_value_range.first, d.source_value_range.second});
    j["status"] = d.status;
    j["generator_version"] = d.generator_version;
    j["updated_at"] = d.updated_at;
    j["linked_map_document_id"] = d.linked_map_document_id.empty()
                                      ? Json(nullptr)
                                      : Json(d.linked_map_document_id);
    return j;
}

Json progress_to_json(const uw::FactorPrepareProgress& p) {
    Json j;
    j["generation"] = p.generation;
    j["total_tasks"] = p.total_tasks;
    j["clean"] = p.clean;
    j["dirty"] = p.dirty;
    j["completed"] = p.completed;
    j["failed"] = p.failed;
    j["cancelled"] = p.cancelled;
    j["phase"] = p.phase;
    j["current_task_id"] = p.current_task_id ? Json(*p.current_task_id)
                                             : Json(nullptr);
    j["current_group"] = p.current_group ? Json(*p.current_group)
                                         : Json(nullptr);
    j["message"] = p.message;
    return j;
}

Json task_result_to_json(const uw::FactorPrepareTaskResult& r) {
    Json j;
    j["task_id"] = r.task_id;
    j["dirty_state"] = r.dirty_state;
    j["reused"] = r.reused;
    j["has_task"] = r.task.has_value();
    j["task_status"] =
        r.task ? Json(r.task->status) : Json(nullptr);
    j["task_last_error"] = nullptr;
    if (r.task) {
        if (auto le = uw::param_str(*r.task, "last_error")) {
            j["task_last_error"] = *le;
        }
    }
    j["scheduled_result_fingerprint"] =
        r.scheduled_result_fingerprint
            ? Json(*r.scheduled_result_fingerprint)
            : Json(nullptr);
    j["error"] = r.error ? Json(*r.error) : Json(nullptr);
    j["grid_present"] = r.grid.has_value();
    return j;
}

// ---------------------------------------------------------------------------
// Per-kind runners — one function per fixture kind.
// ---------------------------------------------------------------------------

void run_py_round(const Json& c) {
    const double v = num_of(c.at("input").at("value"));
    const int digits = c.at("input").at("digits").get<int>();
    check(num_eq_json(c.at("expected"), uw::py_round(v, digits)),
          "py_round mismatch");
}

void run_py_isclose(const Json& c) {
    const auto& in = c.at("input");
    const bool got = uw::py_isclose(
        num_of(in.at("a")), num_of(in.at("b")),
        in.at("rel_tol").get<double>(), in.at("abs_tol").get<double>());
    check(got == c.at("expected").get<bool>(), "py_isclose mismatch");
}

void run_np_linspace(const Json& c) {
    const auto& in = c.at("input");
    const auto got = uw::np_linspace(in.at("lo").get<double>(),
                                     in.at("hi").get<double>(),
                                     in.at("n").get<std::size_t>());
    nums_eq(c.at("expected"), got, "np_linspace");
}

void run_env_int(const Json& c) {
    const auto& in = c.at("input");
    pwb_env_set("PWB_ORACLE_ENV_INT",
             in.at("raw").get<std::string>().c_str(), 1);
    const int got =
        uw::env_int("PWB_ORACLE_ENV_INT", in.at("fallback").get<int>());
    pwb_env_unset("PWB_ORACLE_ENV_INT");
    check(got == c.at("expected").get<int>(), "env_int mismatch");
}

void run_param_truthy(const Json& c) {
    const auto& v = c.at("input").at("value");
    uw::FactorTaskSlice task;
    if (!(v.is_object() && v.value("__missing__", false))) {
        task.parameters["k"] = any_from_json(v);
    }
    check(uw::param_truthy(task, "k") == c.at("expected").get<bool>(),
          "param_truthy mismatch");
}

void run_param_str_or(const Json& c) {
    const auto& v = c.at("input").at("value");
    uw::FactorTaskSlice task;
    if (!(v.is_object() && v.value("__missing__", false))) {
        task.parameters["k"] = any_from_json(v);
    }
    const std::string got =
        uw::param_str(task, "k").value_or("interpolation failed");
    check(got == c.at("expected").get<std::string>(),
          "param_str_or mismatch: got '" + got + "'");
}

void run_is_within_directory(const Json& c) {
    const auto& in = c.at("input");
    check(uw::is_within_directory(in.at("path").get<std::string>(),
                                  in.at("directory").get<std::string>()) ==
              c.at("expected").get<bool>(),
          "is_within_directory mismatch");
}

void run_resource_path(const Json& c) {
    const auto& in = c.at("input");
    const std::string got =
        uw::resource_path(in.at("path").get<std::string>(),
                          in.at("project_root").get<std::string>());
    check(got == c.at("expected").get<std::string>(),
          "resource_path mismatch: got '" + got + "'");
}

void run_absolute_resource_path(const Json& c) {
    const auto& in = c.at("input");
    const std::string got =
        uw::absolute_resource_path(in.at("path").get<std::string>(),
                                   in.at("project_root").get<std::string>());
    check(got == c.at("expected").get<std::string>(),
          "absolute_resource_path mismatch: got '" + got + "'");
}

void run_synthetic_points(const Json& c) {
    const auto& in = c.at("input");
    const auto got = uw::synthetic_sample_points(
        in.at("seed").get<int>(), in.at("factor_type").get<std::string>(),
        in.at("count").get<int>());
    const auto& expected = c.at("expected");
    check(got.size() == expected.size(), "synthetic_points count");
    for (std::size_t i = 0; i < got.size() && i < expected.size(); ++i) {
        const auto& e = expected[i];
        const auto& g = got[i];
        const auto* well = std::any_cast<std::string>(&g.at("well"));
        check(well != nullptr &&
                  *well == e.at("well").get<std::string>(),
              "synthetic_points well mismatch");
        const auto* x = std::any_cast<double>(&g.at("x"));
        const auto* y = std::any_cast<double>(&g.at("y"));
        const auto* val = std::any_cast<double>(&g.at("value"));
        check(x != nullptr && y != nullptr && val != nullptr,
              "synthetic_points coordinate types");
        if (x && y && val) {
            check(num_eq_json(e.at("x"), *x) &&
                      num_eq_json(e.at("y"), *y) &&
                      num_eq_json(e.at("value"), *val),
                  "synthetic_points value mismatch at " +
                      std::to_string(i));
        }
    }
}

void run_sha512(const Json& c) {
    const auto bytes = uw::sha512_bytes(c.at("input").at("text").get<std::string>());
    static const char* hex = "0123456789abcdef";
    std::string got;
    for (std::uint8_t b : bytes) {
        got += hex[b >> 4];
        got += hex[b & 0xf];
    }
    check(got == c.at("expected").get<std::string>(), "sha512 mismatch");
}

void run_nice_levels_range(const Json& c) {
    const auto& in = c.at("input");
    const auto got = uw::suggest_nice_levels_from_range(
        in.at("lo").get<double>(), in.at("hi").get<double>(),
        in.at("n_levels").get<int>());
    nums_eq(c.at("expected"), got, "nice_levels_range");
}

void run_nice_levels_grid(const Json& c) {
    const auto& in = c.at("input");
    const auto got = uw::suggest_nice_levels(grid_of(in.at("grid")),
                                             in.at("n_levels").get<int>());
    nums_eq(c.at("expected"), got, "nice_levels_grid");
}

void run_levels_fallback(const Json& c) {
    const auto& in = c.at("input");
    const auto got = uw::suggest_levels_fallback(
        in.at("lo").get<double>(), in.at("hi").get<double>(),
        in.at("n_levels").get<int>());
    nums_eq(c.at("expected"), got, "levels_fallback");
}

void run_levels_from_interval(const Json& c) {
    const auto& in = c.at("input");
    const auto got = uw::levels_from_interval(
        in.at("lo").get<double>(), in.at("hi").get<double>(),
        in.at("interval").get<double>());
    nums_eq(c.at("expected"), got, "levels_from_interval");
}

void run_upsert_draft(const Json& c) {
    const auto& in = c.at("input");
    std::vector<uw::ContourDraftSlice> ledger;
    for (const auto& l : in.at("ledger")) {
        ledger.push_back(draft_from_scope_json(l));
    }
    auto draft = draft_from_scope_json(in.at("draft"));
    auto out = uw::upsert_contour_draft(
        std::move(draft), ledger, in.at("updated_at").get<std::string>());
    check(out.id == c.at("expected").at("returned_id").get<std::string>(),
          "upsert_draft returned id");
    Json ledger_ids = Json::array();
    for (const auto& d : ledger) ledger_ids.push_back(d.id);
    check(ledger_ids == c.at("expected").at("ledger_ids"),
          "upsert_draft ledger ids");
}

void run_line_features(const Json& c) {
    const auto& dj = c.at("input").at("draft");
    uw::ContourDraftSlice draft;
    draft.id = dj.at("id").get<std::string>();
    draft.factor_type = dj.at("factor_type").get<std::string>();
    draft.target_horizon = dj.at("target_horizon").get<std::string>();
    for (const auto& s : dj.at("segments")) {
        uw::ContourSegmentSlice seg;
        seg.id = s.at("id").get<std::string>();
        seg.level = s.at("level").get<double>();
        for (const auto& p : s.at("coordinates")) {
            seg.coordinates.emplace_back(p[0].get<double>(),
                                         p[1].get<double>());
        }
        seg.closed = s.at("closed").get<bool>();
        if (s.contains("properties")) {
            seg.properties = any_map_of(s.at("properties"));
        }
        draft.segments.push_back(std::move(seg));
    }
    const auto features = uw::line_features_from_contour_draft(draft);
    Json got = Json::array();
    for (const auto& f : features) got.push_back(json_from_any(f));
    std::string diff;
    check(sem_eq(got, c.at("expected"), &diff),
          "line_features mismatch " + diff);
}

// The compile_drafts replay: real compile path, frozen extract lines +
// recorded ids through the seams.
void run_compile_drafts(const Json& c) {
    const auto& in = c.at("input");
    std::vector<uw::FactorTaskSlice> tasks;
    for (const auto& t : in.at("tasks")) tasks.push_back(task_from_json(t));
    std::vector<uw::ContourDraftSlice> ledger;

    std::optional<std::set<std::string>> task_ids;
    if (!in.at("task_ids").is_null()) {
        std::set<std::string> ids;
        for (const auto& id : in.at("task_ids")) {
            ids.insert(id.get<std::string>());
        }
        task_ids = std::move(ids);
    }
    const bool only_complete = in.value("only_complete", true);
    const int n_levels = in.at("n_levels").get<int>();
    const std::string updated_at = in.value("updated_at", std::string{});

    // Seams — absent for the filtered case (no extract happens).
    uw::ExtractLinesFn extract_fn;
    uw::IdFn id_fn;
    std::deque<std::string> id_queue;
    if (c.contains("seam")) {
        const auto& seam = c.at("seam");
        std::vector<double> expected_levels;
        for (const auto& l : seam.at("levels")) {
            expected_levels.push_back(num_of(l));
        }
        std::map<double, std::vector<std::vector<std::pair<double, double>>>>
            frozen_lines;
        for (const auto& [key, lines] : seam.at("lines").items()) {
            std::vector<std::vector<std::pair<double, double>>> polylines;
            for (const auto& line : lines) {
                std::vector<std::pair<double, double>> pts;
                for (const auto& p : line) {
                    pts.emplace_back(num_of(p[0]), num_of(p[1]));
                }
                polylines.push_back(std::move(pts));
            }
            frozen_lines[std::stod(key)] = std::move(polylines);
        }
        extract_fn = [expected_levels, frozen_lines](
                         const std::vector<double>& gx,
                         const std::vector<double>& gy, const uw::Grid2D& gz,
                         const std::vector<double>& levels,
                         const job::CancellationToken&) {
            // The level pick is part of the port — verify it, then return
            // the lines Python's engine produced for them.
            bool levels_ok = levels.size() == expected_levels.size();
            for (std::size_t i = 0; levels_ok && i < levels.size(); ++i) {
                levels_ok = std::fabs(levels[i] - expected_levels[i]) <= 1e-9;
            }
            check(levels_ok, "compile_drafts extract levels");
            (void)gx;
            (void)gy;
            (void)gz;
            return frozen_lines;
        };
        for (const auto& id : seam.at("id_order").at("segment_ids")) {
            id_queue.push_back(id.get<std::string>());
        }
        id_queue.push_back(seam.at("id_order").at("draft_id").get<std::string>());
        auto queue = std::make_shared<std::deque<std::string>>(id_queue);
        id_fn = [queue] {
            if (queue->empty()) return std::string("__exhausted");
            std::string id = queue->front();
            queue->pop_front();
            return id;
        };
    }

    job::CancellationToken token;
    const auto drafts = uw::compile_contour_drafts_for_project(
        tasks, ledger, task_ids, only_complete, n_levels, token, extract_fn,
        id_fn, updated_at);

    const auto& expected = c.at("expected");
    if (expected.contains("draft_count")) {
        check(static_cast<int>(drafts.size()) ==
                  expected.at("draft_count").get<int>(),
              "compile_drafts count");
        return;
    }
    Json got_drafts = Json::array();
    for (const auto& d : drafts) got_drafts.push_back(draft_to_json(d));
    Json expected_drafts = expected.at("drafts");
    for (auto& d : expected_drafts) d.erase("created_at");
    std::string diff;
    check(sem_eq(got_drafts, expected_drafts, &diff),
          "compile_drafts drafts " + diff);
    Json ledger_ids = Json::array();
    for (const auto& d : ledger) ledger_ids.push_back(d.id);
    check(ledger_ids == expected.at("ledger_ids"),
          "compile_drafts ledger ids");
}

void run_dtw_band(const Json& c) {
    const auto& in = c.at("input");
    std::optional<int> band;
    if (!in.at("band_radius").is_null()) {
        band = in.at("band_radius").get<int>();
    }
    check(uw::bounded_dtw_band(in.at("n_samples").get<int>(), band) ==
              c.at("expected").get<int>(),
          "dtw_band mismatch");
}

void run_dtw_correlate(const Json& c) {
    const auto& in = c.at("input");
    const auto nums = [](const Json& a) {
        std::vector<double> out;
        out.reserve(a.size());
        for (const auto& v : a) out.push_back(num_of(v));
        return out;
    };
    const double ref_depth = in.at("ref_depth").is_null()
                                 ? std::numeric_limits<double>::quiet_NaN()
                                 : in.at("ref_depth").get<double>();
    const auto got = uw::dtw_engine_correlate(
        nums(in.at("ref_values")), nums(in.at("ref_depths")),
        nums(in.at("tgt_values")), nums(in.at("tgt_depths")),
        in.at("band_radius").get<int>(), ref_depth);
    const auto& e = c.at("expected");
    check(got.feasible == e.at("feasible").get<bool>(),
          "dtw_correlate feasible");
    check(num_eq_json(e.at("suggested_depth"), got.suggested_depth),
          "dtw_correlate suggested_depth");
    check(num_eq_json(e.at("cost"), got.cost), "dtw_correlate cost");
    check(num_eq_json(e.at("confidence"), got.confidence),
          "dtw_correlate confidence");
}

void run_well_log_resources(const Json& c) {
    const auto& in = c.at("input");
    std::vector<uw::ResourceSlice> resources;
    for (const auto& r : in.at("resources")) {
        uw::ResourceSlice res;
        res.id = r.at("id").get<std::string>();
        res.name = r.value("name", std::string{});
        res.path = r.value("path", std::string{});
        res.type = r.value("type", std::string{});
        res.format = r.value("format", std::string{});
        resources.push_back(std::move(res));
    }
    // The oracle froze list_well_log_resources + the wanted/cap steps
    // verbatim — ref_from_resource/resolve gates were never exercised.
    auto wells = uw::list_well_log_resources(resources);
    if (in.contains("resource_ids") && !in.at("resource_ids").is_null()) {
        std::set<std::string> wanted;
        for (const auto& id : in.at("resource_ids")) {
            wanted.insert(id.get<std::string>());
        }
        std::vector<uw::ResourceSlice> filtered;
        for (const auto& r : wells) {
            if (wanted.count(r.id)) filtered.push_back(r);
        }
        wells = std::move(filtered);
    }
    const int cap = std::max(1, in.value("max_wells", 8));
    if (wells.size() > static_cast<std::size_t>(cap)) {
        wells.resize(static_cast<std::size_t>(cap));
    }
    Json got_ids = Json::array();
    for (const auto& r : wells) got_ids.push_back(r.id);
    check(got_ids == c.at("expected"), "well_log_resources order/filter/clamp");
}

void run_stratal_validate(const Json& c) {
    const auto& in = c.at("input");
    const auto top = grid_of(in.at("top"));
    const auto bot = grid_of(in.at("bot"));
    std::size_t n_samples = 0;
    const std::size_t* n_ptr = nullptr;
    if (!in.at("n_samples").is_null()) {
        n_samples = in.at("n_samples").get<std::size_t>();
        n_ptr = &n_samples;
    }
    const auto got = uw::validate_horizon_pair(top, bot, n_ptr);
    Json got_j = Json::array();
    for (bool v : got) got_j.push_back(v);
    check(got_j == c.at("expected"), "stratal_validate mask");
}

void run_stratal_surfaces(const Json& c) {
    const auto& in = c.at("input");
    std::vector<double> fracs;
    for (const auto& f : in.at("fractions")) fracs.push_back(num_of(f));
    const auto got = uw::build_proportional_surfaces(
        grid_of(in.at("top")), grid_of(in.at("bot")), fracs);
    check(got.size() == c.at("expected").size(), "stratal_surfaces count");
    for (std::size_t i = 0; i < got.size() && i < c.at("expected").size(); ++i) {
        grid_eq(c.at("expected")[i], got[i],
                "stratal_surfaces[" + std::to_string(i) + "]");
    }
}

uw::StratalMode stratal_mode_of(const std::string& m) {
    if (m == "mean") return uw::StratalMode::kMean;
    if (m == "max") return uw::StratalMode::kMax;
    return uw::StratalMode::kRms;
}

void run_stratal_extract(const Json& c) {
    const auto& in = c.at("input");
    const auto got = uw::extract_stratal_slice(
        volume_of(in.at("volume")), grid_of(in.at("surface")),
        in.value("window", 0), stratal_mode_of(in.value("mode", "rms")),
        in.value("order", 1) == 0);
    grid_eq(c.at("expected"), got, "stratal_extract");
}

void run_stratal_slice_volume(const Json& c) {
    const auto& in = c.at("input");
    std::vector<double> fracs;
    for (const auto& f : in.at("fractions")) fracs.push_back(num_of(f));
    std::vector<uw::Grid2D> surfaces;
    const auto maps = uw::stratal_slice_volume(
        volume_of(in.at("volume")), grid_of(in.at("top")),
        grid_of(in.at("bot")), fracs, in.value("window", 0),
        stratal_mode_of(in.value("mode", "rms")),
        in.value("order", 1) == 0, &surfaces);
    const auto& e = c.at("expected");
    check(maps.size() == e.at("maps").size(), "stratal_slice_volume maps");
    for (std::size_t i = 0; i < maps.size() && i < e.at("maps").size(); ++i) {
        grid_eq(e.at("maps")[i], maps[i], "sv map " + std::to_string(i));
    }
    check(surfaces.size() == e.at("surfaces").size(), "sv surfaces count");
    for (std::size_t i = 0;
         i < surfaces.size() && i < e.at("surfaces").size(); ++i) {
        grid_eq(e.at("surfaces")[i], surfaces[i],
                "sv surface " + std::to_string(i));
    }
}

void run_ms_to_preview(const Json& c) {
    const auto& in = c.at("input");
    const auto got = uw::ms_to_preview_sample_index(
        grid_of(in.at("ms")), in.at("dt_ms").get<double>(),
        in.at("t0_ms").get<double>(), in.at("sample_stride").get<int>());
    grid_eq(c.at("expected"), got, "ms_to_preview");
}

void run_ms_grids_preview(const Json& c) {
    const auto& in = c.at("input");
    const auto got = uw::ms_grids_to_preview_sample_indices(
        grid_of(in.at("top_ms")), grid_of(in.at("bot_ms")),
        in.at("n_i_prev").get<std::size_t>(),
        in.at("n_x_prev").get<std::size_t>(),
        in.at("stride_i").get<double>(), in.at("stride_x").get<double>(),
        in.at("dt_ms").get<double>(), in.at("t0_ms").get<double>(),
        in.at("sample_stride").get<int>());
    grid_eq(c.at("expected")[0], got.first, "ms_grids_preview top");
    grid_eq(c.at("expected")[1], got.second, "ms_grids_preview bot");
}

void run_build_stratal_surfaces(const Json& c) {
    const auto& in = c.at("input");
    std::vector<double> fracs;
    for (const auto& f : in.at("fractions")) fracs.push_back(num_of(f));
    const auto got = uw::build_stratal_surfaces(
        grid_of(in.at("top_sidx")), grid_of(in.at("bot_sidx")),
        in.at("n_samples").get<std::size_t>(), fracs);
    const auto& e = c.at("expected");
    if (e.is_null()) {
        check(!got.has_value(), "build_stratal_surfaces should be nullopt");
        return;
    }
    check(got.has_value(), "build_stratal_surfaces should produce");
    if (!got) return;
    const auto& [surfaces, masked] = *got;
    check(surfaces.size() == e.at("surfaces").size(), "bss surfaces");
    for (std::size_t i = 0;
         i < surfaces.size() && i < e.at("surfaces").size(); ++i) {
        grid_eq(e.at("surfaces")[i], surfaces[i],
                "bss surface " + std::to_string(i));
    }
    grid_eq(e.at("masked")[0], masked[0], "bss masked top");
    grid_eq(e.at("masked")[1], masked[1], "bss masked bot");
}

uw::DemoNoiseFn noise_fn_of(const Json& c) {
    if (!c.contains("noise")) return {};
    std::vector<double> noise;
    for (const auto& v : c.at("noise").at("data")) {
        noise.push_back(num_of(v));
    }
    return [noise](std::vector<double>& out) {
        out = noise;  // raw f64 samples; *0.05 + f32 happens inside
    };
}

void run_demo_volume(const Json& c) {
    const auto& in = c.at("input");
    const auto& shape = in.at("shape");
    const auto got = uw::make_synthetic_demo_volume(
        shape[0].get<std::size_t>(), shape[1].get<std::size_t>(),
        shape[2].get<std::size_t>(), in.value("n_reflectors", 3),
        noise_fn_of(c));
    volume_eq(c.at("expected"), got, "demo_volume");
}

void run_demo_grids(const Json& c) {
    const auto& in = c.at("input");
    const auto& shape = in.at("shape");
    const auto [vol, top, bot] = uw::make_demo_stratal_grids(
        shape[0].get<std::size_t>(), shape[1].get<std::size_t>(),
        shape[2].get<std::size_t>(), noise_fn_of(c));
    const auto& e = c.at("expected");
    volume_eq(e.at("volume"), vol, "demo_grids volume");
    grid_eq(e.at("top"), top, "demo_grids top");
    grid_eq(e.at("bot"), bot, "demo_grids bot");
}

// ---------------------------------------------------------------------------
// geomodel primitives + GeologicalModelingWorker.
// ---------------------------------------------------------------------------

Json geom_to_json(const uw::GeomPrimitive& g) {
    Json j;
    Json verts = Json::array();
    for (const auto& v : g.vertices) {
        verts.push_back(Json::array({static_cast<double>(v[0]),
                                     static_cast<double>(v[1]),
                                     static_cast<double>(v[2])}));
    }
    Json faces = Json::array();
    for (const auto& f : g.faces) {
        faces.push_back(Json::array({f[0], f[1], f[2]}));
    }
    Json colors = Json::array();
    for (const auto& col : g.face_colors) {
        colors.push_back(Json::array({static_cast<double>(col[0]),
                                      static_cast<double>(col[1]),
                                      static_cast<double>(col[2]),
                                      static_cast<double>(col[3])}));
    }
    j["vertices"] = verts;
    j["faces"] = faces;
    j["face_colors"] = colors;
    return j;
}

uw::Vec3d vec3_of(const Json& a) {
    return {a[0].get<double>(), a[1].get<double>(), a[2].get<double>()};
}

uw::Color4 color4_of(const Json& a) {
    return {a[0].get<double>(), a[1].get<double>(), a[2].get<double>(),
            a[3].get<double>()};
}

bool geom_eq(const Json& expected, const uw::GeomPrimitive& got,
             const std::string& what) {
    bool ok = true;
    ok &= nums_eq(expected.at("vertices"),
                  [&] {
                      std::vector<double> v;
                      for (const auto& p : got.vertices) {
                          v.insert(v.end(), {static_cast<double>(p[0]),
                                             static_cast<double>(p[1]),
                                             static_cast<double>(p[2])});
                      }
                      return v;
                  }(),
                  what + " vertices", 1e-6);
    const auto& ef = expected.at("faces");
    if (ef.size() != got.faces.size()) {
        check(false, what + " faces size");
        ok = false;
    } else {
        for (std::size_t i = 0; i < got.faces.size(); ++i) {
            for (int k = 0; k < 3; ++k) {
                if (ef[i][k].get<std::int64_t>() !=
                    static_cast<std::int64_t>(got.faces[i][k])) {
                    check(false, what + " face " + std::to_string(i));
                    ok = false;
                    break;
                }
            }
        }
    }
    ok &= nums_eq(expected.at("face_colors"),
                  [&] {
                      std::vector<double> v;
                      for (const auto& col : got.face_colors) {
                          v.insert(v.end(), {static_cast<double>(col[0]),
                                             static_cast<double>(col[1]),
                                             static_cast<double>(col[2]),
                                             static_cast<double>(col[3])});
                      }
                      return v;
                  }(),
                  what + " face_colors", 1e-6);
    return ok;
}

void run_geom_primitive(const Json& c) {
    const auto& in = c.at("input");
    uw::GeomPrimitive got;
    const std::string kind = c.at("kind").get<std::string>();
    if (kind == "geom_cylinder") {
        got = uw::generate_cylinder_geometry(
            vec3_of(in.at("p1")), vec3_of(in.at("p2")),
            in.at("radius").get<double>(), color4_of(in.at("color")),
            in.at("resolution").get<int>());
    } else if (kind == "geom_tube") {
        std::vector<uw::Vec3d> path;
        for (const auto& p : in.at("path")) path.push_back(vec3_of(p));
        got = uw::generate_tube_geometry(path, in.at("radius").get<double>(),
                                         color4_of(in.at("color")),
                                         in.at("resolution").get<int>());
    } else {
        got = uw::generate_fault_geometry(
            {in.at("xlim")[0].get<double>(), in.at("xlim")[1].get<double>()},
            {in.at("ylim")[0].get<double>(), in.at("ylim")[1].get<double>()},
            in.at("nx").get<int>(), in.at("ny").get<int>(),
            color4_of(in.at("color")));
    }
    geom_eq(c.at("expected"), got, kind);
}

Json named_geoms_to_json(const std::vector<uw::NamedGeom>& geoms) {
    Json out = Json::array();
    for (const auto& g : geoms) {
        Json j = geom_to_json(g.geom);
        j["name"] = g.name;
        out.push_back(std::move(j));
    }
    return out;
}

uw::GeoModelingInput geomodel_input_of(const Json& in) {
    uw::GeoModelingInput input;
    input.density = in.value("density", std::string{"低"});
    input.algorithm = in.value("algorithm", std::string{"demo"});
    input.demo = in.value("demo", true);
    input.sleep_fn = [](double) {};  // oracle runs must not stall
    return input;
}

void run_geomodel_dim(const Json& c) {
    job::CancellationToken token;
    job::JobContext ctx{"oracle", token};
    const auto got = uw::run_geological_modeling(
        geomodel_input_of(c.at("input")), ctx);
    check(got.dim == c.at("expected").get<int>(), "geomodel_dim");
}

void run_geomodel_volume(const Json& c) {
    job::CancellationToken token;
    job::JobContext ctx{"oracle", token};
    const auto got = uw::run_geological_modeling(
        geomodel_input_of(c.at("input")), ctx);
    const auto& e = c.at("expected");
    check(got.dim == e.at("dim").get<int>(), "geomodel_volume dim");
    static const char* hex = "0123456789abcdef";
    std::string got_hex;
    got_hex.reserve(got.volume_data.size() * 2);
    for (std::uint8_t b : got.volume_data) {
        got_hex += hex[b >> 4];
        got_hex += hex[b & 0xf];
    }
    check(got_hex == e.at("volume_hex").get<std::string>(),
          "geomodel_volume bytes");
}

void run_geomodel_records(const Json& c) {
    job::CancellationToken token;
    job::JobContext ctx{"oracle", token};
    const auto got = uw::run_geological_modeling(
        geomodel_input_of(c.at("input")), ctx);
    const auto& e = c.at("expected");
    std::string diff;
    check(sem_eq(got.bh_raw, e.at("bh_raw"), &diff), "bh_raw " + diff);
    check(sem_eq(got.faults_raw, e.at("faults_raw"), &diff),
          "faults_raw " + diff);
    // tunnel_raw: the slice keeps tunnel records inside the NamedGeom
    // tunnels (verified end-to-end by geomodel_scene) — the raw dict is
    // not part of the DTO surface.
}

void run_geomodel_scene(const Json& c) {
    job::CancellationToken token;
    job::JobContext ctx{"oracle", token};
    const auto got = uw::run_geological_modeling(
        geomodel_input_of(c.at("input")), ctx);
    const auto& e = c.at("expected");
    check(got.source == e.at("source").get<std::string>(), "scene source");
    check(static_cast<int>(got.boreholes.size()) ==
              e.at("n_borehole_meshes").get<int>(),
          "scene n_borehole_meshes");
    const auto compare_geoms = [&](const Json& expected_list,
                                   const std::vector<uw::NamedGeom>& got_list,
                                   const std::string& what) {
        check(expected_list.size() == got_list.size(), what + " count");
        for (std::size_t i = 0;
             i < got_list.size() && i < expected_list.size(); ++i) {
            check(got_list[i].name ==
                      expected_list[i].at("name").get<std::string>(),
                  what + " name " + std::to_string(i));
            geom_eq(expected_list[i], got_list[i].geom,
                    what + " " + std::to_string(i));
        }
    };
    compare_geoms(e.at("boreholes"), got.boreholes, "boreholes");
    compare_geoms(e.at("tunnels"), got.tunnels, "tunnels");
    compare_geoms(e.at("faults"), got.faults, "faults");
}

// ---------------------------------------------------------------------------
// Integrity + viz resolve + sha256.
// ---------------------------------------------------------------------------

void run_integrity_catalog_state(const Json& c) {
    const auto got = uw::integrity_state_from_catalog_status(
        c.at("input").at("status").get<std::string>());
    check(std::string(uw::to_string(got)) ==
              c.at("expected").get<std::string>(),
          "integrity_catalog_state mismatch");
}

void run_sha256(const Json& c) {
    // Write the frozen bytes to a temp file, hash it back.
    const auto& hex_in = c.at("input").at("bytes_hex").get<std::string>();
    std::string bytes;
    bytes.reserve(hex_in.size() / 2);
    for (std::size_t i = 0; i + 1 < hex_in.size(); i += 2) {
        bytes.push_back(static_cast<char>(
            std::stoul(hex_in.substr(i, 2), nullptr, 16)));
    }
    namespace fs = std::filesystem;
    const auto path = fs::temp_directory_path() /
                      ("pwb_oracle_sha256_" + g_case_id + ".bin");
    {
        std::ofstream out(path, std::ios::binary);
        out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    }
    const auto got = uw::compute_sha256(path.string());
    std::error_code ec;
    fs::remove(path, ec);
    check(got.has_value() &&
              *got == c.at("expected").get<std::string>(),
          "sha256 mismatch");
}

void run_integrity_summary(const Json& c) {
    const auto& in = c.at("input");
    uw::IntegrityCheckReport report;
    report.verified_count = in.at("verified").get<int>();
    report.modified_count = in.at("modified").get<int>();
    report.missing_count = in.at("missing").get<int>();
    report.unmanaged_count = in.at("unmanaged").get<int>();
    check(report.summary_text() == c.at("expected").get<std::string>(),
          "integrity_summary mismatch");
}

void run_viz_resource(const Json& c) {
    const auto& in = c.at("input");
    uw::ResourceSlice res;
    res.id = in.at("id").get<std::string>();
    res.name = in.value("name", std::string{});
    res.path = in.value("path", std::string{});
    res.type = in.value("type", std::string{});
    res.format = in.value("format", std::string{});
    const auto& e = c.at("expected");
    check(uw::supports_resource(res) == e.at("supports").get<bool>(),
          "viz_resource supports");
    const auto ref = uw::ref_from_resource(res);
    if (e.at("ref").is_null()) {
        check(!ref.has_value(), "viz_resource ref should be absent");
        return;
    }
    check(ref.has_value(), "viz_resource ref missing");
    if (!ref) return;
    const auto& er = e.at("ref");
    check(ref->kind == er.at("kind").get<std::string>(), "viz_ref kind");
    check(ref->id == er.at("id").get<std::string>(), "viz_ref id");
    check(ref->path == er.at("path").get<std::string>(), "viz_ref path");
    check(ref->label == er.at("label").get<std::string>(), "viz_ref label");
    check(ref->source == er.at("source").get<std::string>(),
          "viz_ref source");
}

// ---------------------------------------------------------------------------
// factor_schedule — the full orchestration replay with frozen seams.
// ---------------------------------------------------------------------------

void run_factor_schedule(const Json& c) {
    const auto& in = c.at("input");
    const auto& seam = c.at("seam");

    uw::FactorPrepareSnapshot snapshot;
    const auto& sj = in.at("snapshot");
    snapshot.generation = sj.at("generation").get<int>();
    snapshot.method = sj.at("method").get<std::string>();
    snapshot.grid_n = sj.at("grid_n").get<int>();
    snapshot.power = sj.at("power").get<double>();
    snapshot.force = sj.at("force").get<bool>();
    snapshot.seed = sj.at("seed").get<int>();
    snapshot.target_horizon = sj.at("target_horizon").get<std::string>();
    if (!sj.at("project_crs").is_null()) {
        snapshot.project_crs = sj.at("project_crs").get<std::string>();
    }
    snapshot.created_defaults = sj.value("created_defaults", false);
    for (const auto& t : sj.at("tasks")) {
        snapshot.tasks.push_back(task_from_json(t));
    }

    const auto& classify_map = seam.at("classify");
    const auto& batch_spec = seam.at("batch");
    const auto& group_keys = seam.at("group_keys");

    uw::FactorPrepareSeams seams;
    seams.classify_fn =
        [&classify_map](const uw::FactorTaskSlice& task,
                        const uw::PrepareExecContext&, bool,
                        uw::FingerprintMemo*)
        -> std::pair<uw::FactorDirtyState, std::string> {
        const auto it = classify_map.find(task.id);
        if (it == classify_map.end()) {
            check(false, "classify seam missing task " + task.id);
            return {uw::FactorDirtyState::unknown, ""};
        }
        const auto state = uw::factor_dirty_state_from_string(
            it->at("state").get<std::string>());
        if (!state) {
            check(false, "classify seam bad state " + task.id);
            return {uw::FactorDirtyState::unknown, ""};
        }
        return {*state, it->at("result_fp").get<std::string>()};
    };

    seams.batch_fn =
        [&batch_spec](uw::FactorPrepareSeams::BatchArgs& args,
                      const job::CancellationToken&) {
            // Scripted rules first — Python's fakes matched on task NAME
            // within the batch's task set, then raised (or cancelled).
            for (const auto& rule : batch_spec.at("rules")) {
                const std::string when =
                    rule.at("when_task_name").get<std::string>();
                bool match = when == "*";
                if (!match) {
                    for (const auto& t : args.tasks) {
                        if (t.name == when) {
                            match = true;
                            break;
                        }
                    }
                }
                if (!match) continue;
                const int delay = rule.value("delay_ms", 0);
                if (delay > 0) {
                    std::this_thread::sleep_for(
                        std::chrono::milliseconds(delay));
                }
                const std::string kind = rule.at("raise").get<std::string>();
                if (kind == "cancelled") throw job::JobCancelled("");
                throw std::runtime_error(
                    rule.value("message", std::string{}));
            }
            // Marks — post-batch status + last_error, exactly what the
            // recorded Python fakes stamped.
            if (batch_spec.contains("marks")) {
                for (auto& t : args.tasks) {
                    const auto it = batch_spec.at("marks").find(t.id);
                    if (it == batch_spec.at("marks").end()) continue;
                    t.status = it->at("status").get<std::string>();
                    if (!it->at("last_error").is_null()) {
                        t.parameters["last_error"] =
                            it->at("last_error").get<std::string>();
                    }
                }
            }
        };

    seams.group_key_fn =
        [&group_keys](const uw::FactorTaskSlice& task,
                      const uw::PrepareExecContext&)
        -> std::optional<std::string> {
        const auto it = group_keys.find(task.id);
        if (it == group_keys.end() || it->is_null()) return std::nullopt;
        return it->get<std::string>();
    };

    // grid_peek — the ids the Python run saw with a live grid payload.
    std::set<std::string> grid_ids;
    if (!batch_spec.at("grids").is_null()) {
        for (const auto& id : batch_spec.at("grids")) {
            grid_ids.insert(id.get<std::string>());
        }
    }
    seams.grid_peek_fn = [&grid_ids](const std::string& task_id) -> std::any {
        if (grid_ids.count(task_id)) return std::string("grid-payload");
        return std::any{};
    };
    seams.clock_fn = [] { return 0.0; };  // deterministic ms fields

    // Deterministic replay of the frozen parallel completion order:
    // Python's as_completed sequence is timing-dependent, so each group's
    // batch_fn waits until the schedule releases it — order[0] runs on
    // arrival, later groups run only after the prior one has emitted,
    // then the rest drain. Completion order becomes reproducible.
    struct GroupGate {
        std::mutex m;
        std::condition_variable cv;
        std::vector<std::string> order;
        std::set<std::string> released;
        std::size_t next = 0;
        bool drain_all = false;
    };
    auto gate = std::make_shared<GroupGate>();
    if (in.at("workers").get<int>() > 1) {
        for (const auto& p : c.at("expected").at("progress")) {
            if (p.value("phase", std::string{}) == "executing" &&
                !p.at("current_group").is_null()) {
                gate->order.push_back(
                    p.at("current_group").get<std::string>());
            }
        }
    }
    const bool gated = !gate->order.empty();
    if (gated) {
        auto scripted = seams.batch_fn;
        seams.batch_fn =
            [scripted, gate, &group_keys](
                uw::FactorPrepareSeams::BatchArgs& args,
                const job::CancellationToken& tok) {
                if (!args.tasks.empty()) {
                    const auto it = group_keys.find(args.tasks.front().id);
                    const std::string gkey =
                        (it == group_keys.end() || it->is_null())
                            ? std::string("None")
                            : it->get<std::string>();
                    std::unique_lock<std::mutex> lk(gate->m);
                    if (!gate->released.count(gkey) && !gate->drain_all) {
                        if (gate->next == 0 && gate->order[0] == gkey) {
                            // First frozen-order group self-releases on
                            // arrival; all others wait for emissions.
                            gate->released.insert(gkey);
                            gate->next = 1;
                        } else {
                            gate->cv.wait(lk, [&] {
                                return gate->drain_all ||
                                       gate->released.count(gkey) != 0;
                            });
                        }
                    }
                }
                scripted(args, tok);
            };
    }

    std::vector<Json> progress_log;
    const auto progress = [&progress_log, gate](
                              const uw::FactorPrepareProgress& p) {
        progress_log.push_back(progress_to_json(p));
        if (p.phase == "executing") {
            std::lock_guard<std::mutex> lk(gate->m);
            if (gate->next < gate->order.size()) {
                gate->released.insert(gate->order[gate->next]);
                ++gate->next;
            }
            if (gate->next >= gate->order.size()) gate->drain_all = true;
            gate->cv.notify_all();
        }
    };

    job::CancellationToken token;
    const int workers = in.at("workers").get<int>();
    const auto result = uw::run_factor_prepare_schedule(
        snapshot, token, progress, seams, workers);

    // ---- expected.result ----
    const auto& er = c.at("expected").at("result");
    check(result.generation == er.at("generation").get<int>(), "generation");
    check(result.method == er.at("method").get<std::string>(), "method");
    check(result.clean_count == er.at("clean_count").get<int>(),
          "clean_count");
    check(result.dirty_count == er.at("dirty_count").get<int>(),
          "dirty_count");
    check(result.executed_count == er.at("executed_count").get<int>(),
          "executed_count");
    check(result.failed_count == er.at("failed_count").get<int>(),
          "failed_count");
    check(result.cancelled == er.at("cancelled").get<bool>(), "cancelled");
    check(result.cancelled_count == er.at("cancelled_count").get<int>(),
          "cancelled_count");
    check(result.workers == er.at("workers").get<int>(), "workers");
    check(result.created_default_tasks ==
              er.at("created_default_tasks").get<bool>(),
          "created_default_tasks");
    if (er.at("grid_n").is_null()) {
        check(!result.grid_n.has_value(), "grid_n should be absent");
    } else {
        check(result.grid_n.has_value() &&
                  *result.grid_n == er.at("grid_n").get<int>(),
              "grid_n");
    }
    check(result.power == er.at("power").get<double>(), "power");
    check(result.snapshot_ms >= 0.0 && result.classify_ms >= 0.0 &&
              result.execute_ms >= 0.0,
          "ms fields nonneg");

    // task_results — ordered by snapshot task order (deterministic even
    // for parallel runs; the scheduler orders staged results, not
    // completion order).
    check(result.task_results.size() == er.at("task_results").size(),
          "task_results count");
    const std::size_t n =
        std::min(result.task_results.size(), er.at("task_results").size());
    for (std::size_t i = 0; i < n; ++i) {
        const Json got_j = task_result_to_json(result.task_results[i]);
        std::string diff;
        check(sem_eq(got_j, er.at("task_results")[i], &diff),
              "task_results[" + std::to_string(i) + "] " + diff);
    }

    // ---- expected.progress ----
    Json got_progress = Json::array();
    for (const auto& p : progress_log) got_progress.push_back(p);
    const std::string pcheck = c.value("progress_check", "exact");
    std::string diff;
    if (pcheck == "exact") {
        check(sem_eq(got_progress, c.at("expected").at("progress"), &diff),
              "progress " + diff);
    } else {
        // Parallel completion order is nondeterministic — compare the
        // progress emission as a multiset.
        Json sorted_got = got_progress;
        Json sorted_exp = c.at("expected").at("progress");
        const auto by_dump = [](const Json& a, const Json& b) {
            return a.dump() < b.dump();
        };
        std::sort(sorted_got.begin(), sorted_got.end(), by_dump);
        std::sort(sorted_exp.begin(), sorted_exp.end(), by_dump);
        const bool prog_ok = sem_eq(sorted_got, sorted_exp, &diff);
        if (!prog_ok) {
            std::fprintf(stderr, "GOT %s\nEXP %s\n",
                         sorted_got.dump().c_str(),
                         sorted_exp.dump().c_str());
        }
        check(prog_ok, "progress (multiset) " + diff);
    }
}

// ---------------------------------------------------------------------------
// Driver.
// ---------------------------------------------------------------------------

void run_case(const Json& c) {
    g_case_id = c.at("id").get<std::string>();
    const std::string kind = c.at("kind").get<std::string>();

    const int checks_before = g_checks;
    const int failures_before = g_failures;

    if (kind == "py_round") run_py_round(c);
    else if (kind == "py_isclose") run_py_isclose(c);
    else if (kind == "np_linspace") run_np_linspace(c);
    else if (kind == "env_int") run_env_int(c);
    else if (kind == "param_truthy") run_param_truthy(c);
    else if (kind == "param_str_or") run_param_str_or(c);
    else if (kind == "is_within_directory") run_is_within_directory(c);
    else if (kind == "resource_path") run_resource_path(c);
    else if (kind == "absolute_resource_path") run_absolute_resource_path(c);
    else if (kind == "synthetic_points") run_synthetic_points(c);
    else if (kind == "sha512") run_sha512(c);
    else if (kind == "nice_levels_range") run_nice_levels_range(c);
    else if (kind == "nice_levels_grid") run_nice_levels_grid(c);
    else if (kind == "levels_fallback") run_levels_fallback(c);
    else if (kind == "levels_from_interval") run_levels_from_interval(c);
    else if (kind == "upsert_draft") run_upsert_draft(c);
    else if (kind == "line_features") run_line_features(c);
    else if (kind == "compile_drafts") run_compile_drafts(c);
    else if (kind == "dtw_band") run_dtw_band(c);
    else if (kind == "dtw_correlate") run_dtw_correlate(c);
    else if (kind == "well_log_resources") run_well_log_resources(c);
    else if (kind == "stratal_validate") run_stratal_validate(c);
    else if (kind == "stratal_surfaces") run_stratal_surfaces(c);
    else if (kind == "stratal_extract") run_stratal_extract(c);
    else if (kind == "stratal_slice_volume") run_stratal_slice_volume(c);
    else if (kind == "ms_to_preview") run_ms_to_preview(c);
    else if (kind == "ms_grids_preview") run_ms_grids_preview(c);
    else if (kind == "build_stratal_surfaces") run_build_stratal_surfaces(c);
    else if (kind == "demo_volume") run_demo_volume(c);
    else if (kind == "demo_grids") run_demo_grids(c);
    else if (kind == "geom_cylinder" || kind == "geom_tube" ||
             kind == "geom_fault") run_geom_primitive(c);
    else if (kind == "geomodel_dim") run_geomodel_dim(c);
    else if (kind == "geomodel_volume") run_geomodel_volume(c);
    else if (kind == "geomodel_records") run_geomodel_records(c);
    else if (kind == "geomodel_scene") run_geomodel_scene(c);
    else if (kind == "integrity_catalog_state") run_integrity_catalog_state(c);
    else if (kind == "sha256") run_sha256(c);
    else if (kind == "integrity_summary") run_integrity_summary(c);
    else if (kind == "viz_resource") run_viz_resource(c);
    else if (kind == "factor_schedule") run_factor_schedule(c);
    else check(false, "unhandled kind: " + kind);

    const bool expect_mismatch = c.value("expect_mismatch", false);
    if (expect_mismatch) {
        // Negative self-check: this case MUST have flagged at least one
        // failure. If nothing failed, the harness is blind to drift.
        if (g_failures == failures_before) {
            std::fprintf(
                stderr,
                "FAIL [%s] expect_mismatch case produced no mismatch — "
                "harness is blind\n",
                g_case_id.c_str());
            ++g_failures;
        } else {
            // Reconcile: the injected drift was correctly detected —
            // undo the failure count and record the self-check pass.
            g_failures = failures_before;
            g_checks = checks_before + 1;
            ++g_selfcheck;
        }
    }
}

}  // namespace

int main() {
    const char* fixture_path = PWB_UI_WORKERS_FIXTURE;
    std::ifstream in(fixture_path);
    if (!in) {
        std::fprintf(stderr, "cannot open fixture %s\n", fixture_path);
        return 2;
    }
    const Json fixture = Json::parse(in);
    for (const auto& c : fixture.at("cases")) {
        run_case(c);
    }
    std::fprintf(stderr,
                 "ui_workers.oracle: %d checks, %d failures "
                 "(%d negative self-checks verified)\n",
                 g_checks, g_failures, g_selfcheck);
    return g_failures == 0 ? 0 : 1;
}
