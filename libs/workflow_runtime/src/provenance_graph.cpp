// provenance_graph.cpp — C++ port of
// paleo_workbench/workflow/provenance_graph.py (CONV-26). See
// include/pwb/workflow_runtime/provenance_graph.hpp.

#include <pwb/workflow_runtime/provenance_graph.hpp>

#include "python_compat.hpp"

#include <set>
#include <unordered_set>

namespace pwb::workflow_runtime {

namespace {

// _node — {"id", "kind", "label"} + non-null extras.
Json make_node(const std::string& node_id, const std::string& kind,
               const std::string& label, Json extra = Json::object()) {
    Json node = Json::object();
    node["id"] = node_id;
    node["kind"] = kind;
    node["label"] = label;
    if (extra.is_object()) {
        for (auto it = extra.begin(); it != extra.end(); ++it) {
            if (it.value().is_null()) continue;
            node[it.key()] = it.value();
        }
    }
    return node;
}

}  // namespace

Json build_product_lifecycle_graph(
    const Json& project, const CatalogRepository* repository,
    const std::optional<std::string>& product_id) {
    Json nodes = Json::array();
    Json edges = Json::array();
    Json gaps = Json::array();
    std::unordered_set<std::string> seen_nodes;

    auto add_node = [&](Json node) -> std::string {
        const std::string id = node.at("id").get_ref<const std::string&>();
        if (seen_nodes.insert(id).second) {
            nodes.push_back(std::move(node));
        }
        return id;
    };
    auto add_edge = [&](const std::string& src, const std::string& dst,
                        const std::string& relation) {
        Json edge = Json::object();
        edge["source"] = src;
        edge["target"] = dst;
        edge["relation"] = relation;
        edges.push_back(std::move(edge));
    };
    auto add_gap = [&](const std::string& scope, const std::string& reason) {
        Json gap = Json::object();
        gap["scope"] = scope;
        gap["reason"] = reason;
        gaps.push_back(std::move(gap));
    };

    std::vector<Json> records;
    for (const auto& record :
         pycompat::dict_get(project, "map_products", Json::array())) {
        if (!product_id) {
            records.push_back(record);
        } else if (pycompat::str_scalar(
                       pycompat::dict_get(record, "id", Json(""))) ==
                   *product_id) {
            records.push_back(record);
        }
    }
    if (product_id && records.empty()) {
        add_gap("product:" + *product_id,
                "no map product record with this id");
        Json out = Json::object();
        out["nodes"] = std::move(nodes);
        out["edges"] = std::move(edges);
        out["gaps"] = std::move(gaps);
        return out;
    }

    for (const Json& record : records) {
        const std::string rid =
            pycompat::str_scalar(pycompat::dict_get(record, "id", Json("")));
        Json extra = Json::object();
        extra["frozen"] = pycompat::truthy(
            pycompat::dict_get(record, "frozen", Json(false)));
        extra["status"] = pycompat::str_scalar(
            pycompat::dict_get(record, "status", Json("")));
        extra["superseded_by"] =
            pycompat::dict_get(record, "superseded_by", Json(nullptr));
        const std::string product_node = add_node(make_node(
            "product:" + rid, "map_product",
            pycompat::str_scalar(pycompat::dict_get(record, "product_name",
                                                    Json("")))
                    .empty()
                ? rid
                : pycompat::str_scalar(pycompat::dict_get(
                      record, "product_name", Json(""))),
            std::move(extra)));

        std::set<std::string> factor_task_ids;
        for (const auto& tid :
             pycompat::dict_get(record, "factor_task_ids", Json::array())) {
            factor_task_ids.insert(pycompat::str_scalar(tid));
        }
        for (const auto& task :
             pycompat::dict_get(project, "factor_map_tasks", Json::array())) {
            const std::string task_id =
                pycompat::str_scalar(pycompat::dict_get(task, "id", Json("")));
            if (factor_task_ids.count(task_id) == 0) continue;
            const Json grid_version_json = pycompat::dict_get(
                task, "grid_artifact_version_id", Json(nullptr));
            const bool has_grid = !grid_version_json.is_null();
            const std::string grid_version =
                has_grid ? pycompat::str_scalar(grid_version_json) : "";

            Json task_extra = Json::object();
            task_extra["method"] = pycompat::str_scalar(
                pycompat::dict_get(task, "method", Json("")));
            task_extra["source_kind"] = pycompat::str_scalar(
                pycompat::dict_get(task, "source_kind", Json("")));
            task_extra["grid_version_id"] = has_grid
                                                ? Json(grid_version)
                                                : Json(nullptr);
            const std::string task_node_id = add_node(make_node(
                "factor_task:" + task_id, "factor_task",
                pycompat::str_scalar(pycompat::dict_get(task, "name",
                                                        Json("")))
                        .empty()
                    ? task_id
                    : pycompat::str_scalar(
                          pycompat::dict_get(task, "name", Json(""))),
                std::move(task_extra)));
            add_edge(product_node, task_node_id, "assembles_factor");

            if (!has_grid) {
                add_gap("factor_task:" + task_id,
                        "task has no persisted grid version "
                        "(never interpolated or artifact lost)");
            } else {
                Json version_extra = Json::object();
                version_extra["version_id"] = grid_version;
                const std::string version_node = add_node(make_node(
                    "version:" + grid_version, "factor_output",
                    "grid " + pycompat::head12(grid_version) + "…",
                    std::move(version_extra)));
                add_edge(task_node_id, version_node, "produced");
            }

            // Constraint pins: the constraint state this task used.
            const Json params =
                pycompat::dict_get(task, "parameters", Json::object());
            const Json pins =
                pycompat::dict_get(params, "constraint_pins", Json::array());
            if (pins.is_array()) {
                for (const auto& pin : pins) {
                    const std::string pin_group = pycompat::str_scalar(
                        pycompat::dict_get(pin, "group_id", Json("")));
                    Json pin_extra = Json::object();
                    pin_extra["content_hash"] = pycompat::str_scalar(
                        pycompat::dict_get(pin, "content_hash", Json("")));
                    pin_extra["pinned_version_id"] =
                        pycompat::dict_get(pin, "version_id", Json(nullptr));
                    const std::string group_node = add_node(make_node(
                        "constraints:" + pin_group, "constraints",
                        pycompat::str_scalar(pycompat::dict_get(
                            pin, "group_name", Json("")))
                                .empty()
                            ? pin_group
                            : pycompat::str_scalar(pycompat::dict_get(
                                  pin, "group_name", Json(""))),
                        std::move(pin_extra)));
                    add_edge(task_node_id, group_node, "consumed_constraints");
                }
            }
        }
    }

    // Fusion lineage from the catalog (repository == nullptr: Python
    // catalog_service=None — section skipped without a gap).
    if (repository != nullptr) {
        bool runs_read_failed = false;
        std::vector<RunRecord> runs;
        try {
            runs = repository->list_runs();
        } catch (...) {
            runs_read_failed = true;
            add_gap("catalog",
                    "catalog runs not readable — fusion lineage omitted");
        }
        if (!runs_read_failed) {
            for (const RunRecord& run : runs) {
                if (run.operation != "factor_fusion" &&
                    run.operation != "factor_fusion:confidence" &&
                    run.operation != "factor_fusion:variance") {
                    continue;
                }
                for (const std::string& version_id : run.output_version_ids) {
                    Json fusion_extra = Json::object();
                    fusion_extra["version_id"] = version_id;
                    fusion_extra["run_id"] = run.run_id;
                    const std::string node_id = add_node(make_node(
                        "version:" + version_id, "fusion_output",
                        run.operation + " " + pycompat::head12(version_id) +
                            "…",
                        std::move(fusion_extra)));
                    for (const std::string& parent : run.input_version_ids) {
                        Json parent_extra = Json::object();
                        parent_extra["version_id"] = parent;
                        const std::string parent_node = add_node(make_node(
                            "version:" + parent, "factor_output",
                            "input " + pycompat::head12(parent) + "…",
                            std::move(parent_extra)));
                        add_edge(parent_node, node_id, "fusion_input");
                    }
                }
            }
        }
    }

    Json out = Json::object();
    out["nodes"] = std::move(nodes);
    out["edges"] = std::move(edges);
    out["gaps"] = std::move(gaps);
    return out;
}

}  // namespace pwb::workflow_runtime
