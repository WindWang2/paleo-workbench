// data.entity_workspace_scale — V14-DATA-LINEAGE entity workspace SCALE /
// STRUCTURAL contract (11-scale), on top of the behavioural coverage in
// entity_workspace_test.cpp.
//
//  1. Root index at 10k wells / 100k entity_asset_links with a THROWING
//     catalog source: well_index(false) is a pure project-tree walk — zero
//     catalog reads (structural proof), O(W+L), under a 2500 ms ceiling.
//  2. Expand-one-well is bounded: one well_view() issues exactly that well's
//     link count in batched point lookups (never the 100k store), and 50
//     expansions request exactly 50 * per-well links in total.
//  3. Project switch leaves no stale state: a second service over a second
//     document sees only that document's wells.
//  4. Late-generation guard: an index vector built before a mutation never
//     observes it (snapshot semantics), while a fresh index does.
#include "pwb_test.hpp"

#include "pwb/data/entity_workspace.hpp"
#include "pwb/data/role_registry.hpp"
#include "pwb/domain/json.hpp"

#include <chrono>
#include <cstddef>
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

// ---- synthetic corpus -------------------------------------------------------

constexpr int kWellCount = 10000;
constexpr int kLinksPerWell = 10;
constexpr int kTotalLinks = kWellCount * kLinksPerWell;
// ~5% of 10 links per well, rounded deterministically by the generator
// (ceil(10 * 0.05)) — the test computes the expectation from this constant,
// it never hard-codes a magic 1.
constexpr int kUnresolvedPerWell = 1;
constexpr long long kIndexBudgetMs = 2500;

// The generator cycles the well registry vocabulary across each well's links,
// so link #0..9 land on roles[0..9 % 9]: the first role appears twice, every
// other role once. Expected per-role fill is derived from that rule below.
std::vector<std::string> well_role_cycle() {
    std::vector<std::string> roles;
    for (const auto role : pwb::data::roles_for_entity_type("well")) {
        roles.emplace_back(role);
    }
    return roles;
}

std::string well_id_of(int index) {
    // well_00000 .. well_09999 (zero-padded so lexical order == numeric order).
    char buffer[32];
    std::snprintf(buffer, sizeof(buffer), "well_%05d", index);
    return std::string(buffer);
}

std::string well_name_of(int index) {
    char buffer[32];
    std::snprintf(buffer, sizeof(buffer), "Well-%05d", index);
    return std::string(buffer);
}

std::string well_uwi_of(int index) {
    char buffer[48];
    std::snprintf(buffer, sizeof(buffer), "UWI-%05d-X", index);
    return std::string(buffer);
}

Json scale_link_node(int well_index, int slot, int unresolved_per_well) {
    const std::vector<std::string> roles = well_role_cycle();
    const std::string role = roles[static_cast<std::size_t>(slot) %
                                   roles.size()];
    const std::string asset_id =
        "asset_" + well_id_of(well_index) + "_" + std::to_string(slot);
    Json link = Json::object();
    link["id"] = "link_" + asset_id;
    link["entity_type"] = "well";
    link["entity_id"] = well_id_of(well_index);
    link["asset_id"] = asset_id;
    link["role"] = role;
    link["is_primary"] = (slot == 0);
    // Deterministic ~5% unresolved spread: the FIRST `unresolved_per_well`
    // links of every well.
    link["unresolved"] = (slot < unresolved_per_well);
    link["ordinal"] = slot;
    return link;
}

// A synthetic project document: `well_count` wells, `links_per_well` links
// each (registry vocabulary cycled), `unresolved_per_well` of them unresolved.
Json scale_document(int well_count, int links_per_well,
                    int unresolved_per_well) {
    Json root = Json::object();
    Json wells = Json::array();
    for (int i = 0; i < well_count; ++i) {
        Json well = Json::object();
        well["id"] = well_id_of(i);
        well["name"] = well_name_of(i);
        well["uwi"] = well_uwi_of(i);
        wells.push_back(std::move(well));
    }
    root["wells"] = std::move(wells);

    Json links = Json::array();
    for (int i = 0; i < well_count; ++i) {
        for (int slot = 0; slot < links_per_well; ++slot) {
            links.push_back(scale_link_node(i, slot, unresolved_per_well));
        }
    }
    root["entity_asset_links"] = std::move(links);
    return root;
}

