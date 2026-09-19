// CONV-33 route A2 — workflow versioning oracle replay test.
//
// Replays libs/workflow_runtime/workflow_runtime_tests/fixtures/
// workflow_versioning_oracle.json (frozen from the REAL Python
// implementation — paleo_workbench/workflow/versioning.py over the
// project version models — by tools/oracle/
// generate_workflow_versioning_fixtures.py) through the C++ port and
// compares against the frozen expectation: semantic JSON equality plus
// raise parity (python_class "ValueError" + verbatim message — Chinese
// text, fullwidth '（'/'；' separators) plus project-unchanged checks on
// every gate rejection.
//
// Determinism: each case carries "clock" = the Python counter state
// BEFORE the call ({prefix}_{n:012d} ids / 2020-01-01T00:00:{n:02d}
// stamps); OracleClock reproduces the exact factory firing order pydantic
// used (declaration order, frozen by the fixture).
//
// Byte-level fingerprint assertions: the frozen "raw" is the exact
// json.dumps(sort_keys=True, ensure_ascii=False, default=str) byte
// stream (DEFAULT ", "/": " separators — NOT the compact canonical
// variant); the test compares versioning_fingerprint_raw_bytes() against
// it verbatim and re-hashes it through domain::Sha256.
//
// Includes comparator NEGATIVE SELF-CHECKS (tampered expectations must
// FAIL) and C++-local sink semantics checks: a throwing
// VersionFinalizeSink must not fail the finalize (Python broad-except,
// L189-203) and a recording sink must receive the composed call.
#include <pwb/domain/json.hpp>
#include <pwb/domain/sha256.hpp>
#include <pwb/workflow_runtime/versioning.hpp>

#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace pwb::workflow_runtime {

// Test-only byte-level seam DEFINED in src/versioning.cpp (not in the
// frozen header): the exact json.dumps byte stream _fingerprint_map
// hashes — frozen by the oracle for byte-level assertion.
std::string versioning_fingerprint_raw_bytes(const domain::Json& map_doc);

}  // namespace pwb::workflow_runtime

namespace {

using pwb::domain::Json;
using pwb::project::CompilationRun;
using pwb::project::ContourDraft;
using pwb::project::QualityReport;
using pwb::project::VersionSet;
using pwb::project::VersionSnapshot;
using pwb::workflow_runtime::FinalizeDeps;
using pwb::workflow_runtime::FinalizeOptions;
using pwb::workflow_runtime::VersionFinalizeSink;
using pwb::workflow_runtime::active_final_snapshot;
using pwb::workflow_runtime::build_snapshot;
using pwb::workflow_runtime::finalize_map_version;
using pwb::workflow_runtime::version_set_summary;

int g_failures = 0;
int g_checks = 0;

Json read_fixture(const char* path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error(std::string("cannot open fixture: ") + path);
    }
    Json data;
    try {
        in >> data;
    } catch (const std::exception& exc) {
        throw std::runtime_error(std::string("fixture parse error: ") +
                                 exc.what());
    }
    return data;
}

// Compare after a dump/parse round-trip so int/unsigned spellings
// collapse exactly like Python's JSON serialization did for the frozen
// side (json_semantically_equal keeps int vs float a TYPE difference).
bool json_eq(const Json& got, const Json& expect) {
    return pwb::domain::json_semantically_equal(Json::parse(got.dump()),
                                                expect);
}

bool compare(const std::string& id, const Json& got, const Json& expect,
             bool quiet) {
    if (json_eq(got, expect)) return true;
    if (!quiet) {
        const auto diff =
            pwb::domain::json_semantic_diff(Json::parse(got.dump()), expect);
        std::printf("FAIL %s at %s: %s\n  got:    %s\n  expect: %s\n",
                    id.c_str(), diff.path.c_str(), diff.reason.c_str(),
                    got.dump().c_str(), expect.dump().c_str());
        ++g_failures;
    }
    return false;
}

// Byte-level assertion (fingerprint raw stream) — exact string equality.
bool compare_bytes(const std::string& id, const std::string& got,
                   const std::string& expect, bool quiet) {
    if (got == expect) return true;
    if (!quiet) {
        std::printf("FAIL %s: byte streams differ\n  got:    %s\n  expect: %s\n",
                    id.c_str(), got.c_str(), expect.c_str());
        ++g_failures;
    }
    return false;
}

