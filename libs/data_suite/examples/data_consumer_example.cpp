// pwb-data-loop — the A-line consumption example (v3-contracts.md §9).
//
// Drives the full data-kernel loop against a REAL project copy (valid
// resource paths + version bindings — e.g. tests/cpp/data/fixtures/typical):
//
//   1. read-only open + base-version query (DataFacade)
//   2. register an algorithm run (durable "running" row)
//   3. commit a staged edit file  → new DataVersion on the bound asset
//   4. publish one result volume  → new result asset/version + lineage,
//      run turns "complete" only after everything is durable
//   5. close all handles, reopen read-only
//   6. verify the new version/run/binding/lineage and print a JSON summary
//
// Exit 0 = the loop held; anything else prints diagnostics on stderr.
// No test doubles: this is the production library path A links against.
#include "pwb/catalog/repository.hpp"
#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/contracts.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/data/session.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/project/manager.hpp"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;

bool write_staged(const fs::path& file, const std::string& bytes) {
    std::error_code ec;
    fs::create_directories(file.parent_path(), ec);
    if (ec) return false;
    std::ofstream out(file, std::ios::binary | std::ios::trunc);
    if (!out) return false;
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    return static_cast<bool>(out);
}

fs::path staged_dir(const fs::path& project_file) {
    return pwb::project::project_dir_for(project_file) / "staged";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: pwb-data-loop <project-file.paleo.json>\n";
        return 2;
    }
    const fs::path project_file(argv[1]);
    if (!fs::is_regular_file(project_file)) {
        std::cerr << "project file not found: " << argv[1] << "\n";
        return 3;
    }

    // ---- 1. Read-only open: base version of the first bound layer.
    pwb::data::DataFacade facade(project_file);
    auto snapshot = facade.open_snapshot();
    if (!snapshot.is_ok()) {
        std::cerr << "open failed: " << snapshot.error().message << "\n";
        return 3;
    }
    if (snapshot.value().layer_bindings.empty() &&
        snapshot.value().catalog_assets.empty()) {
        std::cerr << "project has no bindings and no catalog assets\n";
        return 3;
    }
    // Pick a REAL target: a binding whose asset resolves in the catalog
    // (fixtures may legitimately carry bindings to unknown/recycled ids —
    // exactly what the audit reports); otherwise the first asset with a
    // current version. The optimistic lock needs the asset's CURRENT
    // version — a binding may pin an older one.
    pwb::domain::AssetId asset_id;
    pwb::domain::VersionId base_version_id;
    pwb::domain::LayerId layer_id;
    std::string binding_role;
    for (const auto& binding : snapshot.value().layer_bindings) {
        if (binding.source_asset_id.empty()) continue;
        const auto asset_row = std::find_if(
            snapshot.value().catalog_assets.begin(),
            snapshot.value().catalog_assets.end(),
            [&](const pwb::catalog::DataAsset& row) {
                return row.id.str() == binding.source_asset_id;
            });
        if (asset_row == snapshot.value().catalog_assets.end() ||
            !asset_row->current_version_id.has_value()) {
            continue;
        }
        asset_id = asset_row->id;
        base_version_id = *asset_row->current_version_id;
        layer_id = pwb::domain::LayerId(binding.layer_id);
        binding_role = binding.role;
        break;
    }
    if (asset_id.empty()) {
        const auto asset_row = std::find_if(
            snapshot.value().catalog_assets.begin(),
            snapshot.value().catalog_assets.end(),
            [](const pwb::catalog::DataAsset& row) {
                return row.current_version_id.has_value();
            });
        if (asset_row == snapshot.value().catalog_assets.end()) {
            std::cerr << "no catalog asset with a current version\n";
            return 3;
        }
        asset_id = asset_row->id;
        base_version_id = *asset_row->current_version_id;
    }

    // ---- 2-4. Writable session: register → commit edit → publish result.
    auto session = pwb::data::WritableSession::open(project_file);
    if (!session.is_ok()) {
        std::cerr << "writable open failed: " << session.error().message
                  << "\n";
        return 3;
    }
    pwb::data::RecoveryReportV1 recovery = session.value().recover();
    if (!recovery.pending.empty()) {
        std::cerr << "project still has pending journals\n";
        return 3;
    }
    auto& coordinator = session.value().coordinator();
    auto& document = session.value().document();

    // Two distinct runs — the manual-edit run links the edit commit (the
    // lifecycle.py manual_edit pattern), the algorithm run carries exactly
    // one published result (the single-result-volume rule).
    pwb::data::RunRegistrationV1 edit_run_registration;
    edit_run_registration.run_id =
        pwb::domain::RunId(pwb::domain::make_id("run_"));
    edit_run_registration.operation = "manual_edit";
    edit_run_registration.generator = "consumer-loop-example@1.0.0+v3";
    edit_run_registration.input_version_ids = {base_version_id};
    auto edit_run = coordinator.register_run(edit_run_registration);
    if (!edit_run.is_ok() ||
        edit_run.value().status != pwb::data::kRunStatusRunning) {
        std::cerr << "register_run (edit) failed\n";
        return 5;
    }

    pwb::data::RunRegistrationV1 registration;
    registration.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    registration.operation = "demo.consumer_loop";
    registration.generator = "consumer-loop-example@1.0.0+v3";
    registration.parameters = Json{{"window_ms", 12},
                                   {"units", "ms"},
                                   {"approximate", false}};
    registration.input_version_ids = {base_version_id};
    auto run = coordinator.register_run(registration);
    if (!run.is_ok() || run.value().status != pwb::data::kRunStatusRunning) {
        std::cerr << "register_run failed\n";
        return 5;
    }

    const fs::path staged_edit = staged_dir(project_file) / "edit_v3.bin";
    if (!write_staged(staged_edit, "consumer-loop-edit-payload-v3")) {
        std::cerr << "cannot stage edit payload\n";
        return 5;
    }
    pwb::data::CommitRequestV1 commit_request;
    commit_request.operation_id =
        pwb::domain::OperationId(pwb::domain::make_id("op_"));
    commit_request.asset_id = asset_id;
    commit_request.base_version_id = base_version_id;
    commit_request.stage = pwb::domain::DataStage::Derived;
    commit_request.staged.source_path = staged_edit;
    commit_request.staged.sha256 = pwb::domain::Sha256::of_file(staged_edit);
    commit_request.staged.format = "bin";
    commit_request.parent_version_ids = {base_version_id};
    commit_request.run_id = edit_run_registration.run_id;
    commit_request.rebind_layer = layer_id;
    commit_request.version_name = "consumer-loop-edit";
    auto commit = coordinator.commit(commit_request, document);
    if (!commit.is_ok() ||
        commit.value().status != pwb::data::CommitStatus::Committed) {
        std::cerr << "commit failed";
        if (commit.is_ok()) {
            for (const auto& diagnostic : commit.value().diagnostics) {
                std::cerr << " [" << diagnostic.code << "] "
                          << diagnostic.message;
            }
        } else {
            std::cerr << ": " << commit.error().message;
        }
        std::cerr << "\n";
        return 5;
    }

    const fs::path staged_result =
        staged_dir(project_file) / "result_v3.bin";
    if (!write_staged(staged_result,
                      "consumer-loop-result-volume-bytes-v3")) {
        std::cerr << "cannot stage result payload\n";
        return 5;
    }
    pwb::data::PublishRequestV1 publish;
    publish.operation_id =
        pwb::domain::OperationId(pwb::domain::make_id("op_"));
    publish.run_id = registration.run_id;
    publish.new_asset_name = "consumer-loop-result";
    publish.new_asset_type = "volume";
    publish.stage = pwb::domain::DataStage::Derived;
    pwb::data::StagedAssetV1 product;
    product.source_path = staged_result;
    product.sha256 = pwb::domain::Sha256::of_file(staged_result);
    product.format = "bin";
    publish.products.push_back(product);
    publish.result_metadata = Json{{"units", "ms"},
                                   {"approximate", false},
                                   {"encoding", "f32le"}};
    auto published = coordinator.publish_run_result(publish, document);
    if (!published.is_ok() ||
        published.value().status != pwb::data::PublishStatus::Published) {
        std::cerr << "publish failed";
        if (published.is_ok()) {
            for (const auto& diagnostic : published.value().diagnostics) {
                std::cerr << " [" << diagnostic.code << "] "
                          << diagnostic.message;
            }
        } else {
            std::cerr << ": " << published.error().message;
        }
        std::cerr << "\n";
        return 5;
    }

    const std::string edit_version = commit.value().new_version_id.str();
    const std::string result_version = published.value().new_version_id.str();
    const std::string result_asset = published.value().asset_id.str();
    const std::string run_id = registration.run_id.str();
    const std::string edit_run_id = edit_run_registration.run_id.str();

    // ---- 5. Close everything, then reopen read-only in fresh handles.
    {
        auto reopened = pwb::data::DataFacade(project_file).open_snapshot();
        if (!reopened.is_ok()) {
            std::cerr << "reopen failed: " << reopened.error().message << "\n";
            return 3;
        }
        const auto run_row = std::find_if(
            reopened.value().catalog_runs.begin(),
            reopened.value().catalog_runs.end(),
            [&](const pwb::catalog::DataRun& row) {
                return row.id.str() == run_id;
            });
        if (run_row == reopened.value().catalog_runs.end() ||
            run_row->status != pwb::data::kRunStatusComplete ||
            run_row->output_version_ids.size() != 1 ||
            run_row->output_version_ids.front().str() != result_version) {
            std::cerr << "run row incomplete after reopen\n";
            return 5;
        }
        if (!layer_id.empty()) {
            const auto binding_after = std::find_if(
                reopened.value().layer_bindings.begin(),
                reopened.value().layer_bindings.end(),
                [&](const pwb::workspace::LayerBinding& row) {
                    return row.layer_id == layer_id.str();
                });
            if (binding_after == reopened.value().layer_bindings.end() ||
                binding_after->source_version_id != edit_version) {
                std::cerr << "layer binding did not advance to the edit "
                             "version\n";
                return 5;
            }
        }
    }

    // ---- 6. Summary for the caller (A) — the provenance envelope shape.
    Json summary = Json::object();
    summary["base_version_id"] = base_version_id.str();
    summary["asset_id"] = asset_id.str();
    summary["layer_id"] = layer_id.str();
    summary["binding_role"] = binding_role;
    summary["edit_version_id"] = edit_version;
    summary["result_asset_id"] = result_asset;
    summary["result_version_id"] = result_version;
    summary["run_id"] = run_id;
    summary["edit_run_id"] = edit_run_id;
    summary["run_status"] = pwb::data::kRunStatusComplete;
    summary["result_sha256"] = published.value().sha256;
    std::cout << summary.dump(2) << "\n";
    return 0;
}
