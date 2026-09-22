// fault_lifecycle domain test: draft lifting from constraint layers,
// fingerprint determinism, save → project ref → restore roundtrip (clean
// draft, parent pinned), noop short-circuit, and the H7 compensation (a
// failing catalog never leaves a local artifact behind). No frozen oracle
// fixture — the assertions are structural (the Python chain's own
// lifecycle contract), like the integrated tests.
#include <pwb/workflow_interpretation/fault_lifecycle.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <unistd.h>
#include <filesystem>
#include <string>

namespace {

namespace fs = std::filesystem;
using namespace pwb::workflow_interpretation;
using pwb::domain::Json;

int g_failures = 0;

void check(bool condition, const std::string& what) {
    if (!condition) {
        ++g_failures;
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
    }
}

// A catalog whose register_result_asset always fails — the H7 probe.
class FailingCatalog final : public pwb::workflow_runtime::CatalogRepository {
public:
    std::vector<pwb::workflow_runtime::AssetRecord> list_assets() override {
        return {};
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
    std::string register_run(const std::string&, const std::vector<std::string>&,
                             const Json&, const std::optional<std::string>&,
                             const std::string& = "running",
                             const std::optional<std::string>& = std::nullopt,
                             const std::optional<std::string>& = std::nullopt,
                             const std::optional<std::string>& = std::nullopt)
        override {
        throw std::runtime_error("catalog down (test probe)");
    }
    pwb::workflow_runtime::RegisteredAssetVersion register_result_asset(
        const std::string&, const std::string&, const std::string&,
        const Json&, const std::string&, const std::string&,
        const std::string&, const Json&) override {
        throw std::runtime_error("catalog down (test probe)");
    }
    std::string register_version(const std::string&, const std::string&,
                                 const std::string&,
                                 const std::vector<std::string>&,
                                 const std::string&, const Json&) override {
        throw std::runtime_error("catalog down (test probe)");
    }
    void update_run_status(const std::string&, const std::string&) override {}
    void attach_run_output(const std::string&, const std::string&) override {}
    void set_current_version(const std::string&, const std::string&) override {}
    std::optional<std::string> verify_integrity(const std::string&) override {
        return std::nullopt;
    }
};

Json constraint_layers() {
    Json layers = Json::object();
    layers["id"] = "cl_1";
    layers["name"] = "约束层";
    Json lines = Json::array();
    Json break_line = Json::object();
    break_line["id"] = "ln_1";
    break_line["name"] = "F1";
    break_line["role"] = "break";
    break_line["coordinates"] =
        Json::array({Json::array({0.0, 0.0}), Json::array({1.0, 1.0}),
                     Json::array({2.0, 0.5})});
    lines.push_back(std::move(break_line));
    Json other = Json::object();
    other["id"] = "ln_2";
    other["role"] = "boundary";  // NOT lifted (break/fault only)
    other["coordinates"] =
        Json::array({Json::array({0.0, 0.0}), Json::array({1.0, 0.0})});
    lines.push_back(std::move(other));
    Json too_short = Json::object();
    too_short["id"] = "ln_3";
    too_short["role"] = "fault";
    too_short["coordinates"] = Json::array({Json::array({5.0, 5.0})});
    lines.push_back(std::move(too_short));
    layers["lines"] = std::move(lines);
    return layers;
}

}  // namespace

int main() {
    const fs::path dir = fs::temp_directory_path()
        / ("fault_lifecycle_test_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    const fs::path fault_dir = dir / "faults";
    Json project = Json::object();

    // draft_from_constraint_layers: break/fault polylines ≥2 points only.
    auto draft = draft_from_constraint_layers(constraint_layers(),
                                              "断层约束", "EPSG:4326");
    check(draft.payload.traces.size() == 1,
          "only the break polyline lifts into a trace");
    check(draft.payload.traces[0].role == "break"
              && draft.payload.traces[0].polyline.size() == 3,
          "trace keeps the map-plane polyline");

    // Fingerprint stability: trace ORDER does not matter (the scientific
    // dict sorts by (name, id)) — fresh drafts carry fresh trace ids, so
    // the invariant is over one payload, not across drafts.
    auto reordered = draft;
    std::reverse(reordered.payload.traces.begin(),
                 reordered.payload.traces.end());
    check(draft_fingerprint(draft) == draft_fingerprint(reordered),
          "scientific fingerprint is order-stable");

    // save (no catalog): ref lands, artifact exists, parent chain advances.
    const auto [ref, outcome] =
        save_fault_draft(draft, project, fault_dir, dir, nullptr);
    check(outcome == "ok" && ref.has_value(), "save ok without a catalog");
    check(ref->current_version_id.size() > 4, "version token recorded");
    check(fs::is_regular_file(dir / ref->artifact_path),
          "artifact file exists at the recorded path");
    check(!draft.dirty, "save clears the dirty flag");
    check(draft.payload.parent_version_id.has_value()
              && *draft.payload.parent_version_id == ref->current_version_id,
          "parent pinned to the saved version");

    // Unchanged re-save short-circuits.
    const auto [ref2, outcome2] =
        save_fault_draft(draft, project, fault_dir, dir, nullptr);
    check(outcome2 == "noop_unchanged" && ref2.has_value(),
          "unchanged draft is a noop");

    // restore: clean draft off the project ref, parent = current version.
    auto restored = restore_fault_draft_from_project(project, dir);
    check(restored.has_value() && !restored->dirty,
          "restore yields a clean draft");
    check(restored->payload.traces.size() == 1
              && restored->last_saved_fingerprint == ref->scientific_fingerprint,
          "restored payload matches the saved fingerprint");

    // Dirty edit → new version on save (chain grows).
    restored->payload.traces.push_back(FaultTrace{
        "ftrace_x", "F2",
        {{9.0, 9.0}, {8.0, 7.0}}, "fault", "", "", Json::array(),
        std::nullopt});
    restored->dirty = true;
    const auto [ref3, outcome3] =
        save_fault_draft(*restored, project, fault_dir, dir, nullptr);
    check(outcome3 == "ok" && ref3.has_value()
              && ref3->parent_version_id.has_value()
              && *ref3->parent_version_id == ref->current_version_id,
          "edited draft saves a new version with the old parent");
    check(find_fault_ref(project, restored->interpretation_id)
              ->current_version_id == ref3->current_version_id,
          "project ref advances to the new version");

    // H7 compensation: a failing catalog leaves no ghost artifact.
    FailingCatalog failing;
    auto probe = new_fault_draft("断层解释");
    probe.payload.traces.push_back(FaultTrace{
        "ftrace_y", "F3", {{0.0, 0.0}, {1.0, 2.0}}, "fault", "", "",
        Json::array(), std::nullopt});
    bool compensated = false;
    try {
        (void)save_fault_draft(probe, project, fault_dir, dir, &failing);
    } catch (const std::exception&) {
        compensated = true;
    }
    check(compensated, "catalog failure re-raises");
    check(find_fault_ref(project, probe.interpretation_id) == std::nullopt,
          "failed save leaves no project ref");
    bool ghost = false;
    for (const auto& entry : fs::directory_iterator(fault_dir)) {
        ghost |= entry.path().filename().string().rfind(
                     probe.interpretation_id, 0) == 0;
    }
    check(!ghost, "failed save leaves no ghost artifact (H7)");

    fs::remove_all(dir);
    if (g_failures != 0) {
        std::fprintf(stderr, "%d failure(s)\n", g_failures);
        return 1;
    }
    std::fprintf(stderr, "workflow_interpretation.fault_lifecycle: ok\n");
    return 0;
}
