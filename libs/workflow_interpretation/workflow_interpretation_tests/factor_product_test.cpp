// CONV-32 oracle replay: drives every frozen case in
// fixtures/workflow_interpretation_factor_oracle.json (generated from the
// REAL Python factor_product.py / summaries.py) through the C++ port and
// compares against the Python expectation. Comparison is dump()-string
// equality on ordered_json so the frozen KEY ORDER and int/float/bool types
// are enforced, not just values.
#include <pwb/domain/json.hpp>
#include <pwb/workflow_interpretation/factor_product.hpp>
#include <pwb/workflow_interpretation/summaries.hpp>

#include <cstdio>
#include <fstream>
#include <map>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using pwb::domain::Json;
using namespace pwb::workflow_interpretation;

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

CatalogResolver make_resolver(const Json& spec) {
    if (!spec.is_object()) return {};
    std::map<std::string, std::string> versions;
    if (spec.contains("versions")) {
        for (auto it = spec.at("versions").begin();
             it != spec.at("versions").end(); ++it) {
            versions[it.key()] = it.value().at("run_id").get<std::string>();
        }
    }
    std::map<std::string, std::vector<std::string>> runs;
    if (spec.contains("runs")) {
        for (auto it = spec.at("runs").begin(); it != spec.at("runs").end();
             ++it) {
            std::vector<std::string> inputs;
            for (const Json& v : it.value().at("input_version_ids")) {
                inputs.push_back(v.get<std::string>());
            }
            runs[it.key()] = std::move(inputs);
        }
    }
    std::vector<std::string> raise_versions;
    for (const Json& v : spec.value("raise_versions", Json::array())) {
        raise_versions.push_back(v.get<std::string>());
    }
    std::vector<std::string> raise_runs;
    for (const Json& v : spec.value("raise_runs", Json::array())) {
        raise_runs.push_back(v.get<std::string>());
    }
    CatalogResolver resolver;
    resolver.resolve_version =
        [versions = std::move(versions),
         raise_versions = std::move(raise_versions)](
            const std::string& version_id)
        -> std::optional<VersionRunInfo> {
            for (const std::string& v : raise_versions) {
                if (v == version_id) {
                    throw std::runtime_error("catalog unavailable: " + v);
                }
            }
            const auto it = versions.find(version_id);
            if (it == versions.end()) return std::nullopt;
            return VersionRunInfo{it->second};
        };
    resolver.resolve_run =
        [runs = std::move(runs), raise_runs = std::move(raise_runs)](
            const std::string& run_id) -> std::optional<RunInfo> {
            for (const std::string& v : raise_runs) {
                if (v == run_id) {
                    throw std::runtime_error("catalog unavailable: " + v);
                }
            }
            const auto it = runs.find(run_id);
            if (it == runs.end()) return std::nullopt;
            return RunInfo{it->second};
        };
    return resolver;
}

WorkspaceView make_workspace(const Json& spec) {
    if (!spec.is_object()) return {};  // workspace_state=None -> draft default
    std::map<std::string, std::string> maturity;
    for (auto it = spec.begin(); it != spec.end(); ++it) {
        maturity[it.key()] = it.value().get<std::string>();
    }
    WorkspaceView view;
    view.maturity_of =
        [maturity = std::move(maturity)](const std::string& artifact_key) {
            const auto it = maturity.find(artifact_key);
            return it == maturity.end() ? std::string("draft") : it->second;
        };
    return view;
}

std::map<std::string, FreshnessEntry> make_freshness(const Json& spec) {
    std::map<std::string, FreshnessEntry> out;
    if (spec.is_object()) {
        for (auto it = spec.begin(); it != spec.end(); ++it) {
            out[it.key()] = FreshnessEntry{
                it.value().at("status").get<std::string>(),
                it.value().at("detail").get<std::string>()};
        }
    }
    return out;
}