// Expected role → linked-asset count for one well of the synthetic corpus,
// derived from the generator's own rule (never hard-coded per role).
std::map<std::string, int> expected_role_fill() {
    std::map<std::string, int> fill;
    const std::vector<std::string> roles = well_role_cycle();
    for (int slot = 0; slot < kLinksPerWell; ++slot) {
        ++fill[roles[static_cast<std::size_t>(slot) % roles.size()]];
    }
    return fill;
}

// ---- catalog seams ----------------------------------------------------------

// Structural proof source: any call is a bug in the layer under test.
class ThrowingSource : public pwb::data::WorkspaceCatalogSource {
public:
    std::map<std::string, AssetCatalogSummary> resolve_assets(
        const std::vector<std::string>&) override {
        throw std::runtime_error("index layer must not resolve assets");
    }
    std::vector<WorkingCopyLite> list_working_copies() override {
        throw std::runtime_error("index layer must not list working copies");
    }
    std::vector<StaleLite> entity_staleness(
        const std::vector<pwb::data::EntityLinkView>&) override {
        throw std::runtime_error("index layer must not read entity staleness");
    }
    std::vector<StaleLite> downstream_stale_all() override {
        throw std::runtime_error("index layer must not read stale all");
    }
    std::vector<std::string> related_runs(
        const std::vector<std::string>&) override {
        throw std::runtime_error("index layer must not read runs");
    }
    std::vector<std::string> probe_missing_sources(
        const std::vector<std::string>&) override {
        throw std::runtime_error("index layer must not probe sources");
    }
};

// Counting fake: every seam records the asset ids it was asked for and how
// often it was called. Returns EMPTY summaries, so every linked asset is
// unknown to the catalog and surfaces as an unresolved placeholder row.
class CountingSource : public pwb::data::WorkspaceCatalogSource {
public:
    std::size_t requested_asset_ids = 0;   // sum of vector sizes
    std::size_t resolve_calls = 0;
    std::size_t probe_calls = 0;
    std::size_t probe_requested_asset_ids = 0;
    std::size_t copies_calls = 0;
    std::size_t runs_calls = 0;
    std::size_t runs_requested_asset_ids = 0;
    std::size_t stale_calls = 0;
    std::size_t stale_all_calls = 0;
    // Largest single request seen — the batching bound (a full-store read
    // would show up here as the whole corpus).
    std::size_t max_single_request = 0;
    std::vector<std::string> last_resolve_ids;

    std::map<std::string, AssetCatalogSummary> resolve_assets(
        const std::vector<std::string>& asset_ids) override {
        ++resolve_calls;
        requested_asset_ids += asset_ids.size();
        max_single_request = (std::max)(max_single_request, asset_ids.size());
        last_resolve_ids = asset_ids;
        return {};  // unknown → <未注册资产> rows
    }
    std::vector<WorkingCopyLite> list_working_copies() override {
        ++copies_calls;
        return {};
    }
    std::vector<StaleLite> entity_staleness(
        const std::vector<pwb::data::EntityLinkView>&) override {
        ++stale_calls;
        return {};
    }
    std::vector<StaleLite> downstream_stale_all() override {
        ++stale_all_calls;
        return {};
    }
    std::vector<std::string> related_runs(
        const std::vector<std::string>& asset_ids) override {
        ++runs_calls;
        runs_requested_asset_ids += asset_ids.size();
        max_single_request = (std::max)(max_single_request, asset_ids.size());
        return {};
    }
    std::vector<std::string> probe_missing_sources(
        const std::vector<std::string>& asset_ids) override {
        ++probe_calls;
        probe_requested_asset_ids += asset_ids.size();
        max_single_request = (std::max)(max_single_request, asset_ids.size());
        return {};
    }
};

