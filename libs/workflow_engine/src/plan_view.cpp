// CONV-32 — dag/plan_view.py port. Python is authoritative: key orders,
// label fallbacks and the checklist's progress fill are frozen against the
// oracle fixture (tools/oracle/generate_workflow_receipt_plan_view_fixtures.py).
#include <pwb/workflow_engine/plan_view.hpp>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <optional>
#include <string>
#include <utility>

namespace pwb::workflow_engine {
namespace {

namespace ws = ::pwb::workflow_spec;

// Python round(x, 3) — decimal half-to-even via %.3f + strtod (see
// receipt.cpp for the rationale; duplicated here to keep each port's
// helpers internal).
double python_round3(double value) {
    if (!std::isfinite(value)) return value;
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.3f", value);
    return std::strtod(buffer, nullptr);
}

// Python str() of a JSON scalar (str(None) == "None", str(True) == "True").
std::string py_str(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_null()) return "None";
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_number_integer() || value.is_number_unsigned()) {
        return std::to_string(value.get<long long>());
    }
    if (value.is_number_float()) {
        char buffer[64] = {0};
        for (int precision = 1; precision <= 17; ++precision) {
            std::snprintf(buffer, sizeof(buffer), "%.*g", precision,
                          value.get<double>());
            if (std::strtod(buffer, nullptr) == value.get<double>()) break;
        }
        std::string text(buffer);
        if (text.find('.') == std::string::npos
            && text.find('e') == std::string::npos
            && text.find('E') == std::string::npos) {
            text += ".0";
        }
        return text;
    }
    return value.dump();
}

// bool(x) Python truthiness.
bool py_truthy(const Json& value) {
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number()) return value.get<double>() != 0.0;
    if (value.is_string()) return !value.get<std::string>().empty();
    return !value.empty();
}

std::string str_field(const Json& data, const char* key, std::string fallback) {
    if (!data.is_object()) return fallback;
    const auto it = data.find(key);
    if (it == data.end()) return fallback;
    return py_str(*it);
}

// data.get(key) passthrough for optional strings.
std::optional<std::string> opt_string(const Json& data, const char* key) {
    if (!data.is_object()) return std::nullopt;
    const auto it = data.find(key);
    if (it == data.end() || it->is_null()) return std::nullopt;
    if (it->is_string()) return it->get<std::string>();
    return py_str(*it);
}

// Python _STATE_LABELS.
std::string run_state_label(ws::RunState state) {
    switch (state) {
    case ws::RunState::running: return "运行中";
    case ws::RunState::completed: return "已完成";
    case ws::RunState::failed: return "失败";
    case ws::RunState::cancelled: return "已取消";
    case ws::RunState::interrupted: return "已中断（可恢复）";
    }
    return "?";
}

// Python _SYMBOLS.
std::string node_state_symbol(ws::NodeState state) {
    switch (state) {
    case ws::NodeState::pending: return "○";
    case ws::NodeState::running: return "●";
    case ws::NodeState::succeeded: return "✓";
    case ws::NodeState::failed: return "✗";
    case ws::NodeState::cancelled: return "⊗";
    case ws::NodeState::skipped: return "↷";
    case ws::NodeState::unavailable: return "⊘";
    }
    return "○";  // _SYMBOLS.get(state, "○")
}

// Python int(x) truncation for the checklist percentage fill.
int py_int(double value) { return static_cast<int>(value); }

}  // namespace

// ----------------------------------------------------------------- PlanItem --

std::string PlanItem::symbol() const { return node_state_symbol(state); }

Json PlanItem::to_dict() const {
    Json dict;
    dict["node_id"] = node_id;
    dict["label"] = label;
    dict["state"] = ws::to_string(state);
    dict["detail"] = detail;
    dict["from_cache"] = from_cache;
    dict["receipt_status"] =
        receipt_status.has_value() ? Json(*receipt_status) : Json(nullptr);
    dict["error"] = error.has_value() ? Json(*error) : Json(nullptr);
    dict["symbol"] = symbol();
    return dict;
}

// -------------------------------------------------------- WorkflowPlanView --