Json raise_json(const std::exception& exc) {
    return Json{{"python_class", "ValueError"}, {"message", exc.what()}};
}

// ------------------------------------------------ deterministic clock seam --

// Mirrors the generator's counters: ids "{prefix}_{n:012d}", stamps
// "2020-01-01T00:00:{n:02d}+00:00". Seeded from each case's frozen
// pre-call state so make_id/now_iso fire in the same order pydantic's
// default factories did (field-declaration order).
struct OracleClock {
    int id_n = 0;
    int now_n = 0;

    std::string make_id(std::string_view prefix) {
        char tail[16];
        std::snprintf(tail, sizeof tail, "%012d", ++id_n);
        return std::string(prefix) + "_" + tail;
    }

    std::string now_iso() {
        char buffer[48];
        std::snprintf(buffer, sizeof buffer,
                      "2020-01-01T00:00:%02d+00:00", ++now_n);
        return buffer;
    }

    pwb::project::ModelClock model_clock() {
        pwb::project::ModelClock clock;
        clock.now_iso = [this] { return now_iso(); };
        clock.make_id = [this](std::string_view prefix) {
            return make_id(prefix);
        };
        return clock;
    }
};

FinalizeOptions options_from(const Json& spec) {
    FinalizeOptions options;
    if (spec.contains("note")) {
        options.note = spec.at("note").get<std::string>();
    }
    if (spec.contains("operator")) {
        options.operator_ = spec.at("operator").get<std::string>();
    }
    if (spec.contains("require_qc_pass")) {
        options.require_qc_pass = spec.at("require_qc_pass").get<bool>();
    }
    return options;
}

// --------------------------------------------------------------- dispatch --

bool dispatch(const Json& cs, const Json& expect, bool quiet) {
    const std::string id = cs.at("id").get<std::string>();
    const std::string fn = cs.at("fn").get<std::string>();
    const Json& input = cs.at("input");
    OracleClock clock;
    clock.id_n = cs.at("clock").at("id_consumed").get<int>();
    clock.now_n = cs.at("clock").at("now_consumed").get<int>();
    FinalizeDeps deps;
    deps.clock = clock.model_clock();

    if (fn == "build_snapshot") {
        const VersionSnapshot snap = build_snapshot(
            input.at("project"), input.at("map_doc"),
            input.at("note").get<std::string>(),
            input.at("created_by").get<std::string>(), deps.clock);
        return compare(id, snap.to_dict(), expect.at("snapshot"), quiet);
    }
    if (fn == "finalize_map_version") {
        Json project = input.at("project");
        try {
            const VersionSet vset = finalize_map_version(
                project, input.at("map_document_id").get<std::string>(),
                options_from(input.at("options")), deps);
            return compare(id,
                           Json{{"version_set", vset.to_dict()},
                                {"project", project}},
                           expect, quiet);
        } catch (const std::invalid_argument& exc) {
            return compare(
                id,
                Json{{"raise", raise_json(exc)},
                     {"project_unchanged",
                      json_eq(project, input.at("project"))}},
                expect, quiet);
        }
    }
    if (fn == "finalize_map_version_steps") {
        Json project = input.at("project");
        Json steps = Json::array();
        for (const Json& step : input.at("steps")) {
            try {
                const VersionSet vset = finalize_map_version(
                    project, step.at("map_document_id").get<std::string>(),
                    options_from(step.at("options")), deps);
                steps.push_back(Json{{"version_set", vset.to_dict()},
                                     {"project", project}});
            } catch (const std::invalid_argument& exc) {
                steps.push_back(
                    Json{{"raise", raise_json(exc)},
                         {"project_unchanged",
                          json_eq(project, input.at("project"))}});
            }
        }
        return compare(id, steps, expect.at("steps"), quiet);
    }
    if (fn == "active_final_snapshot") {
        const Json& horizon_spec = input.at("target_horizon");
        const std::string horizon =
            horizon_spec.is_string() ? horizon_spec.get<std::string>() : "";
        const auto snap =
            active_final_snapshot(input.at("project"), horizon);
        return compare(id,
                       snap.has_value() ? snap->to_dict() : Json(nullptr),
                       expect.at("snapshot"), quiet);
    }
    if (fn == "version_set_summary") {
        return compare(id, version_set_summary(input.at("project")),
                       expect.at("summary"), quiet);
    }
    if (fn == "dto_roundtrip") {
        bool all = true;
        const Json& models = input.at("models");
        for (std::size_t i = 0; i < models.size(); ++i) {
            // entries frozen as [model_name, model_dump] tuples
            const Json& model = models.at(i);
            const Json& data = model.at(1);
            const std::string name = model.at(0).get<std::string>();
            Json got;
            if (name == "VersionSet") {
                got = VersionSet::from_dict(data).to_dict();
            } else if (name == "VersionSnapshot") {
                got = VersionSnapshot::from_dict(data).to_dict();
            } else if (name == "ContourDraft") {
                got = ContourDraft::from_dict(data).to_dict();
            } else if (name == "CompilationRun") {
                got = CompilationRun::from_dict(data).to_dict();
            } else if (name == "QualityReport") {
                got = QualityReport::from_dict(data).to_dict();
            } else {
                got = Json(std::string("unknown model: ") + name);
            }
            all = compare(id + "." + name, got,
                          expect.at("dumps").at(i), quiet) &&
                  all;
        }
        return all;
    }
    if (fn == "fingerprint_bytes") {
        const std::string raw =
            pwb::workflow_runtime::versioning_fingerprint_raw_bytes(
                input.at("map_doc"));
        const bool bytes_ok =
            compare_bytes(id + ".raw", raw,
                          expect.at("raw").get<std::string>(), quiet);
        // Fixture self-consistency: the frozen fingerprint IS sha256 of
        // the frozen raw — checked here through the C++ hash path.
        const std::string fingerprint =
            pwb::domain::Sha256::of_bytes(raw).substr(0, 16);
        return compare(id + ".fingerprint", Json(fingerprint),
                       expect.at("fingerprint"), quiet) &&
               bytes_ok;
    }
    std::printf("FAIL %s: unknown fn '%s'\n", id.c_str(), fn.c_str());
    ++g_failures;
    return false;
}

