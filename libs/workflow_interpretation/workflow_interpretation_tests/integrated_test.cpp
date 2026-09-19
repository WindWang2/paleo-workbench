// CONV-32 oracle replay: drives every frozen case in
// fixtures/workflow_interpretation_integrated_oracle.json (generated from
// the REAL Python integrated_interpretation.py + revision.py) through the
// C++ port and compares against the Python expectation. Comparison is
// dump()-string equality on ordered_json so the frozen KEY ORDER and
// int/float/bool types are enforced, not just values. The catalog seam is
// a RecordingCatalog logging the exact argument dicts of every call —
// byte-compared against the Python recording fake's log (payload transport
// is the canonical TEXT on both sides).
#include <pwb/domain/json.hpp>
#include <pwb/workflow_interpretation/integrated_interpretation.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <map>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using pwb::domain::Json;
using namespace pwb::workflow_interpretation;
using pwb::workflow_runtime::CatalogRepository;

namespace {

int g_checks = 0;
int g_failures = 0;

void check(bool ok, const std::string& id, const std::string& what) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::printf("FAIL %s: %s\n", id.c_str(), what.c_str());
    }
}

Json read_fixture(const char* path) {
    std::ifstream in(path);
    std::stringstream ss;
    ss << in.rdbuf();
    return Json::parse(ss.str());
}

// Strict parity: same value, same type (int vs float), same key order.
bool dump_equal(const Json& actual, const Json& expected) {
    return actual.dump() == expected.dump();
}

std::string first_mismatch(const Json& actual, const Json& expected) {
    if (actual.type() != expected.type()) {
        return "type " + std::to_string(static_cast<int>(actual.type())) +
               " != " + std::to_string(static_cast<int>(expected.type()));
    }
    return "actual=" + actual.dump().substr(0, 200) +
           " expected=" + expected.dump().substr(0, 200);
}

std::vector<std::string> str_array(const Json& v) {
    std::vector<std::string> out;
    if (v.is_array()) {
        for (const Json& item : v) out.push_back(item.get<std::string>());
    }
    return out;
}

// Python None serializes to JSON null — tolerant string read (null -> "").
std::string str_or_empty(const Json& v) {
    return v.is_string() ? v.get_ref<const std::string&>() : std::string();
}

std::string str_member(const Json& obj, const char* key) {
    const auto it = obj.find(key);
    return it == obj.end() ? std::string() : str_or_empty(*it);
}

// Deterministic id feed: hands out the frozen Python consumption sequence
// (create consumes first, each recorded revision consumes the next).
struct IdFeed {
    const Json* ids;
    std::size_t index = 0;

    explicit IdFeed(const Json& id_array) : ids(&id_array) {}
    std::string next() { return ids->at(index++).get<std::string>(); }
};

// ---------------------------------------------------------------- catalog

class RecordingCatalog : public CatalogRepository {
public:
    explicit RecordingCatalog(std::string fail_at)
        : fail_at_(std::move(fail_at)) {}

    [[nodiscard]] const Json& log_json() const { return log_; }

    std::vector<pwb::workflow_runtime::AssetRecord> list_assets() override {
        Json entry = Json::object();
        entry["method"] = "list_assets";
        log_.push_back(std::move(entry));
        std::vector<pwb::workflow_runtime::AssetRecord> out;
        for (const Asset& asset : assets_) {
            out.push_back(asset.record());
        }
        return out;
    }

    std::optional<pwb::workflow_runtime::AssetRecord> resolve_asset(
        const std::string&) override {
        return std::nullopt;
    }
    std::vector<pwb::workflow_runtime::VersionRecord> list_versions(
        const std::string&) override {
        return {};
    }
    std::optional<pwb::workflow_runtime::VersionRecord> resolve_version(
        const std::string&) override {
        return std::nullopt;
    }
    std::vector<pwb::workflow_runtime::RunRecord> list_runs() override {
        return {};
    }
    std::optional<pwb::workflow_runtime::RunRecord> resolve_run(
        const std::string&) override {
        return std::nullopt;
    }

    std::string register_run(
        const std::string& operation,
        const std::vector<std::string>& input_version_ids,
        const Json& parameters,
        const std::optional<std::string>& generator_version,
        const std::string& status = "running",
        const std::optional<std::string>& domain_task_id = std::nullopt,
        const std::optional<std::string>& input_snapshot_hash = std::nullopt,
        const std::optional<std::string>& actor = std::nullopt) override {
        Json entry = Json::object();
        entry["method"] = "register_run";
        entry["operation"] = operation;
        Json inputs = Json::array();
        for (const std::string& v : input_version_ids) inputs.push_back(v);
        entry["input_version_ids"] = std::move(inputs);
        entry["parameters"] = parameters;
        entry["generator"] = generator_version.value_or("");
        entry["status"] = status;
        log_.push_back(std::move(entry));
        maybe_fail("register_run");
        return next_id("run");
    }

