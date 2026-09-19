// UI-10 — factor pages state: badges, grids, dialog params + worker body.

#include "pwb/ui_seqviz/factor_state.hpp"

#include <map>
#include <set>
#include <stdexcept>

namespace pwb::ui_seqviz {

namespace {

// domain::Json helpers — Python dict.get + str() coercions.
const domain::Json* json_get(const domain::Json& object,
                             const std::string& key) {
    if (!object.is_object()) {
        return nullptr;
    }
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &*it;
}

std::string json_str(const domain::Json& value) {
    if (value.is_null()) {
        return "None";
    }
    if (value.is_string()) {
        return value.get<std::string>();
    }
    if (value.is_boolean()) {
        return value.get<bool>() ? "True" : "False";
    }
    if (value.is_number_integer()) {
        return std::to_string(value.get<long long>());
    }
    if (value.is_number_unsigned()) {
        return std::to_string(value.get<unsigned long long>());
    }
    if (value.is_number_float()) {
        // Python str(float): repr-style — %g trims trailing zeros.
        std::string text = std::to_string(value.get<double>());
        text.erase(text.find_last_not_of('0') + 1, std::string::npos);
        if (!text.empty() && text.back() == '.') {
            text += '0';
        }
        return text;
    }
    return value.dump();
}

// Python truthiness for a Json value (dict/list/str non-empty, numbers
// non-zero, bool itself, null false).
bool json_truthy(const domain::Json& value) {
    if (value.is_null()) {
        return false;
    }
    if (value.is_boolean()) {
        return value.get<bool>();
    }
    if (value.is_number()) {
        return value.get<double>() != 0.0;
    }
    if (value.is_string()) {
        return !value.get<std::string>().empty();
    }
    if (value.is_array() || value.is_object()) {
        return !value.empty();
    }
    return false;
}

long long json_int_or_zero(const domain::Json* value) {
    if (value == nullptr || value->is_null()) {
        return 0;
    }
    if (value->is_number()) {
        return static_cast<long long>(value->get<double>());
    }
    if (value->is_string()) {
        try {
            return std::stoll(value->get<std::string>());
        } catch (...) {
            return 0;
        }
    }
    if (value->is_boolean()) {
        return value->get<bool>() ? 1 : 0;
    }
    return 0;
}

}  // namespace

// ---------------------------------------------------------------------------
// factor_task_panel.py
// ---------------------------------------------------------------------------

StateToken factor_task_badge_token(const std::string& status) {
    std::string value = status;
    if (status == "complete") {
        value = "done";
    } else if (status == "pending") {
        value = "queued";
    }
    return state_token("task", value);
}

std::string factor_task_sub_label(const FactorTaskRecord& task) {
    std::string grid = "50m";
    if (const domain::Json* value = json_get(task.parameters, "grid")) {
        if (!value->is_null()) {
            grid = json_str(*value);
        }
    }
    return task.method + " · " + grid;
}

std::string factor_panel_horizon_text(
    const std::vector<FactorTaskRecord>& tasks) {
    if (tasks.empty()) {
        return "层位: —";
    }
    return "层位: " + tasks.front().target_horizon;
}

std::optional<std::string> factor_common_method(
    const std::vector<FactorTaskRecord>& tasks) {
    // Counter.most_common(1): count every non-empty method; max count wins,
    // ties keep first-seen order.
    std::map<std::string, long long> counts;
    std::vector<std::string> order;
    for (const auto& task : tasks) {
        if (task.method.empty()) {
            continue;
        }
        if (counts[task.method]++ == 0) {
            order.push_back(task.method);
        }
    }
    std::optional<std::string> best;
    long long best_count = -1;
    for (const auto& method : order) {
        if (counts[method] > best_count) {
            best_count = counts[method];
            best = method;
        }
    }
    return best;
}

std::string factor_prepared_summary(
    const std::vector<FactorTaskRecord>& tasks) {
    long long complete = 0;
    for (const auto& task : tasks) {
        if (task.status == "complete") {
            ++complete;
        }
    }
    return "已制备 " + std::to_string(complete) + " / " +
           std::to_string(tasks.size()) + " 个单因素图";
}

std::string factor_selected_method(const std::string& combo_text) {
    return combo_text.empty() ? "IDW" : combo_text;
}

// ---------------------------------------------------------------------------
// factor_preview_grid.py
// ---------------------------------------------------------------------------

std::vector<FactorTaskRecord> factor_completed_tasks(
    const std::vector<FactorTaskRecord>& tasks) {
    std::vector<FactorTaskRecord> out;
    for (const auto& task : tasks) {
        if (task.status == "complete") {
            out.push_back(task);
        }
    }
    return out;
}

std::string factor_preview_header(
    const std::vector<FactorTaskRecord>& completed) {
    if (completed.empty()) {
        return "单因素图集";
    }
    const FactorTaskRecord& first = completed.front();
    const std::string method =
        first.method.empty() ? "—" : first.method;
    std::string grid = "50×50";
    if (const domain::Json* value =
            json_get(first.quality_metrics, "grid")) {
        if (!value->is_null()) {
            grid = json_str(*value);
        }
    }
    return first.target_horizon + " 单因素图集（" + method + "插值 · 网格 " +
           grid + " m）";
}

FactorCardView factor_card_view(const FactorTaskRecord& task) {
    FactorCardView view;
    view.title =
        task.factor_type.empty() ? task.name : task.factor_type;

    const domain::Json& metrics = task.quality_metrics;
    view.range_text = "—";
    if (const domain::Json* value = json_get(metrics, "range")) {
        view.range_text = json_str(*value);
    }

    const domain::Json* r2 = json_get(metrics, "r_squared");
    if (r2 != nullptr && !r2->is_null()) {
        view.rsquared_text = "R² " + json_str(*r2);
        view.rsquared_visible = true;
    } else if (metrics.is_object() && !metrics.empty()) {
        // #939-5: plan/batch runs legitimately omit LOO R² — show the
        // reason instead of hiding the metric.
        view.rsquared_text = "R² 本轮未计算";
        view.rsquared_visible = true;
    }

    const long long dup = json_int_or_zero(
        json_get(metrics, "duplicate_wells_dropped"));
    if (dup > 0) {
        view.dup_text = std::to_string(dup) +
                        " 口同坐标井已去重（保留先录入值）";
        view.dup_visible = true;
    }
    return view;
}

// ---------------------------------------------------------------------------
// create_factor_map_dialog.py
// ---------------------------------------------------------------------------

const std::vector<std::string>& factor_map_factor_items() {
    static const std::vector<std::string> items = {
        "砂岩厚度", "地层厚度", "孔隙度", "渗透率", "TOC", "古水深", "砂地比"};
    return items;
}

const std::vector<std::string>& factor_map_default_horizons() {
    static const std::vector<std::string> items = {
        "T1", "T2", "T3", "E1s", "E2s", "E3s", "K1q"};
    return items;
}

const std::vector<std::pair<std::string, std::string>>&
factor_map_method_items() {
    static const std::vector<std::pair<std::string, std::string>> items = {
        {"克里金插值 (Ordinary Kriging)", "kriging"},
        {"反距离加权 (IDW)", "idw"},
    };
    return items;
}

const std::vector<std::string>& factor_map_ramp_items() {
    static const std::vector<std::string> items = {
        "porosity", "permeability", "sand_thickness", "thickness",
        "toc",      "water_depth",  "viridis",        "plasma",
        "magma",    "coolwarm",     "jet"};
    return items;
}

std::vector<std::string> factor_map_horizon_items(
    const std::string& stratigraphy_target) {
    std::vector<std::string> items;
    std::set<std::string> seen;
    if (!stratigraphy_target.empty() && seen.insert(stratigraphy_target).second) {
        items.push_back(stratigraphy_target);
    }
    for (const auto& horizon : factor_map_default_horizons()) {
        if (seen.insert(horizon).second) {
            items.push_back(horizon);
        }
    }
    return items;
}

FactorMapOutcome run_factor_map_job(const FactorMapParams& params,
                                    const FactorMapServiceFn& service,
                                    job::JobContext& ctx) {
    if (ctx.token().is_cancelled()) {
        return FactorMapOutcome{};
    }
    if (!service) {
        throw std::runtime_error(
            "geological mapping service is not configured");
    }
    FactorMapOutcome outcome = service(params);
    if (ctx.token().is_cancelled()) {
        return FactorMapOutcome{};
    }
    return outcome;
}

std::string factor_map_success_text(const std::string& title,
                                    long long layer_count) {
    return "成功生成地质图件：" + title + "\n包含 " +
           std::to_string(layer_count) + " 个 GIS 图层。";
}

std::string factor_map_failure_text(const std::string& message) {
    return "地质编图失败：" + message;
}

job::JobSpec make_factor_map_job_spec(
    FactorMapParams params, FactorMapServiceFn service,
    std::function<void(const FactorMapOutcome&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel) {
    job::JobSpec spec;
    spec.kind = "compute.factor_map";
    spec.title = "创建地质单因素图件";
    spec.run = [params = std::move(params), service = std::move(service)](
                   job::JobContext& ctx) -> std::any {
        try {
            return run_factor_map_job(params, service, ctx);
        } catch (const job::JobCancelled&) {
            throw;
        } catch (const std::exception& exc) {
            // Python failed(str(exc)) — plain message, no class prefix.
            throw std::runtime_error(exc.what());
        }
    };
    if (on_done) {
        spec.on_done = [on_done = std::move(on_done)](const std::any& result) {
            on_done(std::any_cast<const FactorMapOutcome&>(result));
        };
    }
    spec.on_fail = std::move(on_fail);
    spec.on_cancel = std::move(on_cancel);
    return spec;
}

}  // namespace pwb::ui_seqviz
