// data.entity_domain_ops — V14-DATA-LINEAGE domain layer: the role
// registry (project/roles.py parity), entity↔asset link ordinals + read
// views, and the entity removal/prune family (project/domain.py
// remove_links_for_asset / remove_well_entity /
// remove_asset_links_and_prune_reference_wells; schema normalization of
// pre-V14 link rows lacking `ordinal`).
#include "pwb_test.hpp"

#include "pwb/data/entity_identity.hpp"
#include "pwb/data/role_registry.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/project/document.hpp"

#include <algorithm>
#include <string>
#include <utility>
#include <vector>

namespace {

using pwb::domain::Json;

Json well_row(const std::string& id, const std::string& name,
              const std::string& spatial_scope = "workarea") {
    Json row = Json::object();
    row["id"] = id;
    row["name"] = name;
    row["spatial_scope"] = spatial_scope;
    return row;
}

Json link_row(const std::string& entity_type, const std::string& entity_id,
              const std::string& asset_id, const std::string& role,
              bool is_primary = false, bool unresolved = false,
              int ordinal = 0) {
    Json row = Json::object();
    row["id"] = "link_" + entity_id + "_" + role + "_" + asset_id;
    row["entity_type"] = entity_type;
    row["entity_id"] = entity_id;
    row["asset_id"] = asset_id;
    row["role"] = role;
    row["is_primary"] = is_primary;
    row["unresolved"] = unresolved;
    row["ordinal"] = ordinal;
    return row;
}

// Wells W1/W2 + survey S1 + a geological entity link; mixed entity types
// so the read-view filters and the prune guards are exercised together.
Json sample_project() {
    Json root = Json::object();
    root["wells"] = Json::array({well_row("W1", "Alpha 1"),
                                 well_row("W2", "Beta 2")});
    Json surveys = Json::array();
    Json survey = Json::object();
    survey["id"] = "S1";
    survey["name"] = "Survey One";
    surveys.push_back(std::move(survey));
    root["seismic_surveys"] = std::move(surveys);

    Json links = Json::array();
    links.push_back(link_row("well", "W1", "a1", "well_log", true, false, 4));
    links.push_back(link_row("well", "W1", "a2", "tops"));
    links.push_back(link_row("well", "W2", "a1", "well_log"));
    links.push_back(link_row("seismic_survey", "S1", "a1", "horizon"));
    links.push_back(link_row("geological_entity", "G1", "a3", "tops"));
    root["entity_asset_links"] = std::move(links);
    return root;
}

// Prune-fixture tree: W1 reference, W2 workarea, W3 reference; links
// W1-a1, W2-a1, W3-a2, W3-a3 (domain.py docstring scenario).
Json prune_project() {
    Json root = Json::object();
    root["wells"] = Json::array({well_row("W1", "Ref One", "reference"),
                                 well_row("W2", "Work Two", "workarea"),
                                 well_row("W3", "Ref Three", "reference")});
    Json links = Json::array();
    links.push_back(link_row("well", "W1", "a1", "well_log"));
    links.push_back(link_row("well", "W2", "a1", "well_log"));
    links.push_back(link_row("well", "W3", "a2", "tops"));
    links.push_back(link_row("well", "W3", "a3", "core"));
    root["entity_asset_links"] = std::move(links);
    return root;
}

std::vector<std::string> well_ids(const Json& root) {
    std::vector<std::string> ids;
    for (const auto& well : root["wells"]) {
        ids.push_back(well.value("id", std::string()));
    }
    return ids;
}

}  // namespace

// ---- role registry (roles.py) ------------------------------------------------