    pwb::workflow_runtime::RegisteredAssetVersion register_result_asset(
        const std::string& name, const std::string& type,
        const std::string& format, const Json& asset_metadata,
        const std::string& payload_json, const std::string& stage,
        const std::string& run_id, const Json& version_metadata) override {
        Json entry = Json::object();
        entry["method"] = "register_result_asset";
        entry["name"] = name;
        entry["type"] = type;
        entry["format"] = format;
        entry["asset_metadata"] = asset_metadata;
        entry["payload_text"] = payload_json;
        entry["stage"] = stage;
        entry["run_id"] = run_id;
        entry["version_metadata"] = version_metadata;
        log_.push_back(std::move(entry));
        maybe_fail("register_result_asset");
        const std::string asset_id = next_id("asset");
        const std::string version_id = next_id("version");
        assets_.push_back(Asset{asset_id, name, type, version_id,
                                asset_metadata});
        log_.back()["version_id"] = version_id;
        return {asset_id, version_id};
    }

    std::string register_version(
        const std::string& asset_id, const std::string& payload_json,
        const std::string& stage,
        const std::vector<std::string>& parent_version_ids,
        const std::string& run_id, const Json& metadata) override {
        Json entry = Json::object();
        entry["method"] = "register_version";
        entry["asset_id"] = asset_id;
        entry["payload_text"] = payload_json;
        entry["stage"] = stage;
        Json parents = Json::array();
        for (const std::string& v : parent_version_ids) parents.push_back(v);
        entry["parent_version_ids"] = std::move(parents);
        entry["run_id"] = run_id;
        entry["metadata"] = metadata;
        log_.push_back(std::move(entry));
        maybe_fail("register_version");
        const std::string version_id = next_id("version");
        for (Asset& asset : assets_) {
            if (asset.id == asset_id) asset.current_version_id = version_id;
        }
        log_.back()["version_id"] = version_id;
        return version_id;
    }

    void update_run_status(const std::string& run_id,
                           const std::string& status) override {
        Json entry = Json::object();
        entry["method"] = "update_run_status";
        entry["run_id"] = run_id;
        entry["status"] = status;
        log_.push_back(std::move(entry));
    }

    void attach_run_output(const std::string&, const std::string&) override {}
    void set_current_version(const std::string&, const std::string&) override {
    }
    std::optional<std::string> verify_integrity(const std::string&) override {
        return std::nullopt;
    }

private:
    struct Asset {
        std::string id;
        std::string name;
        std::string type;
        std::string current_version_id;
        Json metadata;

        [[nodiscard]] pwb::workflow_runtime::AssetRecord record() const {
            pwb::workflow_runtime::AssetRecord out;
            out.id = id;
            out.name = name;
            out.type = type;
            out.current_version_id =
                current_version_id.empty()
                    ? std::optional<std::string>(std::nullopt)
                    : std::optional<std::string>(current_version_id);
            out.metadata = metadata;
            return out;
        }
    };

    // RuntimeStore-style sequential ids ("run_000001", zero-padded 6) —
    // identical to the Python recording fake's counters.
    std::string next_id(const char* kind) {
        char buf[32];
        std::snprintf(buf, sizeof buf, "%06lu", ++counters_[kind]);
        return std::string(kind) + "_" + buf;
    }

    void maybe_fail(const char* method) {
        if (fail_at_ == method) throw std::runtime_error("catalog down");
    }

    std::string fail_at_;
    Json log_ = Json::array();
    std::vector<Asset> assets_;
    std::map<std::string, unsigned long> counters_;
};

// ---------------------------------------------------------------- helpers

IntegratedInterpretation create_from_spec(Json& document, const Json& spec,
                                          const IntegratedIdGen& id_gen) {
    return create_integrated_interpretation(
        document, spec.at("name").get<std::string>(),
        spec.at("layer_id").get<std::string>(),
        spec.value("input_set_id", ""), spec.value("fusion_version_id", ""),
        spec.value("run_id", ""), str_array(spec.value("class_schema", Json::array())),
        spec.value("confidence_summary", Json::object()),
        spec.value("conflicts", Json::object()),
        spec.value("created_by", ""), spec.value("created_at", ""), id_gen);
}

