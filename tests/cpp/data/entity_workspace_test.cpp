// data.entity_workspace — V14-DATA-LINEAGE entity workspace read model
// (catalog/entity_views.py parity): the stale-free well index (structural
// ZERO-catalog-read proof via a throwing source), stale attribution through
// the nearest changed ancestor, survey index counts, per-well slot assembly
// (registry order, primary/ordinal/name member sort, unknown + unresolved
// handling, stage rollups), and the honest-degrade paths (null catalog,
// missing store).
#include "pwb_test.hpp"

#include "pwb/data/entity_workspace.hpp"
#include "pwb/data/role_registry.hpp"
#include "pwb/domain/json.hpp"

#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using pwb::domain::Json;
using pwb::data::AssetCatalogSummary;
using pwb::data::EntityDataView;
using pwb::data::RoleSlot;
using pwb::data::StaleLite;
using pwb::data::WorkingCopyLite;

Json well_node(const std::string& id, const std::string& name,
               const std::string& uwi = "") {
    return Json{{"id", id}, {"name", name}, {"uwi", uwi}};
}

Json link_node(const std::string& entity_type, const std::string& entity_id,
               const std::string& asset_id, const std::string& role,
               bool is_primary = false, bool unresolved = false,
               int ordinal = 0) {
    return Json{{"id", "link_" + entity_id + "_" + role + "_" + asset_id},
                {"entity_type", entity_type},
                {"entity_id", entity_id},
                {"asset_id", asset_id},
                {"role", role},
                {"is_primary", is_primary},
                {"unresolved", unresolved},
                {"ordinal", ordinal}};
}

AssetCatalogSummary asset(const std::string& name, const std::string& type,
                          const std::string& stage, int version_count = 1,
                          const std::string& format = "",
                          bool bundle = false, bool trashed = false) {
    AssetCatalogSummary summary;
    summary.name = name;
    summary.type = type;
    summary.current_version_id = "ver_" + name;
    summary.version_count = version_count;
    summary.stage = stage;
    summary.format = format;
    summary.bundle = bundle;
    summary.trashed = trashed;
    return summary;
}

// Programmable fake over the catalog seam.
class FakeSource : public pwb::data::WorkspaceCatalogSource {
public:
    std::map<std::string, AssetCatalogSummary> assets;
    std::vector<WorkingCopyLite> working_copies;
    std::vector<StaleLite> entity_stale;
    std::vector<StaleLite> stale_all;
    std::vector<std::string> runs;
    std::set<std::string> missing_sources;

    std::map<std::string, AssetCatalogSummary> resolve_assets(
        const std::vector<std::string>& asset_ids) override {
        std::map<std::string, AssetCatalogSummary> found;
        for (const auto& id : asset_ids) {
            auto it = assets.find(id);
            if (it != assets.end()) found.emplace(id, it->second);
        }
        return found;
    }
    std::vector<WorkingCopyLite> list_working_copies() override {
        return working_copies;
    }
    std::vector<StaleLite> entity_staleness(
        const std::vector<pwb::data::EntityLinkView>&) override {
        return entity_stale;
    }
    std::vector<StaleLite> downstream_stale_all() override {
        return stale_all;
    }
    std::vector<std::string> related_runs(
        const std::vector<std::string>&) override {
        return runs;
    }
    std::vector<std::string> probe_missing_sources(
        const std::vector<std::string>& asset_ids) override {
        std::vector<std::string> missing;
        for (const auto& id : asset_ids) {
            if (missing_sources.count(id) != 0) missing.push_back(id);
        }
        return missing;
    }
};