PWB_TEST(role_registry_vocabularies_match_roles_py_order) {
    // WELL_ROLES in declaration order — "other" last (roles.py:240).
    const std::vector<std::string_view> expected_well{
        "well_head", "well_log", "trajectory", "tops", "time_depth", "core",
        "interpretation", "qc", "other"};
    PWB_CHECK(pwb::data::well_roles() == expected_well);

    const std::vector<std::string_view> expected_survey{
        "seismic_volume", "geometry", "velocity", "horizon", "fault",
        "interpretation", "other"};
    PWB_CHECK(pwb::data::survey_roles() == expected_survey);

    const std::vector<std::string_view> expected_geological{
        "horizon", "tops", "fault", "other"};
    PWB_CHECK(pwb::data::geological_roles() == expected_geological);

    // Scoped vocabularies agree with the bare lookup helpers; unknown
    // entity types degrade to the {"other"} vocabulary, never empty.
    PWB_CHECK(pwb::data::roles_for_entity_type("well") == expected_well);
    PWB_CHECK(pwb::data::roles_for_entity_type("seismic_survey") ==
              expected_survey);
    PWB_CHECK(pwb::data::roles_for_entity_type("geological_entity") ==
              expected_geological);
    const std::vector<std::string_view> degraded{"other"};
    PWB_CHECK(pwb::data::roles_for_entity_type("mystery") == degraded);
}

PWB_TEST(role_definition_scoped_lookup_resolves_repeated_role_names) {
    // "tops" repeats across the well AND geological vocabularies — the
    // scoped index is the authority (well display 分层顶, geological 分层).
    const pwb::data::RoleDefinition* well_tops =
        pwb::data::role_definition("tops", "well");
    PWB_CHECK(well_tops != nullptr);
    PWB_CHECK(well_tops->display == "分层顶");
    PWB_CHECK(well_tops->applies_to("well"));
    PWB_CHECK(!well_tops->applies_to("geological_entity"));

    const pwb::data::RoleDefinition* geo_tops =
        pwb::data::role_definition("tops", "geological_entity");
    PWB_CHECK(geo_tops != nullptr);
    PWB_CHECK(geo_tops->display == "分层");
    PWB_CHECK(geo_tops->applies_to("geological_entity"));

    // Scoped lookup with an entity type the role does not belong to falls
    // back to the bare-role index (well vocabulary first in build order).
    const pwb::data::RoleDefinition* cross =
        pwb::data::role_definition("tops", "seismic_survey");
    PWB_CHECK(cross != nullptr);
    PWB_CHECK(cross->display == "分层顶");

    // Interpretation repeats too; well_log is ordered (ordinal meaningful).
    PWB_CHECK(pwb::data::role_definition("interpretation", "seismic_survey")
                  ->display == "调查解释");
    PWB_CHECK(pwb::data::role_definition("interpretation", "well")->display ==
              "井周解释");
    PWB_CHECK(pwb::data::role_definition("well_log")->ordered);
}

PWB_TEST(role_policies_table_truth) {
    // Every current role is 0..N — the multi-file well model is the
    // product-level contract (assert the whole table, not spot checks).
    for (auto role : pwb::data::well_roles()) {
        PWB_CHECK(pwb::data::cardinality_allows_multiple(role));
    }
    for (auto role : pwb::data::survey_roles()) {
        PWB_CHECK(pwb::data::cardinality_allows_multiple(role));
    }
    for (auto role : pwb::data::geological_roles()) {
        PWB_CHECK(pwb::data::cardinality_allows_multiple(role));
    }
    // The permissive fallback for unknown roles is also multi-allowing.
    PWB_CHECK(pwb::data::cardinality_allows_multiple("bogus"));

    // required_single primaries: well_head / time_depth / seismic_volume.
    PWB_CHECK(pwb::data::primary_required("well_head"));
    PWB_CHECK(pwb::data::primary_required("time_depth"));
    PWB_CHECK(pwb::data::primary_required("seismic_volume"));
    for (const char* role : {"well_log", "trajectory", "tops", "core",
                             "interpretation", "qc", "other", "geometry",
                             "velocity", "horizon", "fault", "bogus"}) {
        PWB_CHECK(!pwb::data::primary_required(role));
    }
}