const RoleSlot* slot_for(const EntityDataView& view, const std::string& role) {
    for (const auto& slot : view.role_slots) {
        if (slot.role == role) return &slot;
    }
    return nullptr;
}

std::size_t total_rows(const EntityDataView& view) {
    std::size_t rows = 0;
    for (const auto& slot : view.role_slots) {
        rows += slot.members.size() + slot.unresolved.size();
    }
    return rows;
}

}  // namespace

// ---- 1. root index at scale, zero catalog reads -----------------------------

PWB_TEST(well_index_at_10k_wells_100k_links_never_touches_the_catalog) {
    const Json document = scale_document(kWellCount, kLinksPerWell,
                                         kUnresolvedPerWell);
    ThrowingSource thrower;  // any catalog call fails the test by throw
    const pwb::data::EntityWorkspaceService service(document, &thrower);

    const auto started = std::chrono::steady_clock::now();
    const std::vector<pwb::data::EntityIndexEntry> entries =
        service.well_index(false);
    const auto elapsed_ms = std::chrono::duration_cast<
        std::chrono::milliseconds>(std::chrono::steady_clock::now() -
                                    started)
                                .count();

    std::cout << "  well_index: " << entries.size() << " wells / "
              << kTotalLinks << " links in " << elapsed_ms << " ms\n";
    PWB_CHECK(entries.size() == static_cast<std::size_t>(kWellCount));

    const std::map<std::string, int> expected_fill = expected_role_fill();
    int fill_total = 0;
    int expected_fill_total = 0;
    for (const auto& [role, count] : expected_fill) {
        expected_fill_total += count;
    }
    PWB_CHECK(expected_fill_total == kLinksPerWell);

    std::size_t unresolved_wells = 0;
    std::size_t stale_wells = 0;
    std::size_t mismatched_fill = 0;
    for (const auto& entry : entries) {
        int per_well = 0;
        for (const auto& [role, count] : entry.role_fill) {
            per_well += count;
            if (expected_fill.find(role) == expected_fill.end() ||
                expected_fill.at(role) != count) {
                ++mismatched_fill;
            }
        }
        fill_total += per_well;
        if (entry.role_fill.size() != expected_fill.size()) {
            ++mismatched_fill;
        }
        if (entry.unresolved_count == kUnresolvedPerWell) ++unresolved_wells;
        if (entry.stale_count != 0) ++stale_wells;
    }
    PWB_CHECK(mismatched_fill == 0);
    PWB_CHECK(fill_total == kTotalLinks);
    PWB_CHECK(unresolved_wells == static_cast<std::size_t>(kWellCount));
    PWB_CHECK(stale_wells == 0);

    // Order and identity of the synthetic corpus are preserved end to end.
    PWB_CHECK(entries.front().entity_id == well_id_of(0));
    PWB_CHECK(entries.front().name == well_name_of(0));
    PWB_CHECK(entries.front().uwi == well_uwi_of(0));
    PWB_CHECK(entries.back().entity_id == well_id_of(kWellCount - 1));

    // Spot checks across the corpus (first / middle / last) — per-role counts.
    const std::vector<int> probes = {0, 4242, kWellCount - 1};
    for (const int probe : probes) {
        const pwb::data::EntityIndexEntry& entry =
            entries[static_cast<std::size_t>(probe)];
        PWB_CHECK(entry.entity_id == well_id_of(probe));
        PWB_CHECK((entry.role_fill == expected_fill));
        PWB_CHECK(entry.unresolved_count == kUnresolvedPerWell);
        PWB_CHECK(entry.stale_count == 0);
    }

    // The survey index over the same document stays empty (no surveys).
    PWB_CHECK(service.survey_index().empty());

    // Scale ceiling: O(W+L) tree walk, generous for CI-class machines.
    PWB_CHECK(elapsed_ms < kIndexBudgetMs);
}