struct CommitRun {
    Json document;
    Json log;
    std::string last_version;
    std::string raise_message;
    bool raised = false;
};

CommitRun run_commit_case(const Json& fixture_case) {
    CommitRun run;
    run.document = Json::object();
    run.document["integrated_interpretations"] = Json::array();
    run.document["interpretation_revisions"] = Json::array();

    IdFeed feed(fixture_case.at("ids"));
    // Create's seam returns the 12 hex chars ("iint_" prefixed inside);
    // revision.hpp's RevisionIdGen returns the FULL "irev_" id.
    const IntegratedIdGen create_gen = [&feed] { return feed.next(); };
    const RevisionIdGen revision_gen = [&feed] {
        return "irev_" + feed.next();
    };

    const Json& create = fixture_case.at("create");
    IntegratedInterpretation interpretation =
        create_from_spec(run.document, create, create_gen);
    if (fixture_case.value("pre_append_revision", false)) {
        // Case 22: the would-be revision id pre-appended into the stored
        // record — the domain link + commit guard must not double-append.
        run.document.at("integrated_interpretations")
            .at(0)["revision_ids"]
            .push_back("irev_" + fixture_case.at("ids").at(1).get<std::string>());
    }

    RecordingCatalog catalog(str_member(fixture_case, "fail_at"));
    for (const Json& step : fixture_case.at("commits")) {
        try {
            run.last_version = commit_integrated_interpretation(
                run.document, interpretation, step.at("layer"), &catalog,
                step.value("actor", ""), step.value("now", ""),
                str_array(step.value("evidence_refs", Json::array())),
                revision_gen);
            const std::optional<IntegratedInterpretation> fresh =
                find_by_layer(run.document,
                              create.at("layer_id").get<std::string>());
            if (fresh.has_value()) interpretation = *fresh;
        } catch (const std::exception& exc) {
            run.raised = true;
            run.raise_message = exc.what();
            break;
        }
    }
    run.log = catalog.log_json();
    return run;
}

// ---------------------------------------------------------------- replay

void replay_roundtrip(const Json& fixture_case) {
    const std::string id = fixture_case.at("id").get<std::string>();
    const IntegratedInterpretation value =
        IntegratedInterpretation::from_dict(fixture_case.at("input"));
    const Json dumped = value.to_dict();
    check(dump_equal(dumped, fixture_case.at("to_dict")), id + "/to_dict",
          "mismatch: " + first_mismatch(dumped, fixture_case.at("to_dict")));
    // "active" is always re-emitted true (from_dict ignores the stored one).
    check(dumped.at("active").is_boolean() && dumped.at("active").get<bool>(),
          id + "/active_true", "to_dict must emit active=true");
    check(dumped.size() == 20, id + "/field_count",
          "expected 19 fields + active, got " + std::to_string(dumped.size()));
    for (const Json& transition : fixture_case.at("transitions")) {
        const IntegratedInterpretation state = IntegratedInterpretation::from_dict(
            transition.at("input"));
        check(state.has_uncommitted_edits() ==
                  transition.at("has_uncommitted_edits").get<bool>(),
              id + "/transition",
              "has_uncommitted_edits mismatch for " +
                  transition.at("input").dump().substr(0, 120));
    }
}

