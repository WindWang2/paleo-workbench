// CONV-32 oracle replay (I6): drives every frozen case in
// fixtures/workflow_interpretation_constraint_oracle.json (generated from
// the REAL Python constraint_product.py / revision.py through the real
// constraint_versions commit chain) through the C++ port and compares
// against the Python expectation. Comparison is dump()-string equality on
// ordered_json so the frozen KEY ORDER and int/float/bool types are
// enforced, not just values. Catalog version ids are uuid-based on the
// Python side and are frozen as null sentinels (checked non-empty here);
// everything else is byte-exact.
#include <pwb/domain/json.hpp>
#include <pwb/workflow_interpretation/constraint_product.hpp>
#include <pwb/workflow_interpretation/revision.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/constraint_versions.hpp>

#include <cstdio>
#include <fstream>
#include <map>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using pwb::domain::Json;
using namespace pwb::workflow_interpretation;
using pwb::workflow_runtime::CatalogRepository;
using pwb::workflow_runtime::RuntimeStore;

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

std::optional<std::string> optional_string(const Json& value) {
    if (value.is_null()) return std::nullopt;
    return value.get<std::string>();
}

// ---------------------------------------------------------------- kinds ----

void replay_kind_entry(const std::string& scope, const Json& entry) {
    const std::string input = entry.at("input").get<std::string>();
    const std::string id = scope + "/" + entry.at("id").get<std::string>();
    const auto resolved = constraint_kind_from_value(input);
    check((resolved.has_value() == entry.at("resolved_kind").is_string()) &&
              (!resolved.has_value() ||
               *resolved == entry.at("resolved_kind").get<std::string>()),
          id + "/resolved_kind", "constraint_kind_from_value mismatch");
    const auto engine = to_engine_kind(input);
    check((engine.has_value() == entry.at("engine_kind").is_string()) &&
              (!engine.has_value() ||
               *engine == entry.at("engine_kind").get<std::string>()),
          id + "/engine_kind", "to_engine_kind mismatch");
}

void replay_kind_cases(const Json& fixture) {
    for (const Json& entry : fixture.at("kind_cases")) {
        if (entry.contains("inputs")) {
            for (const Json& sub : entry.at("inputs")) {
                replay_kind_entry(entry.at("id").get<std::string>(), sub);
            }
            continue;
        }
        replay_kind_entry("kind_cases", entry);
    }
}

// ------------------------------------------------------------------ CRS ----

void replay_crs_cases(const Json& fixture) {
    for (const Json& entry : fixture.at("crs_cases")) {
        const std::string id =
            "crs/" + entry.at("id").get<std::string>();
        const auto factor = optional_string(entry.at("factor_crs"));
        const auto constraint = optional_string(entry.at("constraint_crs"));
        const std::string context =
            entry.value("context", std::string(""));
        try {
            const std::string note = assert_constraints_crs_compatible(
                factor, constraint, context);
            check(entry.at("error").is_null(), id + "/no_error",
                  "expected ConstraintCrsError, got note: " + note);
            check(note == entry.at("note").get<std::string>(), id + "/note",
                  "note mismatch: actual='" + note + "' expected='" +
                      entry.at("note").get<std::string>() + "'");
        } catch (const ConstraintCrsError& error) {
            check(!entry.at("error").is_null(), id + "/error",
                  "unexpected ConstraintCrsError: " + std::string(error.what()));
            if (!entry.at("error").is_null()) {
                check(std::string(error.what()) ==
                          entry.at("error").get<std::string>(),
                      id + "/error_message",
                      "message mismatch: actual='" +
                          std::string(error.what()) + "'");
            }
            check(std::string(error.python_class()) == "ValueError",
                  id + "/python_class", "python_class must be ValueError");
        }
    }
}

// -------------------------------------------------------------- products ---

struct CatalogSetup {
    std::unique_ptr<RuntimeStore> store;
    CatalogRepository* repository = nullptr;
};

CatalogSetup make_catalog(const Json& case_data, const Json& group_committed) {
    CatalogSetup setup;
    const Json& catalog = case_data.at("catalog");
    if (catalog.is_null()) return setup;
    const std::string kind = catalog.at("kind").get<std::string>();
    setup.store = std::make_unique<RuntimeStore>();
    if (kind == "commit") {
        const auto report = pwb::workflow_runtime::commit_constraint_group(
            *setup.store, group_committed,
            case_data.value("commit_actor", std::string("")),
            case_data.value("commit_notes", std::string("")));
        check(report.committed && report.reason == "changed",
              case_data.at("id").get<std::string>() + "/commit",
              "commit_constraint_group did not create a version");
    }
    setup.repository = setup.store.get();
    return setup;
}