PWB_TEST(role_lookup_unknown_roles_get_the_permissive_fallback) {
    PWB_CHECK(!pwb::data::known_role("bogus"));
    PWB_CHECK(pwb::data::known_role("well_log"));
    PWB_CHECK(pwb::data::known_role("seismic_volume"));
    PWB_CHECK(!pwb::data::known_role(""));

    const pwb::data::RoleDefinition* fallback =
        pwb::data::role_definition("bogus");
    PWB_CHECK(fallback != nullptr);
    PWB_CHECK(fallback->role == "other");
    PWB_CHECK(fallback->cardinality == "0..N");
    PWB_CHECK(fallback->primary_policy == "none");
    PWB_CHECK(fallback->display == "其他");

    // Display: registry zh label when present, role name otherwise
    // (roles.py `display or role`); unknown roles classify as 其他.
    PWB_CHECK(pwb::data::role_display("well_log") == "测井曲线");
    PWB_CHECK(pwb::data::role_display("tops", "geological_entity") == "分层");
    PWB_CHECK(pwb::data::role_display("bogus") == "其他");
}

// ---- link ordinals -----------------------------------------------------------

PWB_TEST(upsert_link_ordinal_stored_and_preserved_on_negative_update) {
    Json root = Json::object();
    const auto first = pwb::data::upsert_entity_asset_link(
        root, "well", "W1", "a1", "well_log", true, false, "", 7);
    PWB_CHECK(first.created);
    PWB_CHECK(first.changed);
    PWB_CHECK(first.index == 0);

    auto links = pwb::data::links_for_entity(root, "well", "W1");
    PWB_CHECK(links.size() == 1);
    PWB_CHECK(links[0].asset_id == "a1");
    PWB_CHECK(links[0].ordinal == 7);
    PWB_CHECK(links[0].is_primary);

    // ordinal < 0 on update = leave the stored value untouched.
    const auto second = pwb::data::upsert_entity_asset_link(
        root, "well", "W1", "a1", "well_log", true, false, "", -1);
    PWB_CHECK(!second.created);
    PWB_CHECK(second.index == 0);
    links = pwb::data::links_for_entity(root, "well", "W1");
    PWB_CHECK(links.size() == 1);
    PWB_CHECK(links[0].ordinal == 7);

    // A brand-new row with ordinal < 0 lands on the schema default 0.
    const auto fresh = pwb::data::upsert_entity_asset_link(
        root, "well", "W1", "a9", "core", false, false, "", -5);
    PWB_CHECK(fresh.created);
    links = pwb::data::links_for_entity(root, "well", "W1");
    PWB_CHECK(links.size() == 2);
    PWB_CHECK(links[1].role == "core");
    PWB_CHECK(links[1].ordinal == 0);
}

PWB_TEST(old_style_links_without_ordinal_read_as_zero) {
    // Pre-V14 documents have no `ordinal` on link rows — every reader must
    // surface the schema default without mutating the tree.
    Json root = Json::object();
    Json links = Json::array();
    Json legacy = Json::object();
    legacy["id"] = "l_legacy";
    legacy["entity_type"] = "well";
    legacy["entity_id"] = "W1";
    legacy["asset_id"] = "a1";
    legacy["role"] = "well_log";
    legacy["is_primary"] = true;
    links.push_back(std::move(legacy));
    root["entity_asset_links"] = std::move(links);

    const auto views = pwb::data::links_for_entity(root, "well", "W1");
    PWB_CHECK(views.size() == 1);
    PWB_CHECK(views[0].ordinal == 0);
    PWB_CHECK(views[0].is_primary);
    // The raw tree is untouched (read views never normalize in place).
    PWB_CHECK(!root["entity_asset_links"][0].contains("ordinal"));
}

