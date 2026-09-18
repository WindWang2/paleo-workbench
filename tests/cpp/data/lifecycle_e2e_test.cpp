// data.lifecycle_e2e — the conv-26 acceptance loop, entirely C++ (no
// Python runtime anywhere in the path):
//
//   create project → directory import (plan + execute) → run registration
//   → result publish (journal transaction) → workspace membership + pin
//   → save → save-as (artifact relocation) → reopen → SQL pagination
//   → provenance/lineage + consistency audit + GC plan.
//
// This is the flow the C++ product needs to manage project data on its
// own; every stage goes through the production kernels (ingest_exec,
// CommitCoordinator, relocation, paged_sql).
#include "pwb_test.hpp"
#include "compare_json.hpp"

#include "pwb/catalog/gc.hpp"
#include "pwb/catalog/paged_sql.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/catalog/sqlite.hpp"
#include "pwb/data/ingest_exec.hpp"
#include "pwb/data/ingest_plan.hpp"
#include "pwb/data/run_contracts.hpp"
#include "pwb/data/save_as.hpp"
#include "pwb/data/session.hpp"
#include "pwb/domain/ids.hpp"
#include "pwb/project/manager.hpp"
#include "pwb/workspace/mutations.hpp"
#include "pwb/workspace/state.hpp"

#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;

struct E2e {
    fs::path root;
    fs::path incoming;
    fs::path project_file;

    E2e() {
        root = fs::temp_directory_path() / "pwb_lifecycle_e2e";
        std::error_code ec;
        fs::remove_all(root, ec);
        incoming = root / "incoming";
        fs::create_directories(incoming / "Well-A", ec);
        fs::create_directories(incoming / "survey", ec);
        project_file = root / "e2e.paleo.json";

        write(incoming / "Well-A" / "curves.las", "las-header-A\n");
        write(incoming / "Well-A" / "tops.csv", "formation,top\nF1,10\n");
        write(incoming / "survey" / "Gulf3D.sgy", "segy-bytes");

        // Create the project document through the production factory.
        pwb::project::ProjectManager manager(project_file);
        auto document = pwb::project::ProjectDocument::create_new("e2e", "");
        Json& root_json = document.root();
        root_json["wells"] = Json::array();
        Json well = Json::object();
        well["id"] = "well_e2e000000001";
        well["name"] = "Well-A";
        root_json["wells"].push_back(std::move(well));
        auto saved = manager.save(document);
        PWB_CHECK(saved.is_ok());
    }

    ~E2e() {
        std::error_code ec;
        fs::remove_all(root, ec);
    }

    static void write(const fs::path& file, const std::string& bytes) {
        std::ofstream stream(file, std::ios::binary);
        stream << bytes;
    }
};

}  // namespace