void expect_product(const std::string& id, const ConstraintProduct& product,
                    const Json& expect_in) {
    Json expect = expect_in;  // copy: null sentinel -> actual value
    if (expect.at("committed_version_id").is_null()) {
        check(!product.committed_version_id.empty(),
              id + "/committed_version_id", "expected a non-empty version id");
        expect["committed_version_id"] = product.committed_version_id;
    }
    check(dump_equal(product.to_dict(), expect), id + "/product",
          "product mismatch: " + first_mismatch(product.to_dict(), expect));
}

void replay_product_cases(const Json& fixture) {
    for (const Json& case_data : fixture.at("product_cases")) {
        const std::string id =
            "product/" + case_data.at("id").get<std::string>();
        CatalogSetup setup =
            make_catalog(case_data, case_data.contains("group_committed")
                                       ? case_data.at("group_committed")
                                       : case_data.at("group"));
        const ConstraintProduct product = constraint_product_for_group(
            case_data.at("document"), case_data.at("group"),
            setup.repository);
        expect_product(id, product, case_data.at("expect"));
        check(product.has_uncommitted_edits() ==
                  case_data.at("has_uncommitted").get<bool>(),
              id + "/has_uncommitted", "has_uncommitted_edits mismatch");

        // Document variant: one product per constraint_layers entry.
        const std::vector<ConstraintProduct> products =
            constraint_products_for_document(case_data.at("document"),
                                             setup.repository);
        check(static_cast<int>(products.size()) ==
                  case_data.at("document_products_len").get<int>(),
              id + "/document_len", "document product count mismatch");
        if (products.size() == 1) {
            expect_product(id + "/document", products.front(),
                           case_data.at("expect"));
        }
    }
}

// -------------------------------------------------------------- revision ---

std::vector<std::string> string_array(const Json& value) {
    std::vector<std::string> out;
    if (value.is_array()) {
        for (const Json& item : value) out.push_back(item.get<std::string>());
    }
    return out;
}

RevisionIdGen id_gen_from(const Json& ids) {
    auto queue = std::make_shared<std::vector<std::string>>(
        string_array(ids));
    auto index = std::make_shared<std::size_t>(0);
    return [queue, index]() { return (*queue)[(*index)++]; };
}

void replay_call(Json& document, const Json& call, const Json& layer,
                 const std::string& scope, const Json& expect_result,
                 const RevisionIdGen& id_gen) {
    const std::vector<std::string> evidence =
        string_array(call.value("evidence_refs", Json::array()));
    const auto result = record_interpretation_revision(
        document, call.at("target_kind").get<std::string>(),
        call.at("target_layer_id").get<std::string>(), layer,
        call.value("actor", std::string("")),
        call.value("now", std::string("")),
        call.value("interpretation_id", std::string("")),
        call.value("base_kind", std::string(BASE_MANUAL)),
        call.value("base_version_id", std::string("")), evidence,
        call.value("note", std::string("")), id_gen);
    if (expect_result.is_null()) {
        check(!result.has_value(), scope + "/unchanged",
              "unchanged content must record no revision");
        return;
    }
    check(result.has_value(), scope + "/recorded",
          "expected a revision, got nullopt");
    if (!result.has_value()) return;
    check(dump_equal(result->to_dict(), expect_result), scope + "/revision",
          "revision mismatch: " + first_mismatch(result->to_dict(),
                                                 expect_result));
}

void replay_revision_chain(const Json& fixture) {
    const Json& chain = fixture.at("revision_chain");
    const std::string scope = "revision_chain";
    Json document = chain.at("document_in");  // mutable copy
    const RevisionIdGen id_gen = id_gen_from(chain.at("ids"));
    int i = 0;
    for (const Json& call : chain.at("calls")) {
        const Json& layer = call.at("layer").get<std::string>() == "after"
                                ? chain.at("layer_after")
                                : chain.at("layer_before");
        replay_call(document, call, layer, scope + "/" + std::to_string(i),
                    chain.at("expect_results").at(i), id_gen);
        ++i;
    }
    check(dump_equal(document.at("interpretation_revisions"),
                     chain.at("expect_document").at("interpretation_revisions")),
          scope + "/document",
          "document interpretation_revisions mismatch: " +
              first_mismatch(document.at("interpretation_revisions"),
                             chain.at("expect_document").at(
                                 "interpretation_revisions")));
    const std::vector<InterpretationRevision> revisions =
        revisions_for_layer(document, "L1");
    check(revisions.size() == chain.at("chain_ids").size(),
          scope + "/chain_size", "chain length mismatch");
    for (std::size_t k = 0;
         k < revisions.size() && k < chain.at("chain_ids").size(); ++k) {
        check(revisions[k].revision_id ==
                  chain.at("chain_ids").at(k).get<std::string>(),
              scope + "/chain_order", "chain order mismatch at " +
                                          std::to_string(k));
    }
    const auto latest = latest_revision_for_layer(document, "L1");
    check(latest.has_value() &&
              latest->revision_id == chain.at("latest_id").get<std::string>(),
          scope + "/latest", "latest revision mismatch");
}