// Structural proof source: any call is a bug in the layer under test.
class ThrowingSource : public pwb::data::WorkspaceCatalogSource {
public:
    std::map<std::string, AssetCatalogSummary> resolve_assets(
        const std::vector<std::string>&) override {
        throw std::runtime_error("well_index(false) must not read assets");
    }
    std::vector<WorkingCopyLite> list_working_copies() override {
        throw std::runtime_error("well_index(false) must not read copies");
    }
    std::vector<StaleLite> entity_staleness(
        const std::vector<pwb::data::EntityLinkView>&) override {
        throw std::runtime_error("well_index(false) must not read staleness");
    }
    std::vector<StaleLite> downstream_stale_all() override {
        throw std::runtime_error("well_index(false) must not read stale all");
    }
    std::vector<std::string> related_runs(
        const std::vector<std::string>&) override {
        throw std::runtime_error("well_index(false) must not read runs");
    }
    std::vector<std::string> probe_missing_sources(
        const std::vector<std::string>&) override {
        throw std::runtime_error("well_index(false) must not probe sources");
    }
};

StaleLite stale(const std::string& version_id, const std::string& asset_id,
                const std::string& ancestor_asset_id) {
    StaleLite item;
    item.version_id = version_id;
    item.asset_id = asset_id;
    item.reason = "ancestor_changed";
    item.nearest_changed_ancestor_asset_id = ancestor_asset_id;
    return item;
}

const RoleSlot* slot_for(const EntityDataView& view, const std::string& role) {
    for (const auto& slot : view.slots) {
        if (slot.role == role) return &slot;
    }
    return nullptr;
}

}  // namespace

// ---- index layer ---------------------------------------------------------------

PWB_TEST(well_index_without_stale_never_touches_the_catalog) {
    Json root = Json::object();
    root["wells"] = Json::array({well_node("W1", "Alpha 1", "100/1-1"),
                                 well_node("W2", "Beta 2"),
                                 well_node("W3", "Gamma 3")});
    Json links = Json::array();
    links.push_back(link_node("well", "W1", "a1", "well_log"));
    links.push_back(link_node("well", "W1", "a2", "well_log", false, true));
    links.push_back(link_node("well", "W1", "a3", "tops"));
    links.push_back(link_node("well", "W2", "a4", "well_head", true));
    links.push_back(link_node("seismic_survey", "S1", "a1",
                              "seismic_volume"));  // wrong entity type
    links.push_back(link_node("well", "W9", "a5",
                              "core"));  // unknown well → skipped
    root["entity_asset_links"] = std::move(links);

    ThrowingSource thrower;  // any catalog call fails the test by crash
    const pwb::data::EntityWorkspaceService service(root, &thrower);
    const auto entries = service.well_index(false);
    PWB_CHECK(entries.size() == 3);

    PWB_CHECK(entries[0].entity_id == "W1");
    PWB_CHECK(entries[0].name == "Alpha 1");
    PWB_CHECK(entries[0].uwi == "100/1-1");
    PWB_CHECK((entries[0].role_fill ==
               std::map<std::string, int>{{"well_log", 2}, {"tops", 1}}));
    PWB_CHECK(entries[0].unresolved_count == 1);
    PWB_CHECK(entries[0].stale_count == 0);

    PWB_CHECK(entries[1].entity_id == "W2");
    PWB_CHECK((entries[1].role_fill ==
               std::map<std::string, int>{{"well_head", 1}}));
    PWB_CHECK(entries[1].unresolved_count == 0);

    PWB_CHECK(entries[2].entity_id == "W3");
    PWB_CHECK(entries[2].role_fill.empty());
    PWB_CHECK(entries[2].unresolved_count == 0);
    PWB_CHECK(entries[2].stale_count == 0);
}