// --------------------------------------------------- comparator negative run

Json& json_pointer_get(Json& root, const std::vector<std::string>& tokens) {
    Json* current = &root;
    for (const std::string& token : tokens) {
        if (current->is_array()) {
            current =
                &(*current)[static_cast<std::size_t>(std::stoul(token))];
        } else {
            current = &(*current)[token];
        }
    }
    return *current;
}

std::vector<std::string> split_pointer(const std::string& json_pointer) {
    std::vector<std::string> tokens;
    std::string rest = json_pointer;
    while (!rest.empty()) {
        const std::size_t slash = rest.find('/');
        if (slash == std::string::npos) {
            tokens.push_back(rest);
            break;
        }
        tokens.push_back(rest.substr(0, slash));
        rest = rest.substr(slash + 1);
    }
    return tokens;
}

bool negative_tamper(const Json& fixture, const std::string& case_id,
                     const std::string& json_pointer,
                     const Json& tampered_value) {
    for (const Json& cs : fixture.at("cases")) {
        if (cs.at("id").get<std::string>() != case_id) continue;
        Json mutated = cs;
        json_pointer_get(mutated.at("expect"), split_pointer(json_pointer)) =
            tampered_value;
        const bool caught =
            !dispatch(cs, mutated.at("expect"), /*quiet=*/true);
        if (!caught) {
            std::printf("FAIL negative self-check: tamper of %s at %s was "
                        "NOT caught\n",
                        case_id.c_str(), json_pointer.c_str());
            ++g_failures;
        }
        return caught;
    }
    std::printf("FAIL negative self-check: case %s not found\n",
                case_id.c_str());
    ++g_failures;
    return false;
}

// ----------------------------------------------- C++-local sink semantics --

class ThrowingSink : public VersionFinalizeSink {
public:
    void register_finalize_run(const VersionSnapshot&, const std::string&,
                               const std::string&, const std::string&) override {
        throw std::runtime_error("catalog backend down");
    }
};

class RecordingSink : public VersionFinalizeSink {
public:
    std::vector<std::string> calls;

    void register_finalize_run(const VersionSnapshot& snapshot,
                               const std::string& operator_name,
                               const std::string& note,
                               const std::string& version_set_id) override {
        calls.push_back(snapshot.id + "|" + operator_name + "|" + note +
                        "|" + version_set_id);
    }
};

const Json* find_case(const Json& fixture, const std::string& case_id) {
    for (const Json& cs : fixture.at("cases")) {
        if (cs.at("id").get<std::string>() == case_id) return &cs;
    }
    return nullptr;
}

