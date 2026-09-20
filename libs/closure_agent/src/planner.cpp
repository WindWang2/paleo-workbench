// planner.cpp — TaskPlanner port (agent/planner.py): the fixed skeleton,
// domain-conditioned well/seismic steps, and cartography fan-in.
#include <pwb/closure_agent/planner.hpp>

namespace pwb::closure_agent {

std::string to_string(TaskStatus status) {
    switch (status) {
        case TaskStatus::Pending: return "pending";
        case TaskStatus::Running: return "running";
        case TaskStatus::Completed: return "completed";
        case TaskStatus::Failed: return "failed";
        case TaskStatus::Skipped: return "skipped";
    }
    return "pending";
}

std::optional<TaskStatus> task_status_from_string(const std::string& value) {
    if (value == "pending") return TaskStatus::Pending;
    if (value == "running") return TaskStatus::Running;
    if (value == "completed") return TaskStatus::Completed;
    if (value == "failed") return TaskStatus::Failed;
    if (value == "skipped") return TaskStatus::Skipped;
    return std::nullopt;
}

void TaskGraph::add_node(TaskNode node) {
    nodes.push_back(std::move(node));
}

TaskNode* TaskGraph::find(const std::string& id) {
    for (auto& node : nodes) {
        if (node.id == id) return &node;
    }
    return nullptr;
}

const TaskNode* TaskGraph::find(const std::string& id) const {
    for (const auto& node : nodes) {
        if (node.id == id) return &node;
    }
    return nullptr;
}

std::vector<TaskNode*> TaskGraph::executable_nodes() {
    std::vector<TaskNode*> ready;
    for (auto& node : nodes) {
        if (node.status != TaskStatus::Pending) continue;
        bool deps_ok = true;
        for (const auto& dep_id : node.dependencies) {
            const TaskNode* dep = find(dep_id);
            if (dep != nullptr && dep->status != TaskStatus::Completed) {
                deps_ok = false;
                break;
            }
        }
        if (deps_ok) ready.push_back(&node);
    }
    return ready;
}

bool TaskGraph::is_finished() const {
    for (const auto& node : nodes) {
        if (node.status == TaskStatus::Pending || node.status == TaskStatus::Running) {
            return false;
        }
    }
    return true;
}

bool TaskGraph::has_failures() const {
    for (const auto& node : nodes) {
        if (node.status == TaskStatus::Failed) return true;
    }
    return false;
}

TaskGraph TaskPlanner::create_plan(const ParsedIntent& intent) const {
    TaskGraph graph;
    const Json& parameters = intent.parameters;

    TaskNode discover;
    discover.id = "task_data_discover";
    discover.agent_name = "data_agent";
    discover.action = "discover_and_validate";
    discover.description = "Discover and validate catalog data assets and schemas";
    discover.parameters = parameters;
    graph.add_node(std::move(discover));

    const bool well_needed =
        intent.primary_domain == TaskDomain::WellLogging ||
        intent.primary_domain == TaskDomain::SingleFactorMapping ||
        intent.primary_domain == TaskDomain::PaleomapCompilation;
    if (well_needed) {
        TaskNode well;
        well.id = "task_well_process";
        well.agent_name = "well_agent";
        well.action = "process_well_tops_and_curves";
        well.description = "Extract formation tops and align well log curves";
        well.dependencies = {"task_data_discover"};
        well.parameters = parameters;
        graph.add_node(std::move(well));
    }

    const bool seismic_needed =
        intent.primary_domain == TaskDomain::SeismicInterpretation ||
        intent.primary_domain == TaskDomain::PaleomapCompilation;
    if (seismic_needed) {
        TaskNode seismic;
        seismic.id = "task_seismic_process";
        seismic.agent_name = "seismic_agent";
        seismic.action = "extract_slices_and_attributes";
        seismic.description = "Extract 3D seismic slices and coherence volumes";
        seismic.dependencies = {"task_data_discover"};
        seismic.parameters = parameters;
        graph.add_node(std::move(seismic));
    }

    TaskNode gis;
    gis.id = "task_gis_spatial";
    gis.agent_name = "gis_agent";
    gis.action = "analyze_spatial_constraints";
    gis.description = "Extract fault barriers and validate boundary topologies";
    gis.dependencies = {"task_data_discover"};
    gis.parameters = parameters;
    graph.add_node(std::move(gis));

    std::vector<std::string> carto_deps = {"task_gis_spatial"};
    if (graph.find("task_well_process") != nullptr) {
        carto_deps.push_back("task_well_process");
    }
    if (graph.find("task_seismic_process") != nullptr) {
        carto_deps.push_back("task_seismic_process");
    }
    TaskNode carto;
    carto.id = "task_carto_generate";
    carto.agent_name = "carto_agent";
    carto.action = "generate_factor_surface";
    carto.description = "Perform barrier-constrained anisotropic IDW and contouring";
    carto.dependencies = std::move(carto_deps);
    carto.parameters = parameters;
    graph.add_node(std::move(carto));

    TaskNode viz;
    viz.id = "task_viz_compose";
    viz.agent_name = "viz_agent";
    viz.action = "compose_map_layout";
    viz.description =
        "Compose standardized geological map layout with legends and graticules";
    viz.dependencies = {"task_carto_generate"};
    viz.parameters = parameters;
    graph.add_node(std::move(viz));

    TaskNode qa;
    qa.id = "task_qa_audit";
    qa.agent_name = "qa_agent";
    qa.action = "audit_and_verify";
    qa.description = "Execute topological, boundary, and statistical QC audit";
    qa.dependencies = {"task_viz_compose"};
    qa.parameters = parameters;
    graph.add_node(std::move(qa));

    TaskNode delivery;
    delivery.id = "task_result_delivery";
    delivery.agent_name = "result_agent";
    delivery.action = "package_and_report";
    delivery.description =
        "Assemble execution report, lineage metadata, and deliverables";
    delivery.dependencies = {"task_qa_audit"};
    delivery.parameters = parameters;
    graph.add_node(std::move(delivery));

    return graph;
}

}  // namespace pwb::closure_agent