void replay_duplicate(const Json& fixture_case) {
    const std::string id = fixture_case.at("id").get<std::string>();
    Json document = Json::object();
    document["integrated_interpretations"] = Json::array();
    document["interpretation_revisions"] = Json::array();
    IdFeed feed(fixture_case.at("ids"));
    const IntegratedIdGen create_gen = [&feed] { return feed.next(); };

    const IntegratedInterpretation created = create_from_spec(
        document, fixture_case.at("create"), create_gen);
    const Json dumped = created.to_dict();
    check(dump_equal(dumped, fixture_case.at("record")), id + "/record",
          "mismatch: " + first_mismatch(dumped, fixture_case.at("record")));
    // Id shape: iint_ + 12 lowercase hex.
    const std::regex id_pattern("iint_[0-9a-f]{12}");
    check(std::regex_match(created.interpretation_id, id_pattern),
          id + "/id_pattern",
          "interpretation_id " + created.interpretation_id);
    check(dump_equal(document.at("integrated_interpretations"),
                     fixture_case.at("records")),
          id + "/records",
          "mismatch: " + first_mismatch(document.at("integrated_interpretations"),
                                        fixture_case.at("records")));

    // Duplicate create -> IntegratedInterpretationValueError, frozen message.
    const Json& duplicate_error = fixture_case.at("duplicate_error");
    bool threw = false;
    try {
        create_from_spec(document, fixture_case.at("create"), create_gen);
    } catch (const IntegratedInterpretationValueError& exc) {
        threw = true;
        check(std::string(exc.what()) ==
                  duplicate_error.at("message").get<std::string>(),
              id + "/message", std::string(exc.what()));
    } catch (const std::exception& exc) {
        check(false, id + "/exception_type",
              std::string("wrong exception: ") + exc.what());
    }
    check(threw, id + "/throws", "duplicate create must throw");
    check(std::string(IntegratedInterpretationValueError::python_class()) ==
              duplicate_error.at("python_class").get<std::string>(),
          id + "/python_class", "python_class must be ValueError");
    // Subclass relationship: catchable as std::runtime_error (Python
    // ValueError heritage is a plain Exception; the C++ seam maps it onto
    // the standard runtime error hierarchy).
    bool caught_runtime = false;
    try {
        create_from_spec(document, fixture_case.at("create"), create_gen);
    } catch (const std::runtime_error&) {
        caught_runtime = true;
    } catch (...) {
    }
    check(caught_runtime, id + "/runtime_subclass",
          "IntegratedInterpretationValueError must subclass std::runtime_error");
}

void replay_guardrails(const Json& fixture_case) {
    const std::string id = fixture_case.at("id").get<std::string>();
    Json document = Json::object();
    document["integrated_interpretations"] = Json::array();
    document["interpretation_revisions"] = Json::array();
    IdFeed feed(fixture_case.at("ids"));
    const IntegratedIdGen create_gen = [&feed] { return feed.next(); };
    const IntegratedInterpretation interpretation = create_from_spec(
        document, fixture_case.at("create"), create_gen);

    // Null catalog -> honest ValueError, nothing registered.
    const Json& null_error = fixture_case.at("null_catalog_error");
    try {
        const std::string ignored = commit_integrated_interpretation(
            document, interpretation, Json::object(), nullptr);
        (void)ignored;
        check(false, id + "/null_catalog", "must throw on null catalog");
    } catch (const IntegratedInterpretationValueError& exc) {
        check(std::string(exc.what()) == null_error.at("message").get<std::string>(),
              id + "/null_catalog_message", std::string(exc.what()));
        check(std::string(IntegratedInterpretationValueError::python_class()) ==
                  null_error.at("python_class").get<std::string>(),
              id + "/null_catalog_class", "python_class");
    }

    // Empty geometry -> refusal (catalog present, features empty).
    const Json& empty_error = fixture_case.at("empty_features_error");
    RecordingCatalog catalog("");
    Json empty_layer = Json::object();
    empty_layer["features"] = Json::array();
    try {
        const std::string ignored = commit_integrated_interpretation(
            document, interpretation, empty_layer, &catalog);
        (void)ignored;
        check(false, id + "/empty_features", "must throw on empty geometry");
    } catch (const IntegratedInterpretationValueError& exc) {
        check(std::string(exc.what()) ==
                  empty_error.at("message").get<std::string>(),
              id + "/empty_features_message", std::string(exc.what()));
    }
    // Missing "features" key entirely -> same refusal.
    const Json& missing_error = fixture_case.at("missing_features_error");
    try {
        const std::string ignored = commit_integrated_interpretation(
            document, interpretation, Json::object(), &catalog);
        (void)ignored;
        check(false, id + "/missing_features", "must throw without features");
    } catch (const IntegratedInterpretationValueError& exc) {
        check(std::string(exc.what()) ==
                  missing_error.at("message").get<std::string>(),
              id + "/missing_features_message", std::string(exc.what()));
    }
    // NO state mutated by any guardrail: document matches the frozen
    // post-create arrays, catalog untouched.
    check(catalog.log_json().empty(), id + "/no_catalog_calls",
          "guardrails must not touch the catalog");
    check(dump_equal(document.at("integrated_interpretations"),
                     fixture_case.at("records")),
          id + "/records",
          "mismatch: " +
              first_mismatch(document.at("integrated_interpretations"),
                             fixture_case.at("records")));
    check(dump_equal(document.at("interpretation_revisions"),
                     fixture_case.at("revisions")),
          id + "/revisions", "guardrails must not record revisions");
}