void replay_factor_case(const Json& fixture_case) {
    const std::string id = fixture_case.at("id").get<std::string>();
    const Json tasks = fixture_case.at("tasks");
    const CatalogResolver resolver = make_resolver(fixture_case.at("resolver"));
    const WorkspaceView workspace = make_workspace(fixture_case.at("workspace"));
    const std::map<std::string, FreshnessEntry> freshness =
        make_freshness(fixture_case.at("freshness"));

    // Products (task missing -> null expectation).
    const Json& products = fixture_case.at("checks").at("products");
    for (auto it = products.begin(); it != products.end(); ++it) {
        const std::string& task_id = it.key();
        const auto fresh_it = freshness.find(task_id);
        const std::optional<FactorProduct> product = factor_product_for_task(
            tasks, task_id, resolver, workspace,
            fresh_it == freshness.end()
                ? std::nullopt
                : std::optional<FreshnessEntry>(fresh_it->second));
        if (it.value().is_null()) {
            check(!product.has_value(), id + "/product/" + task_id,
                  "expected nullopt (missing task)");
            continue;
        }
        check(product.has_value(), id + "/product/" + task_id,
              "expected a product, got nullopt");
        if (!product.has_value()) continue;
        check(dump_equal(product->to_json(), it.value()),
              id + "/product/" + task_id,
              "product mismatch: " +
                  first_mismatch(product->to_json(), it.value()));
        // Miss-path accessor contract (never silently blank).
        const FactorArtifactRef miss = product->artifact("bogus_kind");
        check(!miss.present && miss.version_id.empty() &&
                  miss.absent_reason == "not part of this product",
              id + "/artifact_miss/" + task_id, "artifact(kind) miss contract");
    }

    // Summaries: projected-product path always; compose helper when the case
    // carries no freshness entry for the task.
    const Json& summaries = fixture_case.at("checks").at("summaries");
    for (auto it = summaries.begin(); it != summaries.end(); ++it) {
        const std::string& task_id = it.key();
        const auto fresh_it = freshness.find(task_id);
        const std::optional<FactorProduct> product = factor_product_for_task(
            tasks, task_id, resolver, workspace,
            fresh_it == freshness.end()
                ? std::nullopt
                : std::optional<FreshnessEntry>(fresh_it->second));
        const FactorSummary direct =
            factor_summary(product.has_value() ? &*product : nullptr);
        check(dump_equal(direct.to_display_dict(), it.value()),
              id + "/summary/" + task_id,
              "summary mismatch: " +
                  first_mismatch(direct.to_display_dict(), it.value()));
        if (fresh_it == freshness.end()) {
            const FactorSummary composed = factor_summary_for_task(
                tasks, task_id, resolver, workspace);
            check(dump_equal(composed.to_display_dict(), it.value()),
                  id + "/summary_for_task/" + task_id,
                  "compose mismatch: " +
                      first_mismatch(composed.to_display_dict(), it.value()));
        }
    }

    // Batch projection (factor_products with the precomputed freshness map —
    // the fixture freezes what Python's internal dependency-service
    // evaluation produced for this exact document/catalog/workspace).
    if (fixture_case.contains("batch_products")) {
        const std::map<std::string, FreshnessEntry> batch_freshness =
            make_freshness(fixture_case.value("batch_freshness", Json(nullptr)));
        const std::vector<FactorProduct> batch =
            factor_products(tasks, batch_freshness, resolver, workspace);
        const Json& expected = fixture_case.at("batch_products");
        check(batch.size() == expected.size(), id + "/batch/size",
              "batch size " + std::to_string(batch.size()) + " != " +
                  std::to_string(expected.size()));
        for (std::size_t i = 0;
             i < batch.size() && i < expected.size(); ++i) {
            check(dump_equal(batch[i].to_json(), expected[i]),
                  id + "/batch/" + std::to_string(i),
                  "batch product mismatch: " +
                      first_mismatch(batch[i].to_json(), expected[i]));
        }
    }
}

void replay_interpretation_case(const Json& fixture_case) {
    const std::string id = fixture_case.at("id").get<std::string>();
    const Json null_json = Json(nullptr);
    const Json& interpretation = fixture_case.at("interpretation").is_null()
                                     ? null_json
                                     : fixture_case.at("interpretation");
    const Json* revision = fixture_case.at("revision").is_null()
                               ? nullptr
                               : &fixture_case.at("revision");
    const InterpretationSummary summary =
        interpretation_summary_rows(interpretation, revision);
    check(dump_equal(summary.to_display_dict(), fixture_case.at("expect")),
          "interpretation/" + id,
          "mismatch: " +
              first_mismatch(summary.to_display_dict(),
                             fixture_case.at("expect")));
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

    const Json& cases = fixture.at("cases");
    // 1 — tamper a product field (unit "m" -> "km").
    const Json& full = cases.at(0).at("checks").at("products");
    const std::string full_id = full.begin().key();
    Json tampered_product = full.begin().value();
    tampered_product["unit"] = "km";
    const std::optional<FactorProduct> product = factor_product_for_task(
        cases.at(0).at("tasks"), full_id);
    expect_inequality(dump_equal(product->to_json(), tampered_product),
                      "tampered_unit");

    // 2 — tamper a summary row state (ok -> warn).
    const Json& summaries = cases.at(0).at("checks").at("summaries");
    const std::string sum_id = summaries.begin().key();
    Json tampered_summary = summaries.begin().value();
    tampered_summary["rows"][0]["state"] = "warn";
    const std::optional<FactorProduct> sum_product = factor_product_for_task(
        cases.at(0).at("tasks"), sum_id);
    const FactorSummary direct =
        factor_summary(sum_product.has_value() ? &*sum_product : nullptr);
    expect_inequality(dump_equal(direct.to_display_dict(), tampered_summary),
                      "tampered_row_state");

    // 3 — tamper grid_shape ([100,80] -> [80,100]).
    for (const Json& c : cases) {
        if (c.at("id").get<std::string>() != "grid_shape_variants_batch") {
            continue;
        }
        const Json& products = c.at("checks").at("products");
        const std::string first_id = products.begin().key();
        Json tampered = products.begin().value();
        Json flipped = Json::array();
        flipped.push_back(tampered.at("grid_shape")[1]);
        flipped.push_back(tampered.at("grid_shape")[0]);
        tampered["grid_shape"] = flipped;
        const std::optional<FactorProduct> shape = factor_product_for_task(
            c.at("tasks"), first_id);
        expect_inequality(dump_equal(shape->to_json(), tampered),
                          "tampered_grid_shape");
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
    for (const Json& fixture_case : fixture.at("cases")) {
        replay_factor_case(fixture_case);
    }
    for (const Json& fixture_case : fixture.at("interpretation_cases")) {
        replay_interpretation_case(fixture_case);
    }
    const int negatives = negative_self_checks(fixture);

    if (g_failures != 0) {
        std::printf("%d FAILURES (of %d checks)\n", g_failures, g_checks);
        return 1;
    }
    std::printf("ALL %d CHECKS PASSED (+%d negative self-checks)\n", g_checks,
                negatives);
    return 0;
}