WorkflowPlanView WorkflowPlanView::from_spec(const ws::WorkflowSpec& spec) {
    WorkflowPlanView view;
    view.workflow_id = spec.workflow_id;
    view.name = spec.name;
    view.state = "running";  // RunState.RUNNING.value
    for (const ws::NodeSpec& node : spec.nodes) {
        PlanItem item;
        item.node_id = node.node_id;
        item.label = node.description.empty() ? node.node_id : node.description;
        item.state = ws::NodeState::pending;
        view.items.push_back(std::move(item));
    }
    return view;
}

WorkflowPlanView WorkflowPlanView::from_run(const ws::WorkflowRun& run) {
    WorkflowPlanView view;
    view.workflow_id = run.workflow.workflow_id;
    view.name = run.workflow.name;
    view.update_from_run(run);
    return view;
}

WorkflowPlanView WorkflowPlanView::from_summary(const Json& summary,
                                               const ws::WorkflowSpec* spec) {
    WorkflowPlanView view;
    view.workflow_id = str_field(summary, "workflow_id", "");
    view.name = str_field(summary, "name", "");
    view.state = str_field(summary, "state", "running");
    // progress = float(summary.get("progress", 0.0) or 0.0)
    view.progress = 0.0;
    if (summary.is_object()) {
        const auto it = summary.find("progress");
        if (it != summary.end() && py_truthy(*it)) {
            if (it->is_number()) {
                view.progress = it->get<double>();
            } else if (it->is_boolean()) {
                view.progress = it->get<bool>() ? 1.0 : 0.0;
            } else if (it->is_string()) {
                const std::string text = it->get<std::string>();
                char* end = nullptr;
                const double parsed = std::strtod(text.c_str(), &end);
                if (end != nullptr && end != text.c_str() && *end == '\0') {
                    view.progress = parsed;
                }
            }
        }
    }

    // nodes = summary.get("nodes") or {}
    const Json empty_nodes = Json::object();
    const Json* nodes = &empty_nodes;
    if (summary.is_object()) {
        const auto it = summary.find("nodes");
        if (it != summary.end() && it->is_object() && !it->empty()) {
            nodes = &*it;
        }
    }

    // Spec given: spec node order filtered to ids present in the map.
    // No spec: nodes-map insertion order.
    std::vector<std::pair<std::string, const ws::NodeSpec*>> ordered;
    if (spec != nullptr) {
        for (const ws::NodeSpec& node : spec->nodes) {
            if (nodes->contains(node.node_id)) {
                ordered.emplace_back(node.node_id, &node);
            }
        }
    } else {
        for (const auto& [node_id, info] : nodes->items()) {
            static_cast<void>(info);
            ordered.emplace_back(node_id, nullptr);
        }
    }

    for (const auto& [node_id, node] : ordered) {
        const Json empty_info = Json::object();
        const Json* info = &empty_info;
        const auto found = nodes->find(node_id);
        if (found != nodes->end() && found->is_object() && !found->empty()) {
            info = &*found;
        }

        PlanItem item;
        item.node_id = node_id;
        if (node != nullptr) {
            // Spec path: description only — NO node_id fallback here.
            item.label = node->description;
        } else {
            // str(info.get("label") or node_id)
            const auto label = info->find("label");
            item.label = label != info->end() && py_truthy(*label)
                             ? py_str(*label)
                             : node_id;
        }
        // NodeState(info.get("state", "pending")) — unknown state strings
        // throw, exactly like Python's ValueError.
        item.state = ws::node_state_from_string(
            str_field(*info, "state", "pending"));
        // str(info.get("skip_reason") or info.get("error") or "")
        item.detail.clear();
        for (const char* key : {"skip_reason", "error"}) {
            const auto it = info->find(key);
            if (it != info->end() && py_truthy(*it)) {
                item.detail = py_str(*it);
                break;
            }
        }
        item.from_cache = false;
        const auto from_cache = info->find("from_cache");
        if (from_cache != info->end()) {
            item.from_cache = py_truthy(*from_cache);
        }
        item.receipt_status = opt_string(*info, "receipt_status");
        item.error = opt_string(*info, "error");
        view.items.push_back(std::move(item));
    }
    return view;
}