// ---- 2. expand-one-well is bounded ------------------------------------------

PWB_TEST(well_view_requests_only_that_wells_assets) {
    // Same scale corpus, but with NO unresolved links so the member set (and
    // hence the probe / runs request) is exactly the well's link count.
    const Json document =
        scale_document(kWellCount, kLinksPerWell, /*unresolved_per_well=*/0);
    CountingSource counting;
    const pwb::data::EntityWorkspaceService service(document, &counting);

    const auto view = service.well_view("well_04242");
    PWB_CHECK(view.has_value());
    PWB_CHECK(view->entity_id == "well_04242");
    PWB_CHECK(view->name == well_name_of(4242));

    // Full well vocabulary in registry order — no synthetic slot appended.
    const std::vector<std::string> roles = {
        "well_head", "well_log", "trajectory", "tops", "time_depth", "core",
        "interpretation", "qc", "other"};
    PWB_CHECK(view->role_slots.size() == roles.size());
    for (std::size_t i = 0; i < roles.size(); ++i) {
        PWB_CHECK(view->role_slots[i].role == roles[i]);
    }
    // Every link of that well landed in exactly one slot.
    PWB_CHECK(total_rows(*view) == static_cast<std::size_t>(kLinksPerWell));
    const RoleSlot* head_slot = slot_for(*view, "well_head");
    PWB_CHECK(head_slot != nullptr);
    PWB_CHECK(head_slot->members.size() == 2);  // role slot 0 cycles twice
    PWB_CHECK(head_slot->members[0].is_primary);
    const RoleSlot* qc_slot = slot_for(*view, "qc");
    PWB_CHECK(qc_slot != nullptr);
    PWB_CHECK(qc_slot->members.size() == 1);
    // Unknown assets (empty summaries) surface honestly.
    PWB_CHECK(qc_slot->members[0].unresolved);
    PWB_CHECK(qc_slot->members[0].name.find("asset_well_04242_") !=
              std::string::npos);

    // Bounded: exactly that well's links, never the 100k store.
    PWB_CHECK(counting.resolve_calls == 1);
    PWB_CHECK(counting.requested_asset_ids ==
              static_cast<std::size_t>(kLinksPerWell));
    PWB_CHECK(counting.max_single_request ==
              static_cast<std::size_t>(kLinksPerWell));
    PWB_CHECK(counting.probe_calls == 1);
    PWB_CHECK(counting.probe_requested_asset_ids ==
              static_cast<std::size_t>(kLinksPerWell));
    PWB_CHECK(counting.runs_calls == 1);
    PWB_CHECK(counting.runs_requested_asset_ids ==
              static_cast<std::size_t>(kLinksPerWell));
    PWB_CHECK(counting.copies_calls == 1);
    PWB_CHECK(counting.stale_calls == 0);       // with_stale defaults to false
    PWB_CHECK(counting.stale_all_calls == 0);   // index never read stale here

    // The requested ids are that well's asset ids, in link order.
    const std::vector<std::string>& requested = counting.last_resolve_ids;
    PWB_CHECK(requested.size() == static_cast<std::size_t>(kLinksPerWell));
    bool ids_ok = true;
    for (int slot = 0; slot < kLinksPerWell; ++slot) {
        if (requested[static_cast<std::size_t>(slot)] !=
            "asset_well_04242_" + std::to_string(slot)) {
            ids_ok = false;
        }
    }
    PWB_CHECK(ids_ok);

    // An unknown id resolves without any catalog read beyond its own (zero)
    // links.
    const std::size_t before = counting.requested_asset_ids;
    PWB_CHECK(!service.well_view("well_99999").has_value());
    PWB_CHECK(counting.requested_asset_ids == before);

    // 50 expansions: batching does not over-fetch (50 * 10, not 500k).
    CountingSource loop_counting;
    const pwb::data::EntityWorkspaceService loop_service(document,
                                                         &loop_counting);
    constexpr int kExpansions = 50;
    for (int i = 0; i < kExpansions; ++i) {
        const std::string id = well_id_of((i * 197) % kWellCount);
        const auto expanded = loop_service.well_view(id);
        PWB_CHECK(expanded.has_value());
        PWB_CHECK(expanded->entity_id == id);
        PWB_CHECK(total_rows(*expanded) ==
                  static_cast<std::size_t>(kLinksPerWell));
    }
    PWB_CHECK(loop_counting.requested_asset_ids ==
              static_cast<std::size_t>(kExpansions * kLinksPerWell));
    PWB_CHECK(loop_counting.resolve_calls ==
              static_cast<std::size_t>(kExpansions));
    PWB_CHECK(loop_counting.max_single_request ==
              static_cast<std::size_t>(kLinksPerWell));
    PWB_CHECK(loop_counting.probe_calls ==
              static_cast<std::size_t>(kExpansions));
    PWB_CHECK(loop_counting.probe_requested_asset_ids ==
              static_cast<std::size_t>(kExpansions * kLinksPerWell));
    PWB_CHECK(loop_counting.runs_calls ==
              static_cast<std::size_t>(kExpansions));
    PWB_CHECK(loop_counting.runs_requested_asset_ids ==
              static_cast<std::size_t>(kExpansions * kLinksPerWell));
    PWB_CHECK(loop_counting.stale_all_calls == 0);

    // Link set vs member set: resolve_assets is asked for every linked asset
    // (deduped), while the probe / runs / copies reads are scoped to the
    // MEMBER assets only (unresolved links excluded) — still that well alone.
    const Json with_unresolved =
        scale_document(3, kLinksPerWell, /*unresolved_per_well=*/1);
    CountingSource member_counting;
    const pwb::data::EntityWorkspaceService member_service(with_unresolved,
                                                           &member_counting);
    const auto member_view = member_service.well_view("well_00001");
    PWB_CHECK(member_view.has_value());
    PWB_CHECK(member_counting.resolve_calls == 1);
    PWB_CHECK(member_counting.requested_asset_ids ==
              static_cast<std::size_t>(kLinksPerWell));
    PWB_CHECK(member_counting.probe_calls == 1);
    PWB_CHECK(member_counting.probe_requested_asset_ids ==
              static_cast<std::size_t>(kLinksPerWell - 1));
    PWB_CHECK(member_counting.runs_calls == 1);
    PWB_CHECK(member_counting.runs_requested_asset_ids ==
              static_cast<std::size_t>(kLinksPerWell - 1));
    PWB_CHECK(member_counting.max_single_request ==
              static_cast<std::size_t>(kLinksPerWell));
}

