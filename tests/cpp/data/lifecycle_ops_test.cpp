// data.lifecycle_ops — Save-As artifact relocation + workspace membership
// mutations (conv-26). Python parity references: project/paths.py
// (StagedArtifactRelocation family), ui/project_controller.save_project_as
// (occupied-target refusal), workspace membership semantics from
// mapping_workspace/stage_state.py + the V13 binding rule.
#include "pwb_test.hpp"
#include "compare_json.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/data/save_as.hpp"
#include "pwb/data/session.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/project/manager.hpp"
#include "pwb/project/paths.hpp"
#include "pwb/project/relocation.hpp"
#include "pwb/workspace/mutations.hpp"
#include "pwb/workspace/state.hpp"

#include <filesystem>
#include <fstream>
#include <set>
#include <sstream>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;

fs::path fixture_dir() {
    return fs::path(PWB_DATA_FIXTURE_DIR) / "ingest_plan" / "main";
}

Json load_json(const fs::path& file) {
    std::ifstream stream(file, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return Json::parse(buffer.str(), nullptr, false);
}

struct Scratch {
    fs::path root;

    explicit Scratch(const std::string& tag) {
        root = fs::temp_directory_path() / ("pwb_lifecycle_" + tag);
        std::error_code ec;
        fs::remove_all(root, ec);
        fs::create_directories(root, ec);
        fs::copy(fixture_dir() / "tree", root,
                 fs::copy_options::recursive
                     | fs::copy_options::overwrite_existing,
                 ec);
    }

    ~Scratch() {
        std::error_code ec;
        fs::remove_all(root, ec);
    }
};

std::vector<std::string> files_under(const fs::path& base) {
    std::vector<std::string> files;
    std::error_code ec;
    if (!fs::exists(base, ec)) return files;
    for (const auto& entry : fs::recursive_directory_iterator(base, ec)) {
        if (entry.is_regular_file(ec)) {
            files.push_back(
                fs::relative(entry.path(), base).generic_string());
        }
    }
    std::sort(files.begin(), files.end());
    return files;
}

}  // namespace

PWB_TEST(staged_relocation_copies_then_removes_source_on_commit) {
    Scratch scratch("reloc_commit");
    const fs::path old_artifacts = scratch.root / "demo.artifacts";
    const fs::path new_project = scratch.root / "moved" / "renamed.paleo.json";
    fs::create_directories(new_project.parent_path());

    const auto before = files_under(old_artifacts);
    PWB_CHECK(before.size() >= 3);  // payload + metadata store + manifest

    auto staged = pwb::project::StagedArtifactRelocation::stage(
        scratch.root / "demo.paleo.json", new_project);
    PWB_CHECK(staged.is_ok());
    PWB_CHECK(staged.value().staged());

    // Copy mode: the target holds the full tree AND the source survives
    // until commit (an interrupted save-as cannot orphan the source).
    const auto copied = files_under(new_project.parent_path() /
                                    "renamed.artifacts");
    PWB_CHECK(copied == before);
    PWB_CHECK(fs::exists(old_artifacts / "metadata" / "catalog.sqlite"));

    PWB_CHECK(staged.value().commit());
    std::error_code ec;
    PWB_CHECK(!fs::exists(old_artifacts, ec));
    PWB_CHECK(files_under(new_project.parent_path() / "renamed.artifacts") ==
              before);
}

PWB_TEST(staged_relocation_rollback_restores_source) {
    Scratch scratch("reloc_rollback");
    const fs::path new_project = scratch.root / "moved" / "renamed.paleo.json";
    fs::create_directories(new_project.parent_path());
    const auto before =
        files_under(scratch.root / "demo.artifacts");

    auto staged = pwb::project::StagedArtifactRelocation::stage(
        scratch.root / "demo.paleo.json", new_project);
    PWB_CHECK(staged.is_ok());
    PWB_CHECK(staged.value().rollback());
    PWB_CHECK(files_under(scratch.root / "demo.artifacts") == before);
    std::error_code ec;
    PWB_CHECK(!fs::exists(new_project.parent_path() / "renamed.artifacts",
                          ec));
}