PWB_TEST(schema_normalize_fills_link_ordinal_and_round_trips) {
    Json doc = Json::object();
    doc["schema_version"] = 1;
    doc["meta"] = Json{{"name", "OrdinalDoc"}};
    doc["coordinate"] = Json::object();
    doc["stratigraphy"] = Json::object();
    Json wells = Json::array();
    wells.push_back(Json{{"id", "W1"}, {"name", "Alpha"}});
    doc["wells"] = std::move(wells);

    Json links = Json::array();
    Json legacy = Json::object();  // no `ordinal` (pre-V14 shape)
    legacy["id"] = "l1";
    legacy["entity_type"] = "well";
    legacy["entity_id"] = "W1";
    legacy["asset_id"] = "a1";
    legacy["role"] = "well_log";
    legacy["is_primary"] = true;
    links.push_back(std::move(legacy));
    Json modern = Json::object();  // explicit ordinal survives verbatim
    modern["id"] = "l2";
    modern["entity_type"] = "well";
    modern["entity_id"] = "W1";
    modern["asset_id"] = "a2";
    modern["role"] = "well_log";
    modern["ordinal"] = 3;
    links.push_back(std::move(modern));
    doc["entity_asset_links"] = std::move(links);

    pwb::domain::DiagnosticList diagnostics;
    auto parsed = pwb::project::ProjectDocument::parse(doc.dump(),
                                                       diagnostics);
    PWB_CHECK(parsed.is_ok());
    const Json& root = parsed.value().root();
    PWB_CHECK(root["entity_asset_links"].size() == 2);
    PWB_CHECK(root["entity_asset_links"][0].contains("ordinal"));
    PWB_CHECK(root["entity_asset_links"][0].value("ordinal", -99) == 0);
    PWB_CHECK(root["entity_asset_links"][1].value("ordinal", -99) == 3);

    // Round-trip: serialize + reparse keeps the normalized ordinals.
    pwb::domain::DiagnosticList second_diagnostics;
    auto reparsed = pwb::project::ProjectDocument::parse(
        root.dump(), second_diagnostics);
    PWB_CHECK(reparsed.is_ok());
    const Json& again = reparsed.value().root();
    PWB_CHECK(again["entity_asset_links"][0].value("ordinal", -99) == 0);
    PWB_CHECK(again["entity_asset_links"][1].value("ordinal", -99) == 3);
    // Full-array equality after serialize+reparse. nlohmann operator==
    // compares integer types by value (the normalize-filled default 0 is
    // number_integer in-memory but parses back as number_unsigned, which
    // the stricter json_semantically_equal flags as a type difference).
    PWB_CHECK(root["entity_asset_links"] == again["entity_asset_links"]);

    // And the normalized tree feeds the read views with ordinal 0.
    const auto views = pwb::data::links_for_entity(again, "well", "W1");
    PWB_CHECK(views.size() == 2);
    PWB_CHECK(views[0].ordinal == 0);
    PWB_CHECK(views[1].ordinal == 3);
}

// ---- link read views ----------------------------------------------------------

PWB_TEST(link_read_views_filter_by_entity_and_asset) {
    const Json root = sample_project();

    const auto well_links = pwb::data::links_for_entity(root, "well", "W1");
    PWB_CHECK(well_links.size() == 2);
    PWB_CHECK(well_links[0].asset_id == "a1");
    PWB_CHECK(well_links[0].role == "well_log");
    PWB_CHECK(well_links[0].ordinal == 4);
    PWB_CHECK(well_links[1].asset_id == "a2");
    PWB_CHECK(well_links[1].role == "tops");
    PWB_CHECK(pwb::data::links_for_entity(root, "well", "W9").empty());
    PWB_CHECK(pwb::data::links_for_entity(root, "seismic_survey", "W1")
                  .empty());

    // a1 is shared by W1 (well), W2 (well) and S1 (survey) — mixed types.
    const auto a1_links = pwb::data::links_for_asset(root, "a1");
    PWB_CHECK(a1_links.size() == 3);
    PWB_CHECK(a1_links[0].entity_id == "W1");
    PWB_CHECK(a1_links[1].entity_id == "W2");
    PWB_CHECK(a1_links[2].entity_type == "seismic_survey");
    PWB_CHECK(pwb::data::links_for_asset(root, "a_unused").empty());

    const auto pairs = pwb::data::entity_ids_for_asset(root, "a1");
    PWB_CHECK(pairs.size() == 3);
    PWB_CHECK(pairs[0] == std::make_pair(std::string("well"),
                                         std::string("W1")));
    PWB_CHECK(pairs[1] == std::make_pair(std::string("well"),
                                         std::string("W2")));
    PWB_CHECK(pairs[2] == std::make_pair(std::string("seismic_survey"),
                                         std::string("S1")));

    const auto well_only = pwb::data::entity_ids_for_asset(root, "a1",
                                                            "well");
    PWB_CHECK(well_only.size() == 2);
    PWB_CHECK(well_only[1].second == "W2");

    // Role-scoped asset ids (deduped across multi-links, roles.py order).
    const auto log_assets = pwb::data::asset_ids_for_entity(root, "well",
                                                            "W1",
                                                            "well_log");
    PWB_CHECK(log_assets.size() == 1);
    PWB_CHECK(log_assets[0] == "a1");
    const auto any_assets =
        pwb::data::asset_ids_for_entity(root, "well", "W1");
    PWB_CHECK(any_assets.size() == 2);
}