// ---- 3. project switch leaves no stale state --------------------------------

PWB_TEST(project_switch_leaves_no_stale_state) {
    const Json first = scale_document(kWellCount, kLinksPerWell,
                                      kUnresolvedPerWell);
    CountingSource counting;
    const pwb::data::EntityWorkspaceService first_service(first, &counting);
    const auto first_entries = first_service.well_index(false);
    PWB_CHECK(first_entries.size() == static_cast<std::size_t>(kWellCount));

    // A second, unrelated project document (3 wells, no links at all).
    Json second = Json::object();
    Json wells = Json::array();
    for (const char* id : {"sw_a", "sw_b", "sw_c"}) {
        Json well = Json::object();
        well["id"] = id;
        well["name"] = std::string("Switch ") + id;
        wells.push_back(std::move(well));
    }
    second["wells"] = std::move(wells);

    CountingSource second_counting;
    const pwb::data::EntityWorkspaceService second_service(second,
                                                           &second_counting);
    const auto second_entries = second_service.well_index(false);
    PWB_CHECK(second_entries.size() == 3);
    PWB_CHECK(second_counting.resolve_calls == 0);
    PWB_CHECK(second_counting.requested_asset_ids == 0);

    std::set<std::string> ids;
    for (const auto& entry : second_entries) ids.insert(entry.entity_id);
    PWB_CHECK((ids == std::set<std::string>{"sw_a", "sw_b", "sw_c"}));
    // No well from the first document leaks into the second service.
    bool leaked = false;
    for (const auto& entry : second_entries) {
        if (entry.entity_id.rfind("well_", 0) == 0) leaked = true;
    }
    PWB_CHECK(!leaked);
    // Links of the first document are invisible here too (no links array).
    for (const auto& entry : second_entries) {
        PWB_CHECK(entry.role_fill.empty());
        PWB_CHECK(entry.unresolved_count == 0);
        PWB_CHECK(entry.stale_count == 0);
    }
    // Expanding a well of the second document reads nothing from the catalog
    // (no links → no asset ids), and the first document's well is unknown.
    const auto view = second_service.well_view("sw_b");
    PWB_CHECK(view.has_value());
    PWB_CHECK(view->role_slots.size() == 9);
    PWB_CHECK(total_rows(*view) == 0);
    PWB_CHECK(second_counting.resolve_calls == 0);
    PWB_CHECK(!second_service.well_view("well_00000").has_value());

    // The first service is unaffected by the second document's existence.
    PWB_CHECK(first_service.well_index(false).size() ==
              static_cast<std::size_t>(kWellCount));
}

