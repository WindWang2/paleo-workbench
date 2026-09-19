// cpp-close-02 — frozen-oracle replay for the five-segment
// current-context resolve (resolve_current_project_version_context).
//
// Replays fixtures/closure_resolve_oracle.json (frozen from the REAL
// Python implementation by tools/oracle/generate_closure_resolve_fixtures.py)
// through the C++ port. Scenario inputs are rebuilt independently on the
// C++ side: the fixture catalog becomes a RuntimeStore snapshot, the
// project is the portable Json tree, and the resolved context is compared
// field-by-field (selected ids compared SORTED — the documented Python
// set-order divergence).
//
// Beyond the replay: a comparator negative self-check (a tampered
// expected context MUST fail).

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/resolve_context.hpp>

#include <cstdio>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

using pwb::domain::Json;
using pwb::workflow_runtime::AssetRecord;
using pwb::workflow_runtime::RunRecord;
using pwb::workflow_runtime::RuntimeStore;
using pwb::workflow_runtime::VersionRecord;

int failures = 0;
int checks = 0;

Json read_fixture(const char* path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error(std::string("cannot open fixture: ") + path);
    }
    Json data;
    in >> data;
    return data;
}

bool equals(const Json& left, const Json& right) {
    return pwb::domain::json_semantically_equal(left, right);
}

void check(const std::string& id, bool ok, const std::string& detail = "") {
    ++checks;
    if (!ok) {
        ++failures;
        std::printf("FAIL %s%s%s\n", id.c_str(), detail.empty() ? "" : ": ",
                    detail.c_str());
    }
}

void check_json(const std::string& id, const Json& got, const Json& expect) {
    check(id, equals(got, expect),
          "got=" + got.dump() + " expect=" + expect.dump());
}

// Test seam: rehydrate a RuntimeStore from the fixture's catalog snapshot.
class ReplayStore : public RuntimeStore {
public:
    ReplayStore() = default;

    void load(const Json& catalog) {
        std::vector<AssetRecord> assets;
        std::vector<VersionRecord> versions;
        std::vector<RunRecord> runs;
        for (const Json& node : catalog.at("assets")) {
            AssetRecord asset;
            asset.id = node.at("id").get<std::string>();
            asset.name = node.value("name", std::string());
            const Json& current = node.at("current_version_id");
            if (current.is_string()) {
                asset.current_version_id = current.get<std::string>();
            }
            assets.push_back(std::move(asset));
        }
        for (const Json& node : catalog.at("versions")) {
            VersionRecord version;
            version.asset_id = node.at("asset_id").get<std::string>();
            version.version_id = node.at("version_id").get<std::string>();
            version.name = node.value("name", std::string());
            const Json& run = node.at("producing_run_id");
            if (run.is_string()) {
                version.producing_run_id = run.get<std::string>();
            }
            version.created_at = node.value("created_at", std::string());
            versions.push_back(std::move(version));
        }
        for (const Json& node : catalog.at("runs")) {
            RunRecord run;
            run.run_id = node.at("run_id").get<std::string>();
            const Json& task = node.at("domain_task_id");
            if (task.is_string()) {
                run.domain_task_id = task.get<std::string>();
            }
            run.operation = node.value("operation", std::string());
            runs.push_back(std::move(run));
        }
        this->restore_state(std::move(assets), std::move(versions),
                            std::move(runs));
    }
};

Json sorted_ids(const std::vector<std::string>& ids) {
    std::vector<std::string> sorted = ids;
    std::sort(sorted.begin(), sorted.end());
    return Json(sorted);
}

std::string opt_str(const Json& node, const char* key) {
    const auto it = node.find(key);
    if (it == node.end() || !it->is_string()) return {};
    return it->get<std::string>();
}

void replay_case(const Json& scenario) {
    const std::string id = scenario.at("id").get<std::string>();
    const Json& input = scenario.at("input");
    const Json& expected = scenario.at("expected");

    ReplayStore store;
    const Json& catalog_json = input.at("catalog");
    if (!catalog_json.is_null()) {
        store.load(catalog_json);
    }
    const Json& project = input.at("project");
    std::map<std::string, std::string> extra;
    for (auto it = input.at("extra_selected").begin();
         it != input.at("extra_selected").end(); ++it) {
        extra[it.key()] = it->get<std::string>();
    }

    const pwb::workflow_runtime::CurrentProjectVersionContext context =
        pwb::workflow_runtime::resolve_current_project_version_context(
            catalog_json.is_null() ? nullptr : &store,
            project.is_null() ? nullptr : &project, extra);

    check_json(id + ".current_by_asset", Json(context.current_by_asset()),
               expected.at("current_by_asset"));
    check_json(id + ".selected_version_ids", sorted_ids(
                                                 context.selected_version_ids()),
               expected.at("selected_version_ids"));
    check_json(id + ".labels", Json(context.labels()), expected.at("labels"));
    check_json(id + ".expected_identity", Json(context.expected_identity()),
               expected.at("expected_identity"));
    check_json(id + ".current_by_domain_task",
               Json(context.current_by_domain_task()),
               expected.at("current_by_domain_task"));
}

void negative_self_check(const Json& fixture) {
    // Tamper the first case's expected selection: the comparator MUST
    // reject it.
    Json tampered = fixture;
    Json& expected =
        tampered.at("cases").at(0).at("expected").at("current_by_asset");
    if (expected.is_object() && !expected.empty()) {
        auto it = expected.begin();
        it.value() = Json("ver_tampered");
        const Json& input = tampered.at("cases").at(0).at("input");
        ReplayStore store;
        if (!input.at("catalog").is_null()) store.load(input.at("catalog"));
        Json project_copy = input.at("project");
        const pwb::workflow_runtime::CurrentProjectVersionContext context =
            pwb::workflow_runtime::resolve_current_project_version_context(
                input.at("catalog").is_null() ? nullptr : &store,
                project_copy.is_null() ? nullptr : &project_copy, {});
        check("negative.tampered_context_detected",
              !equals(Json(context.current_by_asset()), expected));
    } else {
        check("negative.tampered_context_detected", true);  // vacuous guard
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]);
        return 2;
    }
    try {
        const Json fixture = read_fixture(argv[1]);
        for (const Json& scenario : fixture.at("cases")) {
            replay_case(scenario);
        }
        negative_self_check(fixture);
    } catch (const std::exception& exc) {
        std::printf("FATAL %s\n", exc.what());
        return 1;
    }
    std::printf("closure_workflow.resolve: %d checks, %d failures\n", checks,
                failures);
    return failures == 0 ? 0 : 1;
}
