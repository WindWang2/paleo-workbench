// WI3: the workspace-freshness evaluator shipped with zero direct tests
// (its only consumer is the app shell). Locks the basics: null-catalog
// honesty (WI2 — never fabricated missing_input), and the
// membership-driven evaluation shape.

#include <cstdio>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/workflow_interpretation/dependencies.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

namespace {

using Json = pwb::domain::Json;
namespace artifact_type = pwb::workflow_interpretation::artifact_type;
namespace freshness_status = pwb::workflow_interpretation::freshness_status;
using pwb::workflow_interpretation::evaluate_workspace_freshness;
using pwb::workflow_runtime::CatalogRepository;
using pwb::workflow_runtime::VersionRecord;

int failures = 0;

void check(bool ok, const char* what) {
    if (!ok) {
        ++failures;
        std::printf("FAIL %s\n", what);
    }
}

// A catalog with exactly one resolvable version id.
class SingleVersionCatalog final : public CatalogRepository {
public:
    explicit SingleVersionCatalog(std::string id)
        : id_(std::move(id)) {}

    std::vector<pwb::workflow_runtime::AssetRecord> list_assets() override {
        return {};
    }
    std::optional<pwb::workflow_runtime::AssetRecord> resolve_asset(
        const std::string&) override {
        return std::nullopt;
    }
    std::optional<pwb::workflow_runtime::RunRecord> resolve_run(
        const std::string&) override {
        return std::nullopt;
    }
    std::string register_run(
        const std::string&, const std::vector<std::string>&, const Json&,
        const std::optional<std::string>&, const std::string& = "running",
        const std::optional<std::string>& = std::nullopt,
        const std::optional<std::string>& = std::nullopt,
        const std::optional<std::string>& = std::nullopt) override {
        return "run_unit";
    }
    pwb::workflow_runtime::RegisteredAssetVersion register_result_asset(
        const std::string&, const std::string&, const std::string&,
        const Json&, const std::string&, const std::string&,
        const std::string&, const Json&) override {
        return {};
    }
    std::string register_version(
        const std::string&, const std::string&, const std::string&,
        const std::vector<std::string>&, const std::string&,
        const Json&) override {
        return "ver_unit";
    }
    void update_run_status(const std::string&, const std::string&) override {}
    void attach_run_output(const std::string&, const std::string&) override {}
    void set_current_version(const std::string&, const std::string&) override {}
    std::optional<std::string> verify_integrity(const std::string&) override {
        return std::nullopt;
    }
    std::vector<pwb::workflow_runtime::RunRecord> list_runs() override {
        return {};
    }
    std::vector<VersionRecord> list_versions(
        const std::string& /*asset_id*/) override {
        return {};
    }
    std::optional<VersionRecord> resolve_version(
        const std::string& version_id) override {
        if (version_id != id_) return std::nullopt;
        VersionRecord record;
        record.asset_id = "asset_unit";
        record.version_id = version_id;
        record.name = "unit";
        record.created_at = "2026-09-22T00:00:00Z";
        return record;
    }

private:
    std::string id_;
};

}  // namespace

int main() {
    // Real shapes: memberships is an OBJECT keyed by layer id; the
    // evidence set rides workspace_state["compilation_input_set"] (the
    // legacy dict seam evidence_view falls back to).
    auto make_workspace = []() {
        Json memberships = Json::object();
        Json entry = Json::object();
        entry["role"] = "integrated_facies";
        memberships["layer_int"] = std::move(entry);
        Json input_set = Json::object();
        input_set["evidence.factor_int"] =
            "ver_000000000000000000000000000001";
        Json workspace = Json::object();
        workspace["memberships"] = std::move(memberships);
        workspace["compilation_input_set"] = std::move(input_set);
        return workspace;
    };
    Json document = Json::object();

    // WI2: null catalog — verifiable checks degrade to UNKNOWN; the header
    // contract forbids fabricating missing_input ("inputs cleaned" when
    // the truth is "no catalog wired").
    {
        Json workspace = make_workspace();
        auto results =
            evaluate_workspace_freshness(document, &workspace, nullptr);
        bool saw_integrated = false;
        for (const auto& fresh : results) {
            std::printf("  artifact type=%s stage=%s status=%s detail=%s\n",
                        fresh.type.c_str(), fresh.stage.c_str(),
                        fresh.status.c_str(), fresh.detail.c_str());
            if (fresh.type != artifact_type::kIntegrated) continue;
            saw_integrated = true;
            check(fresh.status == freshness_status::kUnknown,
                  "null catalog degrades to unknown, not missing_input");
        }
        check(saw_integrated,
              "integrated membership must be evaluated (not vacuous)");
    }

    // With a catalog: the pinned version resolves → never missing_input.
    {
        SingleVersionCatalog catalog(
            "ver_000000000000000000000000000001");
        Json workspace = make_workspace();
        auto results =
            evaluate_workspace_freshness(document, &workspace, &catalog);
        for (const auto& fresh : results) {
            if (fresh.type != artifact_type::kIntegrated) continue;
            check(fresh.status != freshness_status::kMissingInput,
                  "resolvable pinned version is never missing_input");
        }
    }

    // Empty workspace is legal and yields no artifacts.
    {
        Json workspace = Json::object();
        auto results =
            evaluate_workspace_freshness(document, &workspace, nullptr);
        check(results.empty(), "empty workspace → no artifacts");
    }

    if (failures == 0) {
        std::printf("workflow_interpretation.dependencies: all checks passed\n");
        return 0;
    }
    std::printf("workflow_interpretation.dependencies: %d failure(s)\n",
                failures);
    return 1;
}
