#include <pwb/ui_wellseis/run_diagnostic.hpp>

#include <algorithm>
#include <cctype>

#include <pwb/ui_wellseis/json_helpers.hpp>
#include <pwb/ui_wellseis/redact.hpp>

namespace pwb::ui_wellseis {

const std::vector<std::string> kOnlineWellLogWorkflows = {
    "geoviz_online_well_log_facies", "inference_api_well_log_facies"};

namespace {

std::string ascii_lower(std::string value) {
    for (char& c : value) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return value;
}

// str(value) parity for JSON scalars used in diagnostic lines.
std::string json_param_str(const Json& parameters, const char* key) {
    const Json& v = json_field(parameters, key);
    if (v.is_string()) {
        return v.get<std::string>();
    }
    if (v.is_number_integer() || v.is_number_unsigned()) {
        return std::to_string(v.get<long long>());
    }
    if (v.is_number_float()) {
        return v.dump();
    }
    if (v.is_boolean()) {
        return v.get<bool>() ? "True" : "False";
    }
    return "";
}

// Python truthiness for a parameter value.
bool json_param_truthy(const Json& parameters, const char* key) {
    const Json& v = json_field(parameters, key);
    if (v.is_null()) {
        return false;
    }
    if (v.is_boolean()) {
        return v.get<bool>();
    }
    if (v.is_number()) {
        return v.get<double>() != 0.0;
    }
    if (v.is_string()) {
        return !v.get<std::string>().empty();
    }
    if (v.is_array() || v.is_object()) {
        return !v.empty();
    }
    return false;
}

// str(item) for set-membership in well_log_resource_ids.
bool params_mention_resource(const Json& parameters,
                             const std::string& resource_id) {
    for (const Json& item : json_array(parameters, "well_log_resource_ids")) {
        if (item.is_string() && item.get<std::string>() == resource_id) {
            return true;
        }
        if (item.is_number_integer() || item.is_number_unsigned()) {
            if (std::to_string(item.get<long long>()) == resource_id) {
                return true;
            }
        }
    }
    return false;
}

std::string join_lines(const std::vector<std::string>& lines) {
    std::string out;
    for (std::size_t i = 0; i < lines.size(); ++i) {
        if (i != 0) {
            out += "\n";
        }
        out += lines[i];
    }
    return out;
}

}  // namespace

const RunSlice* latest_failed_online_run(const std::vector<RunSlice>& runs,
                                         const std::string& resource_id) {
    if (resource_id.empty()) {
        return nullptr;
    }
    const RunSlice* latest = nullptr;
    for (const RunSlice& run : runs) {
        if (ascii_lower(run.status) != "failed") {
            continue;
        }
        const std::string workflow = json_param_str(run.parameters, "workflow");
        if (std::find(kOnlineWellLogWorkflows.begin(),
                      kOnlineWellLogWorkflows.end(),
                      workflow) == kOnlineWellLogWorkflows.end()) {
            continue;
        }
        if (!params_mention_resource(run.parameters, resource_id)) {
            continue;
        }
        // max(runs, key=created_at) — string compare keeps first on ties.
        if (latest == nullptr || run.created_at > latest->created_at) {
            latest = &run;
        }
    }
    return latest;
}

std::string run_error_text(const RunSlice& run) {
    const Json& v = json_field(run.parameters, "error");
    if (v.is_string() && !v.get<std::string>().empty()) {
        return v.get<std::string>();
    }
    return "未知错误";
}

std::string run_diagnostic_log(const RunSlice* run,
                               const std::string& status,
                               const std::string& error,
                               const ResourceSlice* resource) {
    const Json parameters = run != nullptr ? run->parameters : Json::object();
    const std::string endpoint =
        redact_endpoint(json_param_str(parameters, "online_endpoint"));
    const std::string resource_name =
        resource != nullptr && !resource->name.empty() ? resource->name
                                                       : "未解析";
    const std::string resource_id = resource != nullptr ? resource->id : "";

    std::vector<std::string> lines;
    lines.push_back("线上测井预测运行日志");
    lines.push_back("状态: " + status);
    lines.push_back("运行 ID: " +
                    (run != nullptr && !run->id.empty() ? run->id : "未创建"));
    lines.push_back("井数据: " + resource_name +
                    (resource_id.empty() ? "" : " (" + resource_id + ")"));
    {
        const std::string version =
            json_param_str(parameters, "model_version");
        lines.push_back("模型版本: " +
                        (version.empty() ? std::string("未记录") : version));
    }
    if (!endpoint.empty()) {
        lines.push_back("服务地址: " + endpoint);
    }
    if (json_param_truthy(parameters, "online_model_version_id")) {
        lines.push_back("远端模型 ID: " +
                        json_param_str(parameters, "online_model_version_id"));
    }
    if (json_param_truthy(parameters, "online_wait_timeout_seconds")) {
        lines.push_back(
            "同步等待: " +
            json_param_str(parameters, "online_wait_timeout_seconds") + " 秒");
    }
    if (json_param_truthy(parameters, "online_request_timeout_seconds")) {
        lines.push_back(
            "请求超时: " +
            json_param_str(parameters, "online_request_timeout_seconds") +
            " 秒");
    } else if (json_param_truthy(parameters, "online_timeout_seconds")) {
        lines.push_back(
            "请求超时: " +
            json_param_str(parameters, "online_timeout_seconds") + " 秒");
    }
    if (json_param_truthy(parameters, "online_poll_timeout_seconds")) {
        lines.push_back(
            "轮询超时: " +
            json_param_str(parameters, "online_poll_timeout_seconds") + " 秒");
    }
    if (!error.empty()) {
        lines.push_back("错误:");
        lines.push_back(redact_diagnostic_text(error));
    }
    return join_lines(lines);
}

}  // namespace pwb::ui_wellseis