void replay_commit_case(const Json& fixture_case) {
    const std::string id = fixture_case.at("id").get<std::string>();
    const Json& expect = fixture_case.at("expect");
    const CommitRun run = run_commit_case(fixture_case);

    check(dump_equal(run.log, expect.at("log")), id + "/log",
          "mismatch: " + first_mismatch(run.log, expect.at("log")));
    check(dump_equal(run.document.at("integrated_interpretations"),
                     expect.at("final_interpretations")),
          id + "/final_interpretations",
          "mismatch: " +
              first_mismatch(run.document.at("integrated_interpretations"),
                             expect.at("final_interpretations")));
    check(dump_equal(run.document.at("interpretation_revisions"),
                     expect.at("final_revisions")),
          id + "/final_revisions",
          "mismatch: " +
              first_mismatch(run.document.at("interpretation_revisions"),
                             expect.at("final_revisions")));
    check(run.last_version == expect.at("last_version_id").get<std::string>(),
          id + "/version_id",
          "got " + run.last_version + " want " +
              expect.at("last_version_id").get<std::string>());

    if (expect.at("raise").is_null()) {
        check(!run.raised, id + "/no_raise", "unexpected exception");
        if (expect.contains("final_summary")) {
            const Json summary = interpretation_summary(
                run.document,
                fixture_case.at("create").at("layer_id").get<std::string>());
            check(dump_equal(summary, expect.at("final_summary")),
                  id + "/final_summary",
                  "mismatch: " +
                      first_mismatch(summary, expect.at("final_summary")));
            // last_committed anchor pinned to the chain tail after commit.
            const Json& record =
                run.document.at("integrated_interpretations").at(0);
            if (!record.at("revision_ids").empty()) {
                check(record.at("last_committed_revision_id") ==
                          record.at("revision_ids").back(),
                      id + "/anchor_at_tail",
                      "last_committed_revision_id must equal revision_ids[-1]");
            }
        }
    } else {
        check(run.raised, id + "/raises", "repository failure must propagate");
        check(run.raise_message == expect.at("raise").at("message").get<std::string>(),
              id + "/raise_message", "got " + run.raise_message);
        check(expect.at("raise").at("python_class").get<std::string>() ==
                  "RuntimeError",
              id + "/raise_class", "frozen class must be RuntimeError");
        check(run.document.at("integrated_interpretations")
                      .at(0)
                      .at("committed_version_id")
                      .get<std::string>()
                      .empty(),
              id + "/no_fake_commit",
              "failed commit must not write committed_version_id");
    }
}

void replay_summary_missing(const Json& fixture_case) {
    Json document = Json::object();
    document["integrated_interpretations"] = Json::array();
    document["interpretation_revisions"] = Json::array();
    const Json summary = interpretation_summary(
        document, fixture_case.at("layer_id").get<std::string>());
    check(dump_equal(summary, fixture_case.at("expect")),
          "summary_missing/exact",
          "mismatch: " + first_mismatch(summary, fixture_case.at("expect")));
}

// C++-side seam spot-checks (case 21 substitute — no Python freeze needed).
void seam_checks() {
    const std::regex hex12("[0-9a-f]{12}");
    const std::string generated = default_integrated_id_gen()();
    check(std::regex_match(generated, hex12), "seam/default_id_gen",
          "default id gen must emit 12 lowercase hex, got " + generated);

    check(std::string(OPERATION_INTEGRATED_INTERPRETATION) ==
              "integrated_interpretation" &&
              std::string(ASSET_TYPE_INTEGRATED_INTERPRETATION) ==
                  "integrated_interpretation",
          "seam/constants", "operation/asset type vocabulary");
    check(std::string(FUSION_CONFLICT_KEYS[0]) == "low_confidence_fraction" &&
              std::string(FUSION_CONFLICT_KEYS[1]) ==
                  "mean_conflict_fraction" &&
              std::string(FUSION_CONFLICT_KEYS[2]) ==
                  "high_conflict_fraction" &&
              std::string(FUSION_CONFLICT_KEYS[3]) == "low_margin_fraction",
          "seam/fusion_conflict_keys", "FUSION_CONFLICT_KEYS order");
    check(std::string(MATURITY_DRAFT) == "draft" &&
              std::string(MATURITY_REVIEWED) == "reviewed" &&
              std::string(MATURITY_FROZEN) == "frozen" &&
              std::string(MATURITY_PUBLISHED) == "published" &&
              std::string(MATURITY_SUPERSEDED) == "superseded",
          "seam/maturity_ladder", "maturity constants");

    // Empty-features commit guard fires before any catalog interaction and
    // the upsert seam is replace-or-append (public domain-link contract).
    Json document = Json::object();
    document["integrated_interpretations"] = Json::array();
    document["interpretation_revisions"] = Json::array();
    IdFeed feed(Json::array());
    (void)feed;
    const IntegratedInterpretation created = create_integrated_interpretation(
        document, "x", "LX", "ciset", "ver_f", "run_1", {"a", "b"},
        Json::object(), Json::object(), "u", "t",
        [] { return std::string("abcdef012345"); });
    check(created.interpretation_id == "iint_abcdef012345" &&
              created.has_uncommitted_edits() == false &&
              created.latest_fusion_version_id.empty(),
          "seam/create_defaults",
          "created record defaults (id prefix, no uncommitted edits, empty "
          "latest_fusion_version_id)");
    upsert_interpretation(document, created);
    check(document.at("integrated_interpretations").size() == 1,
          "seam/upsert_idempotent", "upsert of the same id must replace");
}