void sink_checks(const Json& fixture) {
    const Json* happy = find_case(fixture, "finalize_happy_fresh_set");
    if (happy == nullptr) {
        std::printf("FAIL sink checks: happy case missing\n");
        ++g_failures;
        return;
    }
    const FinalizeOptions options =
        options_from(happy->at("input").at("options"));
    const std::string map_id =
        happy->at("input").at("map_document_id").get<std::string>();

    // A throwing sink must NOT fail the finalize (Python broad-except
    // L189-203) and the resulting state must be byte-identical to the
    // null-sink (get_catalog() → None) frozen expectation.
    {
        Json project = happy->at("input").at("project");
        OracleClock clock;
        clock.id_n = happy->at("clock").at("id_consumed").get<int>();
        clock.now_n = happy->at("clock").at("now_consumed").get<int>();
        FinalizeDeps deps;
        deps.clock = clock.model_clock();
        ThrowingSink sink;
        deps.finalize_sink = &sink;
        bool ok = true;
        try {
            const VersionSet vset =
                finalize_map_version(project, map_id, options, deps);
            ok = compare("sink.throwing_does_not_fail_finalize",
                         Json{{"version_set", vset.to_dict()},
                              {"project", project}},
                         happy->at("expect"), /*quiet=*/false);
        } catch (...) {
            std::printf("FAIL sink.throwing_does_not_fail_finalize: the "
                        "finalize itself failed\n");
            ++g_failures;
            ok = false;
        }
        if (ok) ++g_checks;
    }

    // A recording sink receives exactly one call with the composed
    // arguments (snapshot id | operator | note | version set id).
    {
        Json project = happy->at("input").at("project");
        OracleClock clock;
        clock.id_n = happy->at("clock").at("id_consumed").get<int>();
        clock.now_n = happy->at("clock").at("now_consumed").get<int>();
        FinalizeDeps deps;
        deps.clock = clock.model_clock();
        RecordingSink sink;
        deps.finalize_sink = &sink;
        const VersionSet sink_vset =
            finalize_map_version(project, map_id, options, deps);
        (void)sink_vset;  // the call args below are the assertion target
        const Json& frozen = happy->at("expect").at("version_set");
        const std::string expected_call =
            frozen.at("snapshots").at(0).at("id").get<std::string>() + "|" +
            options.operator_ + "|" + options.note + "|" +
            frozen.at("id").get<std::string>();
        std::string got = "count=" + std::to_string(sink.calls.size());
        if (sink.calls.size() == 1) got = sink.calls.front();
        if (compare("sink.recording_call_args", Json(got),
                    Json(expected_call), /*quiet=*/false)) {
            ++g_checks;
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]);
        return 2;
    }
    const Json fixture = read_fixture(argv[1]);

    int cases = 0;
    for (const Json& cs : fixture.at("cases")) {
        ++cases;
        ++g_checks;
        dispatch(cs, cs.at("expect"), /*quiet=*/false);
    }

    // C++-local sink-seam semantics (null ≙ no catalog is frozen above;
    // the throwing/recording behavior cannot be frozen from Python).
    sink_checks(fixture);

    int negatives = 0;
    if (negative_tamper(fixture, "finalize_happy_fresh_set",
                        "version_set/status", Json("open"))) {
        ++negatives;
    }
    if (negative_tamper(fixture, "finalize_gate_qc_failed_status",
                        "raise/message",
                        Json("质检未通过（status=passed），不能定稿"))) {
        ++negatives;
    }
    if (negative_tamper(fixture, "finalize_supersede_chain",
                        "steps/1/version_set/snapshots/0/map_document_id",
                        Json("map_tampered"))) {
        ++negatives;
    }
    if (negative_tamper(fixture, "fingerprint_bytes_rich", "raw",
                        Json("{\"facies\": [], \"horizon\": \"H1\"}"))) {
        ++negatives;
    }
    if (negative_tamper(fixture, "dto_roundtrip_models",
                        "dumps/0/finalized_at", Json("1999-01-01"))) {
        ++negatives;
    }

    if (g_failures != 0) {
        std::printf("%d/%d checks FAILED (%d fixture cases)\n", g_failures,
                    g_checks, cases);
        return 1;
    }
    std::printf("ALL %d CHECKS PASSED (+%d negative self-checks)\n", g_checks,
                negatives);
    return 0;
}
