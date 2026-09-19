#include "pwb/ui_data_core/map_edit_topology.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <set>
#include <utility>

namespace pwb::ui_data_core {
namespace {

domain::Json issue_entry(const FaciesPolygonModel& item,
                         const domain::Json& issue, bool with_address,
                         int part_index, int ring_index) {
    domain::Json entry = domain::Json::object();
    entry["feature_id"] = item.feature_id;
    if (with_address) {
        entry["part_index"] = part_index;
        entry["ring_index"] = ring_index;
    }
    entry["code"] = json_get_string(issue, "code",
                                    with_address ? "invalid_geometry"
                                                 : "invalid_shape");
    entry["message"] = json_get_string(issue, "message",
                                       with_address ? "几何无效"
                                                    : "Shape 几何无效");
    entry["severity"] = "error";
    return entry;
}

FeatureIdFn effective_ids(const FeatureIdFn& ids) {
    return ids ? ids
               : FeatureIdFn(
                     [](std::string_view p) { return new_feature_id(p); });
}

}  // namespace

domain::Json facies_geometry_issues(const FaciesPolygonModel& item,
                                    MapGeometryBackend* backend) {
    domain::Json issues = domain::Json::array();
    for (const auto& address : item.iter_ring_addresses()) {
        const domain::Json ring_issues = validate_ring(address.points);
        for (const auto& issue : ring_issues) {
            issues.push_back(issue_entry(item, issue, true,
                                         address.part_index,
                                         address.ring_index));
        }
    }
    // from geoviz import validate_polygon_geometry — ImportError /
    // AttributeError → [].
    const domain::Json shape_issues = validate_polygon_geometry(
        item.geometry_type, item.geometry_coordinates(), backend);
    for (const auto& issue : shape_issues) {
        issues.push_back(issue_entry(item, issue, false, 0, 0));
    }
    return issues;
}

void apply_adjacency_warnings(std::vector<FaciesPolygonModel*>& items,
                              double gap_tol) {
    if (items.size() < 2) {
        return;
    }
    std::vector<MapRing> rings;
    rings.reserve(items.size());
    for (const auto* item : items) {
        rings.push_back(item->coordinates());
    }
    const domain::Json issues = validate_adjacency(rings, gap_tol);
    std::set<int> flagged;
    for (const auto& issue : issues) {
        const auto it = issue.find("pair");
        if (it == issue.end() || !it->is_array() || it->size() != 2) {
            continue;
        }
        const auto a = (*it)[0].is_number() ? std::optional<int>((*it)[0].get<int>())
                                            : std::nullopt;
        const auto b = (*it)[1].is_number() ? std::optional<int>((*it)[1].get<int>())
                                            : std::nullopt;
        if (a.has_value()) {
            flagged.insert(*a);
        }
        if (b.has_value()) {
            flagged.insert(*b);
        }
    }
    for (const int idx : flagged) {
        if (idx >= 0 && idx < static_cast<int>(items.size()) &&
            items[idx]->topology_status == kTopologyOk) {
            items[idx]->set_topology_status(
                std::string_view{kTopologyWarning});
        }
    }
}

TopologyRebuildPlan plan_topology_rebuild(
    const std::vector<FaciesPolygonModel*>& facies_items, double tol,
    ApplyCoordinatesFn apply_coordinates) {
    TopologyRebuildPlan plan;
    if (facies_items.empty()) {
        plan.report["snapped_count"] = 0;
        plan.report["ring_warnings"] = 0;
        plan.report["adjacency_issues"] = 0;
        plan.report["changed"] = false;
        return plan;
    }
    std::vector<MapRing> rings;
    rings.reserve(facies_items.size());
    for (const auto* item : facies_items) {
        rings.push_back(item->coordinates());
    }
    const TopologyRebuildReport report =
        rebuild_topology(rings, tol, tol);
    std::vector<BatchVertexEditCommand::Change> changes;
    for (std::size_t i = 0; i < facies_items.size(); ++i) {
        if (rings[i] != report.rings[i]) {
            changes.push_back({facies_items[i]->feature_id, rings[i],
                               report.rings[i]});
        }
    }
    const long long snapped_count = static_cast<long long>(changes.size());
    if (!changes.empty()) {
        plan.command = std::make_shared<BatchVertexEditCommand>(
            std::move(changes), std::move(apply_coordinates));
    }
    plan.report["snapped_count"] = snapped_count;
    plan.report["ring_warnings"] =
        static_cast<long long>(report.ring_issues.size());
    plan.report["adjacency_issues"] =
        static_cast<long long>(report.adjacency_issues.size());
    plan.report["changed"] = snapped_count > 0 || report.changed;
    plan.report["ring_issues"] = report.ring_issues;
    plan.report["adjacency_issue_list"] = report.adjacency_issues;
    return plan;
}

MergeFaciesPlan plan_merge_facies(
    const FaciesPolygonModel& a, const FaciesPolygonModel& b,
    AddFeatureFn add_feature, RemoveFeatureFn remove_feature,
    const ItemFromRecordFn& item_from_record, MapGeometryBackend* backend,
    const FeatureIdFn& ids) {
    MergeFaciesPlan plan;
    if (a.has_complex_geometry() || b.has_complex_geometry()) {
        return plan;
    }
    const auto merged = merge_rings(a.coordinates(), b.coordinates(),
                                    backend);
    if (!merged.has_value()) {
        return plan;
    }
    // name = a.name or b.name or "合并相带"
    const domain::Json a_name = a.get_property("name");
    const domain::Json b_name = b.get_property("name");
    const std::string name =
        json_truthy(a_name)   ? python_str(a_name)
        : json_truthy(b_name) ? python_str(b_name)
                              : "合并相带";
    const FeatureIdFn id_gen = effective_ids(ids);
    const std::string new_id = id_gen("facies");
    // style = dict(a.to_record().get("style") or {})
    domain::Json style = domain::Json::object();
    {
        const domain::Json rec = a.to_record();
        const auto it = rec.find("style");
        if (it != rec.end() && it->is_object()) {
            style = *it;
        }
    }
    domain::Json new_rec = domain::Json::object();
    new_rec["id"] = new_id;
    new_rec["kind"] = "facies";
    new_rec["name"] = name;
    new_rec["coordinates"] = ring_to_json(*merged);
    new_rec["style"] = style;
    if (!item_from_record(new_rec).has_value()) {
        return plan;
    }
    auto delete_a = std::make_shared<DeleteFeatureCommand>(
        a.to_record(), add_feature, remove_feature);
    auto delete_b = std::make_shared<DeleteFeatureCommand>(
        b.to_record(), add_feature, remove_feature);
    auto create = std::make_shared<CreateFeatureCommand>(
        new_rec, add_feature, remove_feature);
    plan.command = std::make_shared<CompositeCommand>(
        std::vector<std::shared_ptr<EditCommand>>{delete_a, delete_b,
                                                  create});
    plan.new_id = new_id;
    return plan;
}

SplitFaciesPlan plan_split_facies(
    const FaciesPolygonModel& poly_item, const LineModel& line_item,
    AddFeatureFn add_feature, RemoveFeatureFn remove_feature,
    const ItemFromRecordFn& item_from_record, MapGeometryBackend* backend,
    const FeatureIdFn& ids) {
    SplitFaciesPlan plan;
    if (poly_item.has_complex_geometry()) {
        return plan;
    }
    const auto parts = split_ring_by_line(poly_item.coordinates(),
                                          line_item.coordinates(), backend);
    if (!parts.has_value() || parts->size() < 2) {
        return plan;
    }
    const domain::Json base = poly_item.get_property("name");
    const std::string base_name =
        json_truthy(base) ? python_str(base) : "相带";
    domain::Json poly_style = domain::Json::object();
    {
        const domain::Json rec = poly_item.to_record();
        const auto it = rec.find("style");
        if (it != rec.end() && it->is_object()) {
            poly_style = *it;
        }
    }
    const FeatureIdFn id_gen = effective_ids(ids);
    std::vector<domain::Json> new_recs;
    std::vector<std::string> new_ids;
    for (std::size_t i = 0; i < parts->size(); ++i) {
        const std::string nid = id_gen("facies");
        new_ids.push_back(nid);
        domain::Json rec = domain::Json::object();
        rec["id"] = nid;
        rec["kind"] = "facies";
        rec["name"] = base_name + "-" + std::to_string(i + 1);
        rec["coordinates"] = ring_to_json((*parts)[i]);
        rec["style"] = poly_style;
        new_recs.push_back(std::move(rec));
    }
    std::vector<std::shared_ptr<EditCommand>> children;
    children.push_back(std::make_shared<DeleteFeatureCommand>(
        poly_item.to_record(), add_feature, remove_feature));
    for (const auto& rec : new_recs) {
        if (!item_from_record(rec).has_value()) {
            return SplitFaciesPlan{};
        }
        children.push_back(std::make_shared<CreateFeatureCommand>(
            rec, add_feature, remove_feature));
    }
    plan.command = std::make_shared<CompositeCommand>(std::move(children));
    plan.new_ids = std::move(new_ids);
    return plan;
}

}  // namespace pwb::ui_data_core