PWB_TEST(well_index_with_stale_attributes_through_nearest_ancestor) {
    Json root = Json::object();
    root["wells"] = Json::array({well_node("W1", "Alpha"), well_node("W2",
                                                                     "Beta"),
                                 well_node("W3", "Gamma")});
    Json links = Json::array();
    links.push_back(link_node("well", "W1", "a1", "well_log"));
    links.push_back(link_node("well", "W2", "a2", "tops"));
    root["entity_asset_links"] = std::move(links);

    FakeSource fake;
    // Two stale items descend from assets hanging off a1 (the changed
    // ancestor maps onto W1 through the link); one item has NO ancestor
    // and maps by its own asset id a2 → W2; one maps nowhere.
    fake.stale_all = {stale("v1", "a9", "a1"), stale("v2", "a10", "a1"),
                      stale("v3", "a2", ""), stale("v4", "a404", "zz")};

    const pwb::data::EntityWorkspaceService service(root, &fake);
    const auto entries = service.well_index(true);
    PWB_CHECK(entries.size() == 3);
    PWB_CHECK(entries[0].stale_count == 2);  // via ancestor a1 → W1
    PWB_CHECK(entries[1].stale_count == 1);  // own asset a2 → W2
    PWB_CHECK(entries[2].stale_count == 0);  // unlinked well
    PWB_CHECK((entries[0].role_fill ==
               std::map<std::string, int>{{"well_log", 1}}));
}

PWB_TEST(survey_index_counts_roles_per_survey) {
    Json root = Json::object();
    root["seismic_surveys"] = Json::array({Json{{"id", "S1"},
                                                {"name", "East 3D"}},
                                           Json{{"id", "S2"},
                                                {"name", "West 2D"}}});
    Json links = Json::array();
    links.push_back(link_node("seismic_survey", "S1", "a1", "seismic_volume",
                              true));
    links.push_back(link_node("seismic_survey", "S1", "a2", "horizon"));
    links.push_back(link_node("seismic_survey", "S1", "a3", "horizon"));
    links.push_back(link_node("seismic_survey", "S2", "a4", "velocity"));
    links.push_back(link_node("well", "W1", "a4", "well_log"));  // ignored
    root["entity_asset_links"] = std::move(links);

    FakeSource fake;
    const pwb::data::EntityWorkspaceService service(root, &fake);
    const auto entries = service.survey_index();
    PWB_CHECK(entries.size() == 2);
    PWB_CHECK(entries[0].entity_id == "S1");
    PWB_CHECK(entries[0].name == "East 3D");
    PWB_CHECK(entries[0].uwi.empty());
    PWB_CHECK((entries[0].role_fill ==
               std::map<std::string, int>{{"seismic_volume", 1},
                                          {"horizon", 2}}));
    PWB_CHECK(entries[1].entity_id == "S2");
    PWB_CHECK((entries[1].role_fill ==
               std::map<std::string, int>{{"velocity", 1}}));
}

// ---- per-entity views ----------------------------------------------------------

