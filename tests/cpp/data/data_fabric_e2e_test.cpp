// data.data_fabric_e2e — V14-DATA-LINEAGE cross-module acceptance loop
// (line prompt §13): project → well → multi-role imports → primary/ordinal
// binding → staged edit commit (manual_edit provenance) → INTERMEDIATE run
// (lifecycle-classified publish) → DERIVED run → upstream bump → downstream
// stale → explain → delete impact → usage refs → save → close/reopen with
// identity/version/member/lineage preservation. Appendix: duplicate ingest,
// missing-payload probe, ephemeral-kind refusal.
#include "pwb_test.hpp"

#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/explain.hpp"
#include "pwb/catalog/impact.hpp"
#include "pwb/catalog/manual_edit.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/entity_identity.hpp"
#include "pwb/data/entity_workspace.hpp"
#include "pwb/data/ingest_exec.hpp"
#include "pwb/data/ingest_plan.hpp"
#include "pwb/data/session.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/project/manager.hpp"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <string>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;

struct Fixture {
    fs::path root;
    fs::path incoming;
    fs::path project_file;

    Fixture() {
        root = fs::temp_directory_path() / "pwb_data_fabric_e2e";
        std::error_code ec;
        fs::remove_all(root, ec);
        incoming = root / "incoming";
        fs::create_directories(incoming / "Well-A", ec);
        project_file = root / "fabric.paleo.json";

        write(incoming / "Well-A" / "A_main.las", "las-main-v1\nCURVE GR\n");
        write(incoming / "Well-A" / "A_sonic.las", "las-sonic-v1\nCURVE DT\n");
        write(incoming / "Well-A" / "survey_original.csv",
              "md,inc,azi\n0,0,0\n100,1.5,90\n");
        write(incoming / "Well-A" / "tops.csv", "formation,top\nF1,10\n");

        pwb::project::ProjectManager manager(project_file);
        auto document = pwb::project::ProjectDocument::create_new("fabric", "");
        Json& root_json = document.root();
        root_json["wells"] = Json::array();
        Json well = Json::object();
        well["id"] = "well_fab000000001";
        well["name"] = "Well-A";
        root_json["wells"].push_back(std::move(well));
        auto saved = manager.save(document);
        PWB_CHECK(saved.is_ok());
    }

    ~Fixture() {
        std::error_code ec;
        fs::remove_all(root, ec);
    }

    static void write(const fs::path& file, const std::string& bytes) {
        std::ofstream stream(file, std::ios::binary);
        stream << bytes;
    }
};

std::string stage_copy(const fs::path& source, const fs::path& dir,
                       const std::string& suffix) {
    fs::path target = dir / (source.filename().stem().string() + suffix +
                             source.filename().extension().string());
    std::error_code ec;
    fs::copy_file(source, target, fs::copy_options::overwrite_existing, ec);
    return target.string();
}

}  // namespace

