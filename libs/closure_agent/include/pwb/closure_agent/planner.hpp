#pragma once

// DAG task planner — C++ port of paleo_workbench/agent/planner.py. The
// domain intent is broken into the fixed multi-agent skeleton
// (discover -> well/seismic per domain -> gis -> carto -> viz -> qa ->
// result delivery); ready nodes are PENDING with all dependencies COMPLETED.

#include <pwb/closure_agent/intent.hpp>

#include <functional>
#include <string>
#include <vector>

namespace pwb::closure_agent {

enum class TaskStatus {
    Pending,
    Running,
    Completed,
    Failed,
    Skipped,
};

std::string to_string(TaskStatus status);
std::optional<TaskStatus> task_status_from_string(const std::string& value);

struct TaskNode {
    std::string id;
    std::string agent_name;
    std::string action;
    std::string description;
    std::vector<std::string> dependencies;
    Json parameters = Json::object();
    TaskStatus status = TaskStatus::Pending;
    Json result = Json(nullptr);
    std::optional<std::string> error;
};

class TaskGraph {
public:
    std::vector<TaskNode> nodes;  // insertion order == Python dict order

    void add_node(TaskNode node);
    TaskNode* find(const std::string& id);
    const TaskNode* find(const std::string& id) const;

    // PENDING nodes whose dependencies are all COMPLETED.
    std::vector<TaskNode*> executable_nodes();

    bool is_finished() const;
    bool has_failures() const;
};

class TaskPlanner {
public:
    TaskGraph create_plan(const ParsedIntent& intent) const;
};

}  // namespace pwb::closure_agent