void WorkflowPlanView::update_from_run(const ws::WorkflowRun& run) {
    state = ws::to_string(run.state);

    const std::size_t total = run.node_runs.size();
    std::size_t done = 0;
    for (const auto& [node_id, node_run] : run.node_runs) {
        static_cast<void>(node_id);
        switch (node_run.state) {
        case ws::NodeState::succeeded:
        case ws::NodeState::failed:
        case ws::NodeState::cancelled:
        case ws::NodeState::skipped:
        case ws::NodeState::unavailable:
            ++done;
            break;
        default:
            break;
        }
    }
    progress = total == 0
                   ? 0.0
                   : python_round3(static_cast<double>(done)
                                   / static_cast<double>(total));

    // Spec node positions for the stable order-restore sort, plus the
    // description lookup (Python raises KeyError on a node_run absent from
    // the spec; the view falls back to the node id — node_runs ⊆ spec
    // nodes in every persisted run).
    std::map<std::string, std::size_t> order;
    std::map<std::string, std::string> labels;
    for (std::size_t i = 0; i < run.workflow.nodes.size(); ++i) {
        const ws::NodeSpec& node = run.workflow.nodes[i];
        order.emplace(node.node_id, i);
        labels.emplace(node.node_id,
                       node.description.empty() ? node.node_id
                                                : node.description);
    }
    const auto position = [&order](const std::string& node_id) {
        const auto it = order.find(node_id);
        return it == order.end() ? 1000000000LL : static_cast<long long>(it->second);
    };

    items.clear();
    for (const auto& [node_id, node_run] : run.node_runs) {
        PlanItem item;
        item.node_id = node_run.node_id;
        const auto label = labels.find(node_run.node_id);
        item.label = label == labels.end() ? node_run.node_id : label->second;
        item.state = node_run.state;
        // detail = skip_reason or error or "" (empty strings are falsy).
        if (node_run.skip_reason.has_value() && !node_run.skip_reason->empty()) {
            item.detail = *node_run.skip_reason;
        } else if (node_run.error.has_value() && !node_run.error->empty()) {
            item.detail = *node_run.error;
        }
        item.from_cache = node_run.from_cache;
        // receipt_status = (receipt or {}).get("status")
        if (node_run.receipt.has_value() && node_run.receipt->is_object()) {
            item.receipt_status = opt_string(*node_run.receipt, "status");
        }
        item.error = node_run.error;
        items.push_back(std::move(item));
    }
    std::stable_sort(items.begin(), items.end(),
                     [&position](const PlanItem& left, const PlanItem& right) {
                         return position(left.node_id)
                             < position(right.node_id);
                     });
}

std::optional<std::string> WorkflowPlanView::current_node() const {
    for (const PlanItem& item : items) {
        if (item.state == ws::NodeState::running) return item.label;
    }
    return std::nullopt;
}

std::string WorkflowPlanView::state_label() const {
    try {
        return run_state_label(ws::run_state_from_string(state));
    } catch (const ws::ModelError&) {
        // Python raises ValueError here; the panel-facing view returns the
        // raw state instead (graceful by design, frozen in the oracle).
        return state;
    }
}

Json WorkflowPlanView::checklist() const {
    Json rows = Json::array();
    for (const PlanItem& item : items) rows.push_back(item.to_dict());
    for (Json& row : rows) {
        if (row["state"] == "running") {
            const std::string& detail =
                row["detail"].get_ref<const std::string&>();
            if (detail.empty()) {
                row["detail"] =
                    std::to_string(py_int(progress * 100.0)) + "%";
            }
        }
    }
    const std::optional<std::string> current = current_node();
    if (current.has_value()) {
        for (Json& row : rows) {
            if (row["label"] == *current) row["current"] = true;
        }
    }
    return rows;
}

Json WorkflowPlanView::to_dict() const {
    Json dict;
    dict["workflow_id"] = workflow_id;
    dict["name"] = name;
    dict["state"] = state;
    dict["state_label"] = state_label();
    dict["progress"] = progress;
    const std::optional<std::string> current = current_node();
    dict["current_node"] = current.has_value() ? Json(*current) : Json(nullptr);
    dict["items"] = checklist();
    return dict;
}

}  // namespace pwb::workflow_engine