PWB_TEST(rebase_paths_cover_owned_external_and_prefixed) {
    const fs::path old_root = "/tmp/pwb_x/old.artifacts";
    const fs::path new_root = "/tmp/pwb_y/new.artifacts";
    const fs::path old_dir = "/tmp/pwb_x";

    auto rebased = pwb::project::rebase_owned_artifact_path(
        "/tmp/pwb_x/old.artifacts/raw/a/v/f.las", old_root, new_root,
        old_dir);
    PWB_CHECK(rebased.has_value());
    PWB_CHECK(*rebased == "/tmp/pwb_y/new.artifacts/raw/a/v/f.las");

    // Relative ref with the old artifacts prefix: the resolve-against-
    // project-dir branch wins first (Python resolve() also normalizes
    // nonexistent paths), yielding the absolute new-root path.
    auto prefixed = pwb::project::rebase_owned_artifact_path(
        "old.artifacts/qc/report.json", old_root, new_root, old_dir);
    PWB_CHECK(prefixed.has_value());
    PWB_CHECK(*prefixed == "/tmp/pwb_y/new.artifacts/qc/report.json");

    // External / unrelated paths are left alone.
    PWB_CHECK(!pwb::project::rebase_owned_artifact_path(
                   "/elsewhere/data.las", old_root, new_root, old_dir)
                   .has_value());
    PWB_CHECK(!pwb::project::rebase_owned_artifact_path(
                   "", old_root, new_root, old_dir)
                   .has_value());
}

PWB_TEST(save_session_as_relocates_and_reopens) {
    Scratch scratch("save_as");
    const fs::path old_project = scratch.root / "demo.paleo.json";
    const fs::path new_project =
        scratch.root / "elsewhere" / "copy.paleo.json";

    const auto payload_before = files_under(scratch.root / "demo.artifacts");

    {
        auto session = pwb::data::WritableSession::open(old_project);
        PWB_CHECK(session.is_ok());
        auto outcome = pwb::data::save_session_as(session.value(),
                                                   new_project);
        if (!outcome.is_ok()) {
            std::cout << "  save_as error: " << outcome.error().message
                      << "\n";
        } else {
            std::cout << "  save_as rebased_paths="
                      << outcome.value().rebased_paths
                      << " relocated=" << outcome.value().artifacts_relocated
                      << "\n";
        }
        PWB_CHECK(outcome.is_ok());
        PWB_CHECK(outcome.value().artifacts_relocated);
        PWB_CHECK(fs::exists(new_project));
    }

    // Commit removed the source tree; the relocated store opens at the
    // target with the same content.
    std::error_code ec;
    PWB_CHECK(!fs::exists(scratch.root / "demo.artifacts", ec));
    const fs::path new_artifacts =
        scratch.root / "elsewhere" / "copy.artifacts";
    PWB_CHECK(files_under(new_artifacts) == payload_before);

    auto reopened = pwb::data::WritableSession::open(new_project);
    PWB_CHECK(reopened.is_ok());
    auto catalog = reopened.value().repository().open_read_only();
    PWB_CHECK(catalog.is_ok());
    PWB_CHECK(catalog.value().assets.size() == 1);
    std::cout << "  reopened version path: "
              << catalog.value().versions.front().path << "\n";
    // The staged catalog was rebased to the target's artifacts name before
    // the target JSON landed (service.py rebase_artifact_paths parity), so
    // the project-relative managed path resolves at the new location.
    PWB_CHECK(catalog.value().versions.front().path.rfind(
                  "copy.artifacts/raw/", 0) == 0);
    // And the payload is actually reachable through it.
    std::error_code payload_ec;
    PWB_CHECK(fs::is_regular_file(
        new_project.parent_path() /
        pwb::project::path_from_u8(
            catalog.value().versions.front().path),
        payload_ec));
}

PWB_TEST(save_as_refuses_occupied_target_and_keeps_source) {
    Scratch scratch("save_as_refuse");
    const fs::path new_project =
        scratch.root / "elsewhere" / "copy.paleo.json";
    const fs::path occupied =
        scratch.root / "elsewhere" / "copy.artifacts" / "raw";
    fs::create_directories(occupied);
    std::ofstream(occupied / "stranger.dat") << "not ours";

    auto session = pwb::data::WritableSession::open(
        scratch.root / "demo.paleo.json");
    PWB_CHECK(session.is_ok());
    auto refused = pwb::data::save_session_as(session.value(), new_project);
    PWB_CHECK(!refused.is_ok());
    PWB_CHECK(refused.error().code == pwb::domain::ErrorCode::InvalidArgument);
    // Source untouched, stranger file untouched.
    PWB_CHECK(fs::exists(scratch.root / "demo.artifacts" / "metadata" /
                         "catalog.sqlite"));
    PWB_CHECK(fs::exists(occupied / "stranger.dat"));
    std::error_code ec;
    PWB_CHECK(!fs::exists(new_project, ec));
}