// ---- 4. late-generation guard ------------------------------------------------

PWB_TEST(index_snapshot_does_not_see_later_mutation) {
    Json document = scale_document(2, kLinksPerWell, kUnresolvedPerWell);
    CountingSource counting;
    const pwb::data::EntityWorkspaceService service(document, &counting);
    const auto before = service.well_index(false);
    PWB_CHECK(before.size() == 2);

    // Mutate the document the service references: add a third well + a link.
    Json wells = document["wells"];
    Json extra = Json::object();
    extra["id"] = "well_late";
    extra["name"] = "Late Well";
    extra["uwi"] = "UWI-LATE";
    wells.push_back(std::move(extra));
    document["wells"] = std::move(wells);

    Json links = document["entity_asset_links"];
    links.push_back(Json{{"id", "link_late"},
                         {"entity_type", "well"},
                         {"entity_id", "well_late"},
                         {"asset_id", "asset_late"},
                         {"role", "well_log"},
                         {"is_primary", true},
                         {"unresolved", false},
                         {"ordinal", 0}});
    document["entity_asset_links"] = std::move(links);

    // The ALREADY-BUILT index is unchanged (snapshot, not a live view).
    PWB_CHECK(before.size() == 2);
    bool leaked = false;
    for (const auto& entry : before) {
        if (entry.entity_id == "well_late") leaked = true;
    }
    PWB_CHECK(!leaked);

    // A fresh index over the mutated document sees the third well.
    const auto after = service.well_index(false);
    PWB_CHECK(after.size() == 3);
    PWB_CHECK(after.back().entity_id == "well_late");
    PWB_CHECK(after.back().name == "Late Well");
    PWB_CHECK((after.back().role_fill ==
               std::map<std::string, int>{{"well_log", 1}}));
    PWB_CHECK(after.back().unresolved_count == 0);

    // A brand-new service over the same mutated document agrees.
    CountingSource fresh_counting;
    const pwb::data::EntityWorkspaceService fresh_service(document,
                                                          &fresh_counting);
    const auto fresh = fresh_service.well_index(false);
    PWB_CHECK(fresh.size() == 3);
    PWB_CHECK(fresh.back().entity_id == "well_late");
    PWB_CHECK(fresh_counting.resolve_calls == 0);

    // The new well is expandable, and only its own single asset is requested.
    const auto late_view = service.well_view("well_late");
    PWB_CHECK(late_view.has_value());
    PWB_CHECK(late_view->name == "Late Well");
    PWB_CHECK(counting.requested_asset_ids == 1);
    PWB_CHECK(counting.max_single_request == 1);
    PWB_CHECK(counting.resolve_calls == 1);
}