PWB_TEST(data_fabric_full_loop) {
    using pwb::data::WritableSession;
    Fixture fx;

    // (1)(2) project + Well A exist; (3) import LAS×2 + trajectory + tops.
    auto session = WritableSession::open(fx.project_file);
    PWB_CHECK(session.is_ok());
    {
        auto catalog_doc = session.value().repository().open_read_only();
        PWB_CHECK(catalog_doc.is_ok());
        auto plan = pwb::data::build_ingest_plan(
            fx.incoming, session.value().document(),
            {.preferred_only = true, .catalog = &catalog_doc.value()});
        PWB_CHECK(plan.items.size() == 4);
        for (auto& item : plan.items) {
            if (item.decision == "pending") item.decision = "accept";
        }
        auto report = pwb::data::execute_ingest_plan(plan, session.value());
        PWB_CHECK(report.imported_version_ids.size() == 4);
        PWB_CHECK(report.issues.empty());
    }

    // Import bound some links automatically; normalize them into explicit
    // multi-role membership with (4)(5) primary + ordinal semantics.
    Json& root = session.value().document().root();
    auto links = pwb::data::links_for_entity(root, "well", "well_fab000000001");
    PWB_CHECK(!links.empty());
    // Identify imported assets by role inference from the bound links.
    std::map<std::string, std::vector<std::string>> by_role;
    for (const auto& link : links) by_role[link.role].push_back(link.asset_id);
    PWB_CHECK(!by_role["well_log"].empty());
    PWB_CHECK(by_role["well_log"].size() == 2);  // A_main + A_sonic
    PWB_CHECK(!by_role["trajectory"].empty());
    PWB_CHECK(!by_role["tops"].empty());

    const std::string main_log = by_role["well_log"][0];
    const std::string sonic_log = by_role["well_log"][1];
    const std::string trajectory = by_role["trajectory"][0];
    const std::string tops = by_role["tops"][0];

    // trajectory primary; logs ordered by ordinal (load order).
    pwb::data::upsert_entity_asset_link(root, "well", "well_fab000000001",
                                        trajectory, "trajectory", true);
    pwb::data::upsert_entity_asset_link(root, "well", "well_fab000000001",
                                        main_log, "well_log", true, false, "",
                                        0);
    pwb::data::upsert_entity_asset_link(root, "well", "well_fab000000001",
                                        sonic_log, "well_log", false, false,
                                        "", 1);
    pwb::data::upsert_entity_asset_link(root, "well", "well_fab000000001",
                                        tops, "tops", true);
    {
        auto again = pwb::data::links_for_entity(root, "well",
                                                 "well_fab000000001");
        std::map<std::string, pwb::data::EntityLinkView> by_asset;
        for (const auto& link : again) by_asset[link.asset_id] = link;
        PWB_CHECK(by_asset[sonic_log].ordinal == 1);
        PWB_CHECK(!by_asset[sonic_log].is_primary);
        PWB_CHECK(by_asset[main_log].is_primary);
        PWB_CHECK(by_asset[main_log].ordinal == 0);
        // single-primary invariant on re-flip
        pwb::data::upsert_entity_asset_link(root, "well",
                                            "well_fab000000001", sonic_log,
                                            "well_log", true, false, "",
                                            -1);  // keep ordinal
        auto after = pwb::data::links_for_entity(root, "well",
                                                 "well_fab000000001");
        int primaries = 0;
        for (const auto& link : after) {
            if (link.role == "well_log" && link.is_primary) ++primaries;
        }
        PWB_CHECK(primaries == 1);
    }

    // Workspace view over the imported state (before edits).
    auto doc1 = session.value().repository().open_read_only();
    PWB_CHECK(doc1.is_ok());
    const auto current_of = [&](const std::string& asset_id) {
        for (const auto& asset : doc1.value().assets) {
            if (asset.id.str() == asset_id &&
                asset.current_version_id.has_value()) {
                return asset.current_version_id->str();
            }
        }
        return std::string();
    };
    const std::string tops_v1 = current_of(tops);
    PWB_CHECK(!tops_v1.empty());

    // (6)(7)(10) staged edit of tops with manual_edit provenance.
    pwb::data::RunRegistrationV1 manual;
    manual.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    manual.operation = "manual_edit";
    manual.generator = "paleo-workbench/manual-edit";
    manual.input_version_ids.push_back(pwb::domain::VersionId(tops_v1));
    manual.parameters = Json{{"entity_type", "well"},
                             {"entity_id", "well_fab000000001"},
                             {"business_role", "tops"}};
    pwb::catalog::RunPort port;
    port.direction = "input";
    port.role = "tops";
    port.version_id = pwb::domain::VersionId(tops_v1);
    port.ordinal = 0;
    manual.input_ports.push_back(port);
    auto manual_run = session.value().coordinator().register_run(manual);
    PWB_CHECK(manual_run.is_ok());

    // Resolve the imported payload path for the staged edit copy.
    std::string tops_payload;
    for (const auto& version : doc1.value().versions) {
        if (version.id.str() == tops_v1) tops_payload = version.path;
    }
    PWB_CHECK(!tops_payload.empty());
    // The repository stores project-relative paths; the artifacts root sits
    // beside the project file.
    const fs::path artifacts_root =
        fx.project_file.parent_path() /
        (fx.project_file.stem().string() + ".artifacts");
    const fs::path staged_edit =
        artifacts_root / "working" / "tops_manual_edit.csv";
    fs::create_directories(staged_edit.parent_path());
    Fixture::write(staged_edit, "formation,top\nF1,10.5\nF2,22\n");

    pwb::data::CommitRequestV1 commit;
    commit.operation_id = pwb::domain::OperationId(pwb::domain::make_id("op_"));
    commit.asset_id = pwb::domain::AssetId(tops);
    commit.base_version_id = pwb::domain::VersionId(tops_v1);
    commit.stage = pwb::domain::DataStage::Raw;
    commit.staged = {staged_edit, std::nullopt, "csv"};
    commit.run_id = manual.run_id;
    commit.version_name = "manual tops correction";
    auto committed = session.value().coordinator().commit(
        commit, session.value().document());
    PWB_CHECK(committed.is_ok());
    const std::string tops_v2 = committed.value().new_version_id.str();
    PWB_CHECK(!tops_v2.empty());
    PWB_CHECK(committed.value().version_number == 2);

    // (8) INTERMEDIATE run output — lifecycle-classified publish.
    pwb::data::RunRegistrationV1 normalize;
    normalize.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    normalize.operation = "well.normalize_logs";
    normalize.generator = "pwb/well-science@1.4";
    normalize.parameters = Json{{"curve", "GR"}, {"window", 5}};
    normalize.input_version_ids.push_back(
        pwb::domain::VersionId(current_of(main_log)));
    auto normalize_run = session.value().coordinator().register_run(normalize);
    PWB_CHECK(normalize_run.is_ok());

    const fs::path intermediate_file = fx.root / "normalized_gr.json";
    Fixture::write(intermediate_file, "{\"gr\": [1,2,3]}\n");
    pwb::data::PublishRequestV1 inter_pub;
    inter_pub.operation_id =
        pwb::domain::OperationId(pwb::domain::make_id("op_"));
    inter_pub.run_id = normalize.run_id;
    inter_pub.new_asset_name = "Well-A normalized GR";
    inter_pub.new_asset_type = "well_log_processed";
    inter_pub.stage = pwb::domain::DataStage::Derived;  // policy must win
    inter_pub.artifact_kind = "prediction_intermediate";
    inter_pub.products.push_back({intermediate_file, std::nullopt, "json"});
    auto inter = session.value().coordinator().publish_run_result(
        inter_pub, session.value().document());
    PWB_CHECK(inter.is_ok());
    PWB_CHECK(inter.value().status == pwb::data::PublishStatus::Published);
    const std::string intermediate_version = inter.value().new_version_id.str();
    const std::string intermediate_asset = inter.value().asset_id.str();

    // Bind the intermediate to the well under interpretation role.
    pwb::data::upsert_entity_asset_link(root, "well", "well_fab000000001",
                                        intermediate_asset, "interpretation",
                                        false);

    // (9) DERIVED run consuming the intermediate.
    pwb::data::RunRegistrationV1 facies;
    facies.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    facies.operation = "prediction.facies";
    facies.generator = "pwb/prediction@2.0";
    facies.parameters = Json{{"model", "facies-v3"}};
    facies.input_version_ids.push_back(
        pwb::domain::VersionId(intermediate_version));
    auto facies_run = session.value().coordinator().register_run(facies);
    PWB_CHECK(facies_run.is_ok());
    const fs::path derived_file = fx.root / "facies_prediction.json";
    Fixture::write(derived_file, "{\"facies\": \"F2\"}\n");
    pwb::data::PublishRequestV1 derived_pub;
    derived_pub.operation_id =
        pwb::domain::OperationId(pwb::domain::make_id("op_"));
    derived_pub.run_id = facies.run_id;
    derived_pub.new_asset_name = "Well-A facies prediction";
    derived_pub.new_asset_type = "prediction";
    derived_pub.stage = pwb::domain::DataStage::Derived;
    derived_pub.products.push_back({derived_file, std::nullopt, "json"});
    auto derived = session.value().coordinator().publish_run_result(
        derived_pub, session.value().document());
    PWB_CHECK(derived.is_ok());
    const std::string derived_version = derived.value().new_version_id.str();

    // Appendix: ephemeral artifact kinds are refused BEFORE any write.
    pwb::data::RunRegistrationV1 ephemeral;
    ephemeral.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    ephemeral.operation = "render.preview";
    ephemeral.generator = "pwb/render@1";
    ephemeral.input_version_ids.push_back(
        pwb::domain::VersionId(derived_version));
    auto ephemeral_run = session.value().coordinator().register_run(ephemeral);
    PWB_CHECK(ephemeral_run.is_ok());
    const fs::path temp_svg = fx.root / "preview.svg";
    Fixture::write(temp_svg, "<svg/>");
    pwb::data::PublishRequestV1 refused;
    refused.operation_id =
        pwb::domain::OperationId(pwb::domain::make_id("op_"));
    refused.run_id = ephemeral.run_id;
    refused.new_asset_name = "preview";
    refused.artifact_kind = "render_temp_svg";
    refused.products.push_back({temp_svg, std::nullopt, "svg"});
    auto refused_pub = session.value().coordinator().publish_run_result(
        refused, session.value().document());
    PWB_CHECK(refused_pub.is_ok());  // validation gate → Failed receipt
    PWB_CHECK(refused_pub.value().status == pwb::data::PublishStatus::Failed);
    bool lifecycle_refused = false;
    for (const auto& diagnostic : refused_pub.value().diagnostics) {
        if (diagnostic.code == "artifact_lifecycle_refused") {
            lifecycle_refused = true;
        }
    }
    PWB_CHECK(lifecycle_refused);

    // (11) upstream bump: a manual edit on the MAIN LOG (the normalize
    // run's input) — evolving that asset's current version is what makes
    // the INTERMEDIATE (its consumer) stale.
    const std::string main_log_v1 = current_of(main_log);
    PWB_CHECK(!main_log_v1.empty());
    pwb::data::RunRegistrationV1 manual2;
    manual2.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    manual2.operation = "manual_edit";
    manual2.generator = "paleo-workbench/manual-edit";
    manual2.input_version_ids.push_back(
        pwb::domain::VersionId(main_log_v1));
    manual2.parameters = Json{{"business_role", "well_log"}};
    auto manual2_run = session.value().coordinator().register_run(manual2);
    PWB_CHECK(manual2_run.is_ok());
    const fs::path staged_edit2 =
        artifacts_root / "working" / "main_log_manual_edit.las";
    Fixture::write(staged_edit2, "las-main-v1-edited CURVE GR");
    pwb::data::CommitRequestV1 bump;
    bump.operation_id = pwb::domain::OperationId(pwb::domain::make_id("op_"));
    bump.asset_id = pwb::domain::AssetId(main_log);
    bump.base_version_id = pwb::domain::VersionId(main_log_v1);
    bump.stage = pwb::domain::DataStage::Raw;
    bump.staged = {staged_edit2, std::nullopt, "las"};
    bump.run_id = manual2.run_id;
    bump.version_name = "curve splice correction";
    auto bumped = session.value().coordinator().commit(
        bump, session.value().document());
    PWB_CHECK(bumped.is_ok());
    const std::string main_log_v2 = bumped.value().new_version_id.str();
    PWB_CHECK(bumped.value().version_number == 2);
    const std::string tops_v3 = main_log_v2;  // reopen guard reuses the id

    // (16) save.
    auto saved = session.value().manager().save(session.value().document());
    PWB_CHECK(saved.is_ok());

    // (12)(13)(14)(15) stale + explain + impact + usage over a snapshot.
    {
        auto snapshot = session.value().repository().open_read_only();
        PWB_CHECK(snapshot.is_ok());
        pwb::catalog::DocumentIndex index(snapshot.value());

        // (12) downstream stale: tops v2's successor evolution makes the
        // intermediate/facies chain stale (their ancestor asset's current
        // moved to v3).
        pwb::catalog::ImpactService impact(snapshot.value(), index);
        auto [is_stale, reason] = impact.is_stale(intermediate_version);
        PWB_CHECK(is_stale);
        PWB_CHECK(!reason.empty());

        // (13) explain the intermediate: producing run + lineage + entity.
        pwb::catalog::ExplainService explain(snapshot.value(), index);
        std::vector<pwb::catalog::ImpactService::EntityLink> entity_links;
        for (const auto& link :
             pwb::data::links_for_entity(root, "well", "well_fab000000001")) {
            entity_links.push_back({"well", link.entity_id, link.asset_id});
        }
        auto explanation = explain.explain_version(intermediate_version,
                                                   &entity_links);
        PWB_CHECK(explanation.is_ok());
        bool saw_well = false;
        for (const auto& [type, id] : explanation.value().entities) {
            if (type == "well" && !id.empty()) saw_well = true;
        }
        PWB_CHECK(saw_well);

        // (14) delete impact of the intermediate.
        auto impact_result = impact.delete_impact(
            intermediate_version, std::nullopt, &entity_links);
        PWB_CHECK(!impact_result.live_descendants.empty());

        // (15) usage refs: the derived version consumes the intermediate;
        // related runs flow through the workspace source.
        auto upstream = impact.upstream_impact(derived_version);
        bool saw_intermediate = false;
        for (const auto& id : upstream.ancestor_version_ids) {
            if (id == intermediate_version) saw_intermediate = true;
        }
        PWB_CHECK(saw_intermediate);
    }

    // Workspace view with the repository-backed source: slots + stale.
    {
        pwb::data::RepositoryWorkspaceSource source(
            session.value().repository().path(),
            fx.project_file.parent_path());
        pwb::data::EntityWorkspaceService workspace(root, &source);
        auto view = workspace.well_view("well_fab000000001", true);
        PWB_CHECK(view.has_value());
        PWB_CHECK(!view->stale_items.empty());
        PWB_CHECK(view->intermediate_count == 1);
        bool saw_intermediate_asset = false, saw_facies = false;
        for (const auto& slot : view->role_slots) {
            for (const auto& member : slot.members) {
                if (member.asset_id == intermediate_asset) {
                    saw_intermediate_asset = true;
                    PWB_CHECK(member.stage == "intermediate");
                }
                if (member.bundle) saw_facies = true;
            }
        }
        PWB_CHECK(saw_intermediate_asset);
        auto index_entries = workspace.well_index(true);
        PWB_CHECK(index_entries.size() == 1);
        PWB_CHECK(index_entries[0].stale_count > 0);
        PWB_CHECK(index_entries[0].role_fill.count("well_log") == 1);
    }

    // Appendix: duplicate ingest — re-running the plan over the same files
    // proposes duplicates, not a second copy.
    {
        auto catalog_doc = session.value().repository().open_read_only();
        auto plan = pwb::data::build_ingest_plan(
            fx.incoming, session.value().document(),
            {.preferred_only = true, .catalog = &catalog_doc.value()});
        int duplicates = 0;
        for (const auto& item : plan.items) {
            if (!item.duplicate_of_version.empty()) ++duplicates;
        }
        PWB_CHECK(duplicates == 4);
    }

    // (17)(18) close → reopen: identity/version/member/lineage preserved.
    const std::string reopen_tops_v3 = tops_v3;
    const std::string reopen_intermediate = intermediate_version;
    const std::string reopen_derived = derived_version;
    session = pwb::data::WritableSession::open(fx.project_file);  // close+open
    PWB_CHECK(session.is_ok());
    {
        Json& reopened = session.value().document().root();
        auto links2 = pwb::data::links_for_entity(reopened, "well",
                                                  "well_fab000000001");
        PWB_CHECK(links2.size() >= 5);
        std::map<std::string, pwb::data::EntityLinkView> by_asset2;
        for (const auto& link : links2) by_asset2[link.asset_id] = link;
        PWB_CHECK(by_asset2.count(sonic_log) == 1);
        PWB_CHECK(by_asset2[sonic_log].ordinal == 1);

        auto snapshot = session.value().repository().open_read_only();
        PWB_CHECK(snapshot.is_ok());
        pwb::catalog::DocumentIndex index(snapshot.value());
        const auto* tops_v3_row = index.version(reopen_tops_v3);
        PWB_CHECK(tops_v3_row != nullptr);
        PWB_CHECK(tops_v3_row->version_number == 2);
        // lineage chain: derived → intermediate → (normalize input) is
        // intact through persistence.
        pwb::catalog::ImpactService impact(snapshot.value(), index);
        auto upstream = impact.upstream_impact(reopen_derived);
        bool preserved = false;
        for (const auto& id : upstream.ancestor_version_ids) {
            if (id == reopen_intermediate) preserved = true;
        }
        PWB_CHECK(preserved);
        // The manual_edit run rows survived.
        const pwb::catalog::DataRun* manual_row = nullptr;
        for (const auto& run : snapshot.value().runs) {
            if (run.id == manual.run_id) manual_row = &run;
        }
        PWB_CHECK(manual_row != nullptr);
        PWB_CHECK(manual_row->operation == "manual_edit");
        PWB_CHECK(!manual_row->input_ports.empty());
    }

    // Appendix: missing-payload probe — remove a managed payload, the
    // bounded first-rung probe flags the asset.
    {
        auto snapshot = session.value().repository().open_read_only();
        std::string derived_path;
        for (const auto& version : snapshot.value().versions) {
            if (version.id.str() == derived_version) derived_path = version.path;
        }
        const fs::path payload = fx.project_file.parent_path() / derived_path;
        std::error_code ec;
        const bool removed = fs::remove(payload, ec);
        PWB_CHECK(removed);
        pwb::data::RepositoryWorkspaceSource source(
            session.value().repository().path(),
            fx.project_file.parent_path());
        auto missing = source.probe_missing_sources({derived.value().asset_id.str()});
        PWB_CHECK(std::find(missing.begin(), missing.end(),
                            derived.value().asset_id.str()) !=
                  missing.end());
    }
}