PWB_TEST(workspace_mutations_rebind_repair_and_roundtrip) {
    Scratch scratch("workspace");
    pwb::domain::DiagnosticList diagnostics;
    auto session = pwb::data::WritableSession::open(
        scratch.root / "demo.paleo.json");
    PWB_CHECK(session.is_ok());
    pwb::domain::Json& root = session.value().document().root();
    pwb::workspace::ensure_mapping_workspace(root);

    auto state = pwb::workspace::MappingWorkspaceState::from_json(
        root["mapping_workspace"], diagnostics);

    // add membership
    pwb::workspace::LayerBinding binding;
    binding.layer_id = "layer_facies_1";
    binding.role = "factor_map";
    binding.created_stage = "facies_calibration";
    binding.source_asset_id = "asset_00000000000a";
    binding.source_version_id = "ver_00000000000a";
    auto added = pwb::workspace::set_layer_binding(state, binding);
    PWB_CHECK(added.created && added.changed);

    // upsert same → no change
    auto again = pwb::workspace::set_layer_binding(state, binding);
    PWB_CHECK(!again.changed && !again.created);

    // rebind pins a new version (V13: implicit kind reads as
    // catalog_version)
    auto rebound = pwb::workspace::rebind_to_version(
        state, "layer_facies_1", "asset_00000000000a",
        "ver_00000000000b");
    PWB_CHECK(rebound.changed);
    PWB_CHECK(state.memberships["layer_facies_1"].source_version_id ==
              "ver_00000000000b");
    PWB_CHECK(pwb::workspace::effective_binding_kind(
                  state.memberships["layer_facies_1"]) ==
              "catalog_version");

    // second layer with explicit fingerprint kind
    pwb::workspace::LayerBinding fp;
    fp.layer_id = "layer_grid";
    fp.role = "paleo_map";
    fp.source_asset_id = "asset_00000000000b";
    fp.source_version_id = "ver_00000000000c";
    fp.binding_kind = "content_fingerprint";
    pwb::workspace::set_layer_binding(state, fp);

    // stale repair: pinned version of layer 1 is gone, asset moved on;
    // layer 2's version survives; both memberships persist.
    std::set<std::string> live{"ver_00000000000c"};
    auto repair = pwb::workspace::repair_stale_bindings(
        state,
        [&live](const std::string& id) { return live.count(id) > 0; },
        [](const std::string& asset) {
            return asset == "asset_00000000000a" ? "ver_000000000009"
                                                 : std::string();
        });
    PWB_CHECK(repair.inspected == 2);
    PWB_CHECK(repair.repaired_to_current == 1);
    PWB_CHECK(repair.reset_to_unknown == 0);
    PWB_CHECK(state.memberships["layer_facies_1"].source_version_id ==
              "ver_000000000009");

    // asset gone entirely → unknown
    live.clear();
    auto repair2 = pwb::workspace::repair_stale_bindings(
        state, [](const std::string&) { return false; },
        [](const std::string&) { return std::string(); });
    PWB_CHECK(repair2.repaired_to_current == 0);
    PWB_CHECK(repair2.reset_to_unknown == 2);
    PWB_CHECK(state.memberships["layer_grid"].source_version_id.empty());
    PWB_CHECK(state.memberships["layer_grid"].source_asset_id.empty());
    PWB_CHECK(state.memberships.count("layer_facies_1") == 1);

    // remove + round-trip through the document codec
    auto removed = pwb::workspace::remove_layer_binding(state,
                                                        "layer_grid");
    PWB_CHECK(removed.changed);
    pwb::workspace::write_mapping_workspace(root, state);
    auto reloaded = pwb::workspace::MappingWorkspaceState::from_json(
        root["mapping_workspace"], diagnostics);
    PWB_CHECK(reloaded.memberships.size() == 1);
    PWB_CHECK(reloaded.memberships.count("layer_facies_1") == 1);
    PWB_CHECK(reloaded.memberships["layer_facies_1"].source_version_id ==
              "");
}