// Tamper copies of frozen expectations — the checker MUST reject them
// (guards against comparisons that silently pass everything).
int negative_self_checks(const Json& fixture) {
    int negatives = 0;
    auto expect_inequality = [&](bool equal, const std::string& what) {
        ++negatives;
        if (equal) {
            ++g_failures;
            std::printf("FAIL negative/%s\n", what.c_str());
        }
    };

    const Json& first = fixture.at("commit_cases").at(0);

    // 1 — tamper the canonical payload text (0.25 -> 0.26): the C++ port
    // must produce the frozen bytes, not the tampered ones.
    std::string frozen_payload;
    for (const Json& entry : first.at("expect").at("log")) {
        if (entry.at("method") == "register_result_asset") {
            frozen_payload = entry.at("payload_text").get<std::string>();
            break;
        }
    }
    const IntegratedInterpretation interp =
        IntegratedInterpretation::from_dict(
            first.at("expect").at("final_interpretations").at(0));
    const std::string actual_payload = python_dumps_sorted(
        layer_payload(interp, first.at("commits").at(0).at("layer")));
    expect_inequality(actual_payload != frozen_payload, "payload_must_match");
    std::string tampered = frozen_payload;
    const std::size_t pos = tampered.find("0.25");
    tampered.replace(pos, 4, "0.26");
    expect_inequality(actual_payload == tampered, "tampered_payload");

    // 2 — tamper the missing summary detail -> must not equal.
    Json tampered_summary = fixture.at("summary_missing").at("expect");
    tampered_summary["detail"] = "被篡改";
    Json document = Json::object();
    document["integrated_interpretations"] = Json::array();
    document["interpretation_revisions"] = Json::array();
    expect_inequality(
        dump_equal(interpretation_summary(document, "nope"), tampered_summary),
        "tampered_summary_detail");

    // 3 — tamper committed_version_id in the frozen record -> replay doc
    // must differ.
    const CommitRun rerun = run_commit_case(first);
    Json tampered_records = first.at("expect").at("final_interpretations");
    tampered_records[0]["committed_version_id"] = "ver_999999";
    expect_inequality(
        dump_equal(rerun.document.at("integrated_interpretations"),
                   tampered_records),
        "tampered_committed_version");

    // 4 — tamper register_run parameters (n_features) -> replay log differs.
    Json tampered_log = first.at("expect").at("log");
    for (Json& entry : tampered_log) {
        if (entry.at("method") == "register_run") {
            entry["parameters"]["n_features"] = 99;
        }
    }
    expect_inequality(dump_equal(rerun.log, tampered_log),
                      "tampered_n_features");

    return negatives;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]);
        return 2;
    }
    const Json fixture = read_fixture(argv[1]);
    replay_roundtrip(fixture.at("roundtrip"));
    replay_duplicate(fixture.at("duplicate_create"));
    replay_guardrails(fixture.at("guardrails"));
    for (const Json& fixture_case : fixture.at("commit_cases")) {
        replay_commit_case(fixture_case);
    }
    replay_summary_missing(fixture.at("summary_missing"));
    seam_checks();
    const int negatives = negative_self_checks(fixture);

    if (g_failures != 0) {
        std::printf("%d FAILURES (of %d checks)\n", g_failures, g_checks);
        return 1;
    }
    std::printf("ALL %d CHECKS PASSED (+%d negative self-checks)\n", g_checks,
                negatives);
    return 0;
}