void replay_integrated_link(const Json& fixture) {
    const Json& link = fixture.at("integrated_link");
    const std::string scope = "integrated_link";
    Json document = link.at("document_in");  // mutable copy
    const RevisionIdGen id_gen = id_gen_from(link.at("ids"));
    int i = 0;
    for (const Json& call : link.at("calls")) {
        const Json& layer =
            link.at("layers").at(call.at("layer").get<std::string>());
        replay_call(document, call, layer, scope + "/" + std::to_string(i),
                    link.at("expect_results").at(i), id_gen);
        ++i;
    }
    check(dump_equal(document.at("integrated_interpretations"),
                     link.at("expect_document").at("integrated_interpretations")),
          scope + "/interpretations",
          "integrated_interpretations mismatch: " +
              first_mismatch(document.at("integrated_interpretations"),
                             link.at("expect_document").at(
                                 "integrated_interpretations")));
    check(dump_equal(document.at("interpretation_revisions"),
                     link.at("expect_document").at("interpretation_revisions")),
          scope + "/revisions",
          "interpretation_revisions mismatch: " +
              first_mismatch(document.at("interpretation_revisions"),
                             link.at("expect_document").at(
                                 "interpretation_revisions")));
}

void replay_fingerprint_cases(const Json& fixture) {
    std::map<std::string, LayerFingerprint> computed;
    for (const Json& case_data : fixture.at("fingerprint_cases")) {
        const std::string id =
            "fingerprint/" + case_data.at("id").get<std::string>();
        const LayerFingerprint fp =
            layer_content_fingerprint(case_data.at("layer"));
        const Json& expect = case_data.at("expect");
        computed[case_data.at("id").get<std::string>()] = fp;
        check(fp.digest == expect.at("digest").get<std::string>(),
              id + "/digest", "digest mismatch");
        check(fp.features == expect.at("features").get<long long>(),
              id + "/features", "feature count mismatch");
        check(fp.vertices == expect.at("vertices").get<long long>(),
              id + "/vertices", "vertex count mismatch");
        if (!case_data.at("equal_to").is_null()) {
            const std::string other =
                case_data.at("equal_to").get<std::string>();
            const auto it = computed.find(other);
            check(it != computed.end() && it->second.digest == fp.digest,
                  id + "/equal_to", "digest must equal case " + other);
        }
    }
}

void replay_from_dict_cases(const Json& fixture) {
    for (const Json& case_data : fixture.at("from_dict_cases")) {
        const std::string id =
            "from_dict/" + case_data.at("id").get<std::string>();
        const InterpretationRevision revision =
            InterpretationRevision::from_dict(case_data.at("input"));
        check(dump_equal(revision.to_dict(), case_data.at("expect")), id,
              "roundtrip mismatch: " +
                  first_mismatch(revision.to_dict(), case_data.at("expect")));
    }
}

void replay_summary_cases(const Json& fixture) {
    for (const Json& case_data : fixture.at("summary_cases")) {
        const std::string id =
            "summary/" + case_data.at("id").get<std::string>();
        const Json summary = revision_summary(
            case_data.at("document"),
            case_data.at("layer_id").get<std::string>());
        check(dump_equal(summary, case_data.at("expect")), id,
              "summary mismatch: " +
                  first_mismatch(summary, case_data.at("expect")));
    }
}