PWB_TEST(well_view_assembles_slots_members_and_rollups) {
    Json root = Json::object();
    root["wells"] = Json::array({well_node("W1", "Alpha 1", "100/1-1")});
    Json links = Json::array();
    // Two logs: name says A first, ordinal says Z first — ordinal wins.
    links.push_back(link_node("well", "W1", "log_z", "well_log", false,
                              false, 1));
    links.push_back(link_node("well", "W1", "log_a", "well_log", false,
                              false, 2));
    // Tops: primary member must lead its slot.
    links.push_back(link_node("well", "W1", "tops_main", "tops", true, false,
                              0));
    links.push_back(link_node("well", "W1", "tops_hist", "tops"));
    // Unknown asset on an unresolved link → honest 未注册资产 row.
    links.push_back(link_node("well", "W1", "ghost", "trajectory", false,
                              true));
    // Known asset on an unresolved link → unresolved list of its slot.
    links.push_back(link_node("well", "W1", "qc_note", "qc", false, true));
    root["entity_asset_links"] = std::move(links);

    FakeSource fake;
    fake.assets["log_z"] = asset("Z-first log", "well_log", "derived", 3,
                                 "las");
    fake.assets["log_a"] = asset("A-second log", "well_log",
                                 "intermediate", 1, "las", true);
    fake.assets["tops_main"] = asset("Main tops", "tops", "output", 2, "csv");
    fake.assets["tops_hist"] = asset("Historical tops", "tops", "raw", 5);
    fake.assets["qc_note"] = asset("QC note", "qc", "raw", 1);
    fake.runs = {"run_001", "run_002"};

    WorkingCopyLite member_copy;
    member_copy.working_id = "work_1";
    member_copy.asset_id = "log_a";
    member_copy.state = "checked_out";
    fake.working_copies.push_back(member_copy);
    WorkingCopyLite primary_copy;
    primary_copy.working_id = "work_2";
    primary_copy.asset_id = "tops_main";
    primary_copy.state = "checked_out";
    fake.working_copies.push_back(primary_copy);
    WorkingCopyLite foreign_copy;  // different entity → filtered out
    foreign_copy.working_id = "work_3";
    foreign_copy.asset_id = "unrelated_asset";
    fake.working_copies.push_back(foreign_copy);

    fake.missing_sources = {"tops_main", "unrelated_asset"};

    const pwb::data::EntityWorkspaceService service(root, &fake);
    const auto view = service.well_view("W1");
    PWB_CHECK(view.has_value());
    PWB_CHECK(view->entity_type == "well");
    PWB_CHECK(view->entity_id == "W1");
    PWB_CHECK(view->name == "Alpha 1");
    PWB_CHECK(view->uwi == "100/1-1");

    // Slots in registry order (full well vocabulary, empty slots included).
    PWB_CHECK(view->slots.size() == 9);
    const std::vector<std::string> roles = {
        "well_head", "well_log", "trajectory", "tops", "time_depth", "core",
        "interpretation", "qc", "other"};
    for (std::size_t i = 0; i < roles.size(); ++i) {
        PWB_CHECK(view->slots[i].role == roles[i]);
    }
    PWB_CHECK(view->slots[1].display == "测井曲线");
    PWB_CHECK(view->slots[3].display == "分层顶");

    // well_log members sorted (is_primary, ordinal, name): ordinal 1 wins
    // over the alphabetically-first name.
    const RoleSlot* log_slot = slot_for(*view, "well_log");
    PWB_CHECK(log_slot != nullptr);
    PWB_CHECK(log_slot->members.size() == 2);
    PWB_CHECK(log_slot->unresolved.empty());
    PWB_CHECK(log_slot->members[0].name == "Z-first log");
    PWB_CHECK(log_slot->members[0].ordinal == 1);
    PWB_CHECK(log_slot->members[1].name == "A-second log");
    PWB_CHECK(log_slot->members[1].ordinal == 2);
    // Catalog fields pass through to the summary rows.
    PWB_CHECK(log_slot->members[0].version_count == 3);
    PWB_CHECK(log_slot->members[0].stage == "derived");
    PWB_CHECK(log_slot->members[0].format == "las");
    PWB_CHECK(log_slot->members[0].current_version_id == "ver_Z-first log");
    PWB_CHECK(!log_slot->members[0].bundle);
    PWB_CHECK(!log_slot->members[0].trashed);
    PWB_CHECK(log_slot->members[1].bundle);
    PWB_CHECK(!log_slot->members[1].unresolved);

    // Primary member leads its slot even with ordinal 0 against another 0.
    const RoleSlot* tops_slot = slot_for(*view, "tops");
    PWB_CHECK(tops_slot != nullptr);
    PWB_CHECK(tops_slot->members.size() == 2);
    PWB_CHECK(tops_slot->members[0].is_primary);
    PWB_CHECK(tops_slot->members[0].name == "Main tops");
    PWB_CHECK(!tops_slot->members[1].is_primary);
    PWB_CHECK(tops_slot->members[1].name == "Historical tops");

    // Unknown asset surfaces as an honest unresolved row with the zh
    // placeholder name; the known-but-unresolved link stays in the
    // unresolved list of its own slot.
    const RoleSlot* trajectory_slot = slot_for(*view, "trajectory");
    PWB_CHECK(trajectory_slot != nullptr);
    PWB_CHECK(trajectory_slot->members.empty());
    PWB_CHECK(trajectory_slot->unresolved.size() == 1);
    PWB_CHECK(trajectory_slot->unresolved[0].name ==
              "<未注册资产 ghost>");
    PWB_CHECK(trajectory_slot->unresolved[0].unresolved);
    PWB_CHECK(trajectory_slot->unresolved[0].type == "unknown");

    const RoleSlot* qc_slot = slot_for(*view, "qc");
    PWB_CHECK(qc_slot != nullptr);
    PWB_CHECK(qc_slot->members.empty());
    PWB_CHECK(qc_slot->unresolved.size() == 1);
    PWB_CHECK(qc_slot->unresolved[0].name == "QC note");
    PWB_CHECK(qc_slot->unresolved[0].unresolved);

    // Stage rollups from MEMBER stages only (unresolved rows excluded).
    PWB_CHECK(view->intermediate_count == 1);  // A-second log
    PWB_CHECK(view->derived_count == 1);       // Z-first log
    PWB_CHECK(view->output_count == 1);        // Main tops

    // Related runs, filtered uncommitted edits, bounded missing probe.
    PWB_CHECK(view->related_run_ids.size() == 2);
    PWB_CHECK(view->related_run_ids[0] == "run_001");
    PWB_CHECK(view->related_run_ids[1] == "run_002");
    PWB_CHECK(view->uncommitted_edits.size() == 2);
    PWB_CHECK(view->uncommitted_edits[0].working_id == "work_1");
    PWB_CHECK(view->uncommitted_edits[1].working_id == "work_2");
    PWB_CHECK(view->missing_source_asset_ids.size() == 1);
    PWB_CHECK(view->missing_source_asset_ids[0] == "tops_main");

    // with_stale defaults to false: no stale items were requested.
    PWB_CHECK(view->stale_items.empty());
    PWB_CHECK(view->stale_count() == 0);
}