PWB_TEST(full_lifecycle_without_python_runtime) {
    E2e e2e;

    // ---- import: plan → confirm → execute --------------------------------
    auto session = pwb::data::WritableSession::open(e2e.project_file);
    if (!session.is_ok()) {
        std::cout << "  session open error: " << session.error().message
                  << "\n";
    }
    PWB_CHECK(session.is_ok());
    {
        auto catalog_doc = session.value().repository().open_read_only();
        PWB_CHECK(catalog_doc.is_ok());
        auto plan = pwb::data::build_ingest_plan(
            e2e.incoming, session.value().document(),
            {.preferred_only = true, .catalog = &catalog_doc.value()});
        std::cout << "  plan items: " << plan.items.size() << "\n";
        for (const auto& item : plan.items) {
            std::cout << "    " << item.path.filename().string() << " type="
                      << item.type << " decision=" << item.decision
                      << " note=" << item.note << "\n";
        }
        PWB_CHECK(plan.items.size() == 3);
        PWB_CHECK(plan.unresolved().empty());
        for (auto& item : plan.items) {
            if (item.decision == "pending") item.decision = "accept";
        }
        auto report = pwb::data::execute_ingest_plan(plan,
                                                     session.value());
        PWB_CHECK(report.imported_version_ids.size() == 3);
        PWB_CHECK(report.issues.empty());
        // Well-A bound (canonical name match), survey entity created.
        PWB_CHECK(report.created_entities == 1);
        PWB_CHECK(report.bound_links >= 2);
    }

    // ---- run + single-result publish through the journal path -------------
    const std::string asset_for_run =
        "derived-source";  // symbolic; run inputs use the imported versions
    auto catalog_doc = session.value().repository().open_read_only();
    PWB_CHECK(catalog_doc.is_ok());
    const auto& versions = catalog_doc.value().versions;
    PWB_CHECK(versions.size() == 3);

    pwb::data::RunRegistrationV1 registration;
    registration.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    registration.operation = "e2e.transform";
    registration.generator = "e2e-kernel@1.0";
    registration.parameters = Json::object();
    registration.parameters["factor"] = 1.5;
    for (const auto& version : versions) {
        registration.input_version_ids.push_back(version.id);
    }
    auto registered = session.value().coordinator().register_run(
        registration);
    PWB_CHECK(registered.is_ok());
    PWB_CHECK(registered.value().status == "running");

    const fs::path product = e2e.root / "result_grid.json";
    E2e::write(product, "{\"grid\": [1, 2, 3]}\n");
    pwb::data::PublishRequestV1 publish;
    publish.operation_id = pwb::domain::OperationId(
        pwb::domain::make_id("op_"));
    publish.run_id = registration.run_id;
    publish.new_asset_name = "e2e result grid";
    publish.new_asset_type = "grid";
    publish.stage = pwb::domain::DataStage::Derived;
    publish.products.push_back({product, std::nullopt, "json"});
    publish.result_metadata = Json::object();
    publish.result_metadata["units"] = "m";
    auto published = session.value().coordinator().publish_run_result(
        publish, session.value().document());
    PWB_CHECK(published.is_ok());
    PWB_CHECK(published.value().status == pwb::data::PublishStatus::Published);
    const std::string result_version = published.value().new_version_id.str();
    const std::string result_asset = published.value().asset_id.str();
    auto run_after = session.value().coordinator().run_state(
        registration.run_id);
    PWB_CHECK(run_after.has_value());
    PWB_CHECK(run_after->status == "complete");

    // ---- workspace membership + pinned version ----------------------------
    {
        pwb::domain::DiagnosticList diagnostics;
        Json& doc_root = session.value().document().root();
        pwb::workspace::ensure_mapping_workspace(doc_root);
        auto state = pwb::workspace::MappingWorkspaceState::from_json(
            doc_root["mapping_workspace"], diagnostics);
        auto bound = pwb::workspace::rebind_to_version(
            state, "layer_e2e_result", result_asset, result_version);
        PWB_CHECK(bound.changed);
        pwb::workspace::write_mapping_workspace(doc_root, state);
    }

    // ---- save → save-as → reopen ------------------------------------------
    auto saved = session.value().manager().save(session.value().document());
    PWB_CHECK(saved.is_ok());

    const fs::path relocated = e2e.root / "relocated" / "handed-over.paleo.json";
    auto outcome = pwb::data::save_session_as(session.value(), relocated);
    if (!outcome.is_ok()) {
        std::cout << "  save_as error: " << outcome.error().message << "\n";
    }
    PWB_CHECK(outcome.is_ok());
    PWB_CHECK(outcome.value().artifacts_relocated);
    {
        std::cout << "  relocated tree:\n";
        std::error_code ec;
        for (const auto& entry :
             fs::recursive_directory_iterator(relocated.parent_path(), ec)) {
            if (entry.is_regular_file(ec)) {
                std::cout << "    "
                          << fs::relative(entry.path(),
                                          relocated.parent_path())
                                 .generic_string()
                          << "\n";
            }
        }
    }

    auto reopened = pwb::data::WritableSession::open(relocated);
    PWB_CHECK(reopened.is_ok());
    auto store = reopened.value().repository().open_read_only();
    PWB_CHECK(store.is_ok());
    PWB_CHECK(store.value().assets.size() == 4);  // 3 imported + 1 result

    // ---- SQL pagination over the relocated store ---------------------------
    auto opened = pwb::catalog::Database::open(
        pwb::project::catalog_sqlite_for(relocated),
        pwb::catalog::SqliteOpenMode::ReadOnly);
    PWB_CHECK(opened.is_ok());
    {
        pwb::catalog::EntityPageQuery page;
        page.limit = 2;
        std::vector<Json> walked;
        int guard = 0;
        while (true) {
            auto rows = pwb::catalog::search_assets_page_sql(opened.value(),
                                                             page);
            if (rows.empty()) break;
            walked.insert(walked.end(), rows.begin(), rows.end());
            page.after = {rows.back()["name"].get<std::string>(),
                          rows.back()["id"].get<std::string>()};
            PWB_CHECK(++guard < 20);
        }
        PWB_CHECK(walked.size() == 4);
        pwb::catalog::EntityPageQuery count_query;
        count_query.text = "e2e";
        PWB_CHECK(pwb::catalog::count_assets_sql(opened.value(),
                                                 count_query) >= 1);
        pwb::catalog::EntityPageQuery stage_query;
        stage_query.stage = "derived";
        PWB_CHECK(pwb::catalog::count_assets_sql(opened.value(),
                                                 stage_query) == 1);
    }

    // ---- provenance / lineage ----------------------------------------------
    const auto& doc = store.value();
    const auto* run_row = doc.find_run(registration.run_id);
    PWB_CHECK(run_row != nullptr);
    PWB_CHECK(run_row->output_version_ids.size() == 1);
    PWB_CHECK(run_row->output_version_ids.front().str() == result_version);
    PWB_CHECK(run_row->input_version_ids.size() == 3);
    const auto* result_ver = doc.find_version(
        pwb::domain::VersionId(result_version));
    PWB_CHECK(result_ver != nullptr);
    PWB_CHECK(result_ver->parent_version_ids.size() == 3);
    PWB_CHECK(result_ver->run_id.has_value());
    PWB_CHECK(result_ver->run_id->str() == registration.run_id.str());

    // ---- workspace pin survived the round-trip -----------------------------
    {
        pwb::domain::DiagnosticList diagnostics;
        auto state = pwb::workspace::MappingWorkspaceState::from_json(
            reopened.value().document().root()["mapping_workspace"],
            diagnostics);
        PWB_CHECK(state.memberships.count("layer_e2e_result") == 1);
        PWB_CHECK(state.memberships["layer_e2e_result"].source_version_id ==
                  result_version);
        PWB_CHECK(pwb::workspace::effective_binding_kind(
                      state.memberships["layer_e2e_result"]) ==
                  "catalog_version");
    }

    // ---- consistency audit + GC plan ---------------------------------------
    std::vector<pwb::catalog::WorkspaceBindingRef> bindings;
    bindings.push_back({"layer_e2e_result", result_asset, result_version});
    auto findings = pwb::catalog::audit_catalog(doc, relocated, bindings);
    for (const auto& finding : findings) {
        std::cout << "  audit finding: " << finding.code << " — "
                  << finding.message << "\n";
    }
    PWB_CHECK(findings.empty());

    auto gc_plan = pwb::catalog::plan_gc({relocated, &doc}, false);
    PWB_CHECK(gc_plan.items.empty());

    // Stale-repair wiring: the pin survives while the version exists.
    pwb::domain::DiagnosticList diagnostics;
    auto state2 = pwb::workspace::MappingWorkspaceState::from_json(
        reopened.value().document().root()["mapping_workspace"],
        diagnostics);
    auto repair = pwb::workspace::repair_stale_bindings(
        state2,
        [&](const std::string& id) {
            return doc.find_version(pwb::domain::VersionId(id)) != nullptr;
        },
        [&](const std::string& asset) {
            const auto* row = doc.find_asset(pwb::domain::AssetId(asset));
            return row && row->current_version_id.has_value()
                       ? row->current_version_id->str()
                       : std::string();
        });
    PWB_CHECK(repair.inspected == 1);
    PWB_CHECK(repair.repaired_layers.empty());
}