// Tamper copies of frozen expectations — the checker MUST reject them
// (guards against a comparison that silently passes everything).
int negative_self_checks(const Json& fixture) {
    int negatives = 0;
    auto expect_inequality = [&](bool equal, const std::string& what) {
        ++negatives;
        if (equal) {
            ++g_failures;
            std::printf("FAIL negative/%s\n", what.c_str());
        }
    };

    // 1 — tamper a projected line row (n_points 5 -> 4).
    const Json& product_cases = fixture.at("product_cases");
    const Json* no_catalog = nullptr;
    for (const Json& case_data : product_cases) {
        if (case_data.at("id").get<std::string>() == "projection_no_catalog") {
            no_catalog = &case_data;
        }
    }
    check(no_catalog != nullptr, "negative/case_lookup",
          "projection_no_catalog case missing from fixture");
    if (no_catalog != nullptr) {
        Json tampered = no_catalog->at("expect");
        tampered["lines"][1]["n_points"] = 4;
        const ConstraintProduct product = constraint_product_for_group(
            no_catalog->at("document"), no_catalog->at("group"));
        expect_inequality(dump_equal(product.to_dict(), tampered),
                          "tampered_n_points");
    }

    // 2 — tamper a frozen fingerprint digest (flip the last hex nibble).
    for (const Json& case_data : fixture.at("fingerprint_cases")) {
        if (case_data.at("id").get<std::string>() != "stability_layer_a") {
            continue;
        }
        Json tampered_digest = case_data.at("expect");
        std::string digest = tampered_digest.at("digest").get<std::string>();
        digest.back() = digest.back() == 'a' ? 'b' : 'a';
        tampered_digest["digest"] = digest;
        const LayerFingerprint fp =
            layer_content_fingerprint(case_data.at("layer"));
        expect_inequality(
            fp.digest == tampered_digest.at("digest").get<std::string>(),
            "tampered_digest");
    }

    // 3 — tamper the frozen CRS error message (byte-exactness guard).
    for (const Json& case_data : fixture.at("crs_cases")) {
        if (case_data.at("id").get<std::string>() != "mismatch") continue;
        const std::string frozen =
            case_data.at("error").get<std::string>();
        const std::string tampered_message = frozen + " ";
        try {
            (void)assert_constraints_crs_compatible("EPSG:32650",
                                                    "EPSG:4326");
            expect_inequality(true, "tampered_crs_no_throw");
        } catch (const ConstraintCrsError& error) {
            expect_inequality(std::string(error.what()) == tampered_message,
                              "tampered_crs_message");
        }
    }

    // 4 — tamper a revision delta (features + 1): replaying the same chain
    // must not match the tampered copy.
    const Json& chain = fixture.at("revision_chain");
    Json tampered_delta = chain.at("expect_results").at(2);
    tampered_delta["delta"]["features"] =
        tampered_delta.at("delta").at("features").get<int>() + 1;
    Json document = chain.at("document_in");
    const RevisionIdGen ids = id_gen_from(chain.at("ids"));
    const Json& call_one = chain.at("calls").at(0);
    (void)record_interpretation_revision(
        document, call_one.at("target_kind").get<std::string>(),
        call_one.at("target_layer_id").get<std::string>(),
        chain.at("layer_before"), call_one.value("actor", std::string()),
        call_one.value("now", std::string()), "",
        call_one.value("base_kind", std::string(BASE_MANUAL)),
        call_one.value("base_version_id", std::string()),
        string_array(call_one.value("evidence_refs", Json::array())),
        call_one.value("note", std::string()), ids);
    const Json& call_two = chain.at("calls").at(2);
    const auto second = record_interpretation_revision(
        document, call_two.at("target_kind").get<std::string>(),
        call_two.at("target_layer_id").get<std::string>(),
        chain.at("layer_after"), call_two.value("actor", std::string()),
        call_two.value("now", std::string()), "",
        call_two.value("base_kind", std::string(BASE_MANUAL)),
        call_two.value("base_version_id", std::string()),
        string_array(call_two.value("evidence_refs", Json::array())),
        call_two.value("note", std::string()), ids);
    check(second.has_value(), "negative/second_recorded",
          "second revision must record");
    if (second.has_value()) {
        expect_inequality(dump_equal(second->to_dict(), tampered_delta),
                          "tampered_delta");
    }
    return negatives;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]);
        return 2;
    }
    const Json fixture = read_fixture(argv[1]);
    replay_kind_cases(fixture);
    replay_crs_cases(fixture);
    replay_product_cases(fixture);
    replay_revision_chain(fixture);
    replay_fingerprint_cases(fixture);
    replay_from_dict_cases(fixture);
    replay_summary_cases(fixture);
    replay_integrated_link(fixture);
    const int negatives = negative_self_checks(fixture);

    if (g_failures != 0) {
        std::printf("%d FAILURES (of %d checks)\n", g_failures, g_checks);
        return 1;
    }
    std::printf("ALL %d CHECKS PASSED (+%d negative self-checks)\n", g_checks,
                negatives);
    return 0;
}