PWB_TEST(well_view_unknown_id_and_survey_view) {
    Json root = Json::object();
    root["wells"] = Json::array({well_node("W1", "Alpha")});
    root["seismic_surveys"] = Json::array({Json{{"id", "S1"},
                                                {"name", "East 3D"}}});
    Json links = Json::array();
    links.push_back(link_node("seismic_survey", "S1", "sv1",
                              "seismic_volume", true));
    links.push_back(link_node("seismic_survey", "S1", "hz1", "horizon"));
    root["entity_asset_links"] = std::move(links);

    FakeSource fake;
    fake.assets["sv1"] = asset("East volume", "seismic", "raw", 2, "sgy");
    fake.assets["hz1"] = asset("Top horizon", "horizon", "derived", 1);

    const pwb::data::EntityWorkspaceService service(root, &fake);
    PWB_CHECK(!service.well_view("W404").has_value());
    PWB_CHECK(!service.survey_view("S404").has_value());
    // A well id asked through the survey view does not resolve either.
    PWB_CHECK(!service.survey_view("W1").has_value());

    const auto view = service.survey_view("S1");
    PWB_CHECK(view.has_value());
    PWB_CHECK(view->entity_type == "seismic_survey");
    PWB_CHECK(view->entity_id == "S1");
    PWB_CHECK(view->name == "East 3D");
    PWB_CHECK(view->uwi.empty());
    // Full survey vocabulary in registry order.
    PWB_CHECK(view->slots.size() == 7);
    const std::vector<std::string> roles = {
        "seismic_volume", "geometry", "velocity", "horizon", "fault",
        "interpretation", "other"};
    for (std::size_t i = 0; i < roles.size(); ++i) {
        PWB_CHECK(view->slots[i].role == roles[i]);
    }
    const RoleSlot* volume_slot = slot_for(*view, "seismic_volume");
    PWB_CHECK(volume_slot != nullptr);
    PWB_CHECK(volume_slot->members.size() == 1);
    PWB_CHECK(volume_slot->members[0].is_primary);
    PWB_CHECK(volume_slot->members[0].name == "East volume");
    PWB_CHECK(volume_slot->members[0].stage == "raw");
    PWB_CHECK(volume_slot->members[0].format == "sgy");
    PWB_CHECK(volume_slot->members[0].version_count == 2);
    const RoleSlot* horizon_slot = slot_for(*view, "horizon");
    PWB_CHECK(horizon_slot != nullptr);
    PWB_CHECK(horizon_slot->members.size() == 1);
    PWB_CHECK(horizon_slot->members[0].name == "Top horizon");
    PWB_CHECK(view->derived_count == 1);
}