// ---- entity removal / pruning -------------------------------------------------

PWB_TEST(remove_well_entity_drops_well_and_only_its_links) {
    Json root = sample_project();
    const auto result = pwb::data::remove_well_entity(root, "W1");
    PWB_CHECK(result.removed_links == 2);
    PWB_CHECK(result.pruned_wells == 1);

    const auto ids = well_ids(root);
    PWB_CHECK(ids.size() == 1);
    PWB_CHECK(ids[0] == "W2");
    // W2's link and the survey/geological links survive untouched.
    const auto remaining = root["entity_asset_links"];
    PWB_CHECK(remaining.size() == 3);
    PWB_CHECK(remaining[0].value("entity_id", std::string()) == "W2");
    PWB_CHECK(remaining[1].value("entity_type", std::string()) ==
              "seismic_survey");
    PWB_CHECK(remaining[2].value("entity_type", std::string()) ==
              "geological_entity");

    // Empty id (and unknown id) are no-ops returning {0, 0}.
    const auto empty = pwb::data::remove_well_entity(root, "");
    PWB_CHECK(empty.removed_links == 0);
    PWB_CHECK(empty.pruned_wells == 0);
    const auto unknown = pwb::data::remove_well_entity(root, "W404");
    PWB_CHECK(unknown.removed_links == 0);
    PWB_CHECK(unknown.pruned_wells == 0);
    PWB_CHECK(root["wells"].size() == 1);
    PWB_CHECK(root["entity_asset_links"].size() == 3);
}

PWB_TEST(remove_asset_links_and_prune_reference_wells_drops_orphans) {
    Json root = prune_project();
    const auto result =
        pwb::data::remove_asset_links_and_prune_reference_wells(root, {"a1"});
    PWB_CHECK(result.removed_links == 2);  // W1-a1 + W2-a1
    PWB_CHECK(result.pruned_wells == 1);   // W1: reference, now unlinked

    const auto ids = well_ids(root);
    PWB_CHECK(ids.size() == 2);
    PWB_CHECK(ids[0] == "W2");  // workarea well survives unlinking
    PWB_CHECK(ids[1] == "W3");  // reference but untouched by a1 — survives
    const auto links = root["entity_asset_links"];
    PWB_CHECK(links.size() == 2);
    PWB_CHECK(links[0].value("entity_id", std::string()) == "W3");
    PWB_CHECK(links[1].value("entity_id", std::string()) == "W3");
}