PWB_TEST(null_catalog_degrades_to_unresolved_placeholder_names) {
    Json root = Json::object();
    root["wells"] = Json::array({well_node("W1", "Alpha")});
    Json links = Json::array();
    links.push_back(link_node("well", "W1", "a1", "well_log", true));
    links.push_back(link_node("well", "W1", "a2", "tops"));
    root["entity_asset_links"] = std::move(links);

    const pwb::data::EntityWorkspaceService service(root, nullptr);
    const auto view = service.well_view("W1");
    PWB_CHECK(view.has_value());
    PWB_CHECK(view->slots.size() == 9);

    const RoleSlot* log_slot = slot_for(*view, "well_log");
    PWB_CHECK(log_slot != nullptr);
    PWB_CHECK(log_slot->members.size() == 1);
    PWB_CHECK(log_slot->members[0].name == "<未注册资产 a1>");
    PWB_CHECK(log_slot->members[0].unresolved);
    PWB_CHECK(log_slot->members[0].type == "unknown");
    PWB_CHECK(log_slot->members[0].is_primary);
    PWB_CHECK(log_slot->members[0].current_version_id.empty());
    PWB_CHECK(log_slot->members[0].version_count == 0);

    const RoleSlot* tops_slot = slot_for(*view, "tops");
    PWB_CHECK(tops_slot != nullptr);
    PWB_CHECK(tops_slot->members.size() == 1);
    PWB_CHECK(tops_slot->members[0].name == "<未注册资产 a2>");
    PWB_CHECK(tops_slot->members[0].unresolved);

    // Honest empty degrade for the catalog-backed extras.
    PWB_CHECK(view->related_run_ids.empty());
    PWB_CHECK(view->missing_source_asset_ids.empty());
    PWB_CHECK(view->uncommitted_edits.empty());
    PWB_CHECK(view->intermediate_count == 0);
    PWB_CHECK(view->derived_count == 0);
    PWB_CHECK(view->output_count == 0);

    // The index layer still works over a null catalog.
    const auto entries = service.well_index(false);
    PWB_CHECK(entries.size() == 1);
    PWB_CHECK((entries[0].role_fill ==
               std::map<std::string, int>{{"well_log", 1}, {"tops", 1}}));
}

PWB_TEST(repository_source_with_missing_store_degrades_to_empty) {
    Json root = Json::object();
    root["wells"] = Json::array({well_node("W1", "Alpha")});
    root["entity_asset_links"] =
        Json::array({link_node("well", "W1", "a1", "well_log")});

    pwb::data::RepositoryWorkspaceSource source(std::filesystem::path{},
                                                std::filesystem::path{});
    const pwb::data::EntityWorkspaceService service(root, &source);
    const auto view = service.well_view("W1");
    PWB_CHECK(view.has_value());
    const RoleSlot* log_slot = slot_for(*view, "well_log");
    PWB_CHECK(log_slot != nullptr);
    PWB_CHECK(log_slot->members.size() == 1);
    PWB_CHECK(log_slot->members[0].name == "<未注册资产 a1>");
    PWB_CHECK(log_slot->members[0].unresolved);
    PWB_CHECK(view->related_run_ids.empty());
    PWB_CHECK(view->uncommitted_edits.empty());
    PWB_CHECK(view->stale_items.empty());
}