PWB_TEST(remove_asset_links_keeps_reference_well_with_remaining_links) {
    // W3 keeps its a3 link when a2 is removed → not pruned even though it
    // is a touched reference well (domain.py still-linked guard).
    //
    // KNOWN DOMAIN BUG (entity_identity.cpp
    // remove_asset_links_and_prune_reference_wells): still_linked_well_ids
    // is built by iterating the moved-from `kept` local (the tree was
    // assigned via std::move(kept) just above), so it is always empty and
    // every touched reference well is pruned even while it still owns
    // links (data loss). The checks below fail until the domain fix.
    Json root = prune_project();
    const auto result =
        pwb::data::remove_asset_links_and_prune_reference_wells(root, {"a2"});
    if (result.pruned_wells != 0) {
        std::cout << "  DOMAIN BUG: removing a2 pruned "
                  << result.pruned_wells
                  << " still-linked reference well(s)\n";
    }
    PWB_CHECK(result.removed_links == 1);
    PWB_CHECK(result.pruned_wells == 0);
    PWB_CHECK(well_ids(root).size() == 3);
    PWB_CHECK(root["entity_asset_links"].size() == 3);
    PWB_CHECK(pwb::data::is_reference_well(root, "W3"));

    // Shared reference well: linked from a1 AND a9 — removing a1 leaves a9
    // so the well must survive.
    Json shared = prune_project();
    shared["wells"].push_back(well_row("W4", "Ref Shared", "reference"));
    shared["entity_asset_links"].push_back(
        link_row("well", "W4", "a9", "well_log"));
    shared["entity_asset_links"].push_back(
        link_row("well", "W4", "a1", "tops"));
    const auto shared_result =
        pwb::data::remove_asset_links_and_prune_reference_wells(shared,
                                                                {"a1"});
    PWB_CHECK(shared_result.removed_links == 3);  // W1, W2, W4 links on a1
    PWB_CHECK(shared_result.pruned_wells == 1);   // only W1 orphaned
    const auto survivors = well_ids(shared);
    PWB_CHECK(survivors.size() == 3);
    PWB_CHECK(std::find(survivors.begin(), survivors.end(), "W4") !=
              survivors.end());
    PWB_CHECK(!pwb::data::links_for_entity(shared, "well", "W4").empty());

    // Empty id list → {0, 0} no-op.
    const auto noop = pwb::data::remove_asset_links_and_prune_reference_wells(
        shared, {});
    PWB_CHECK(noop.removed_links == 0);
    PWB_CHECK(noop.pruned_wells == 0);
    const auto blank = pwb::data::remove_asset_links_and_prune_reference_wells(
        shared, {""});
    PWB_CHECK(blank.removed_links == 0);
    PWB_CHECK(blank.pruned_wells == 0);
}

PWB_TEST(remove_links_for_asset_drops_every_matching_link) {
    Json root = sample_project();
    // a1 is referenced by three links (two wells + one survey).
    //
    // KNOWN DOMAIN BUG (entity_identity.cpp remove_links_for_asset): the
    // return count is computed from the moved-from `kept` local after
    // `project_root[...] = std::move(kept)`, so it always reports
    // `before` (all links) instead of the removed count. The tree state
    // below is correct; the count assertion fails until the domain fix.
    const int removed = pwb::data::remove_links_for_asset(root, "a1");
    if (removed != 3) {
        std::cout << "  DOMAIN BUG: remove_links_for_asset returned "
                  << removed << ", expected 3 (moved-from kept counter)\n";
    }
    PWB_CHECK(removed == 3);
    PWB_CHECK(root["entity_asset_links"].size() == 2);
    PWB_CHECK(pwb::data::links_for_asset(root, "a1").empty());
    // Idempotent second sweep; unknown asset ids report zero.
    PWB_CHECK(pwb::data::remove_links_for_asset(root, "a1") == 0);
    PWB_CHECK(pwb::data::remove_links_for_asset(root, "a_missing") == 0);
    PWB_CHECK(root["entity_asset_links"].size() == 2);
}

PWB_TEST(is_reference_well_classifies_scope_and_missing_rows) {
    Json root = Json::object();
    Json wells = Json::array();
    wells.push_back(well_row("W1", "Ref", "reference"));
    wells.push_back(well_row("W2", "Work", "workarea"));
    Json unscoped = Json::object();  // no spatial_scope → workarea default
    unscoped["id"] = "W3";
    unscoped["name"] = "Legacy";
    wells.push_back(std::move(unscoped));
    root["wells"] = std::move(wells);

    PWB_CHECK(pwb::data::is_reference_well(root, "W1"));
    PWB_CHECK(!pwb::data::is_reference_well(root, "W2"));
    PWB_CHECK(!pwb::data::is_reference_well(root, "W3"));
    PWB_CHECK(!pwb::data::is_reference_well(root, "W404"));
    PWB_CHECK(!pwb::data::is_reference_well(root, ""));
}
