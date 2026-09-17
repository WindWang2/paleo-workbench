// Faithful port of the pure decision tree in
// paleo_workbench/interchange/preflight.py (plus the default
// FormatAdapter.plan_import and the registry bookkeeping the tree needs).

#include <pwb/interchange/preflight.hpp>

#include <pwb/interchange/path_safety.hpp>

#include <algorithm>
#include <stdexcept>

namespace pwb::interchange {

namespace {

// Python SNIFF_FORMAT_ALIASES mirror (content family -> adapter id).
const std::vector<std::pair<std::string, std::string>>& sniff_format_aliases() {
    static const std::vector<std::pair<std::string, std::string>> aliases = {
        {"geotiff", "raster"},
        {"gpkg", "vector_gdal"},
        {"shapefile", "vector_gdal"},
    };
    return aliases;
}

std::string join_errors(const PreflightReport& report) {
    std::string joined;
    for (const auto& issue : report.issues) {
        if (issue.severity == "error") {
            if (!joined.empty()) {
                joined += "；";
            }
            joined += issue.message;
        }
    }
    return joined;
}

Json string_array(const std::vector<std::string>& values) {
    Json out = Json::array();
    for (const auto& value : values) {
        out.push_back(value);
    }
    return out;
}

}  // namespace

Json InspectionResult::summary(const std::string& format_id) const {
    Json out = Json::object();
    out["format_id"] = format_id;
    out["ok"] = ok;
    out["size_bytes"] = size_bytes;
    out["crs"] = crs ? Json(*crs) : Json(nullptr);
    out["units"] = units;
    out["object_type"] = object_type;
    if (bounds) {
        Json list = Json::array();
        for (const double value : *bounds) {
            list.push_back(value);
        }
        out["bounds"] = list;
    } else {
        out["bounds"] = nullptr;
    }
    out["metadata"] = metadata;
    out["warnings"] = string_array(warnings);
    out["errors"] = string_array(errors);
    return out;
}

void Registry::register_adapter(AdapterSpec spec, bool replace) {
    if (spec.format_id.empty()) {
        throw std::invalid_argument("adapter must define format_id");
    }
    for (auto& existing : adapters_) {
        if (existing.format_id == spec.format_id) {
            if (!replace) {
                throw std::invalid_argument(
                    "duplicate adapter format_id: " + spec.format_id);
            }
            existing = std::move(spec);
            return;
        }
    }
    adapters_.push_back(std::move(spec));
}

const AdapterSpec* Registry::get(const std::string& format_id) const {
    for (const auto& adapter : adapters_) {
        if (adapter.format_id == format_id) {
            return &adapter;
        }
    }
    return nullptr;
}

const AdapterSpec* Registry::adapter_for_extension(
    const std::string& extension) const {
    for (const auto& adapter : adapters_) {
        if (std::find(adapter.extensions.begin(), adapter.extensions.end(),
                      extension)
            != adapter.extensions.end()) {
            return &adapter;
        }
    }
    return nullptr;
}

Json PreflightIssue::to_dict() const {
    Json out = Json::object();
    out["severity"] = severity;
    out["code"] = code;
    out["message"] = message;
    return out;
}

bool PreflightReport::ok() const {
    for (const auto& issue : issues) {
        if (issue.severity == "error") {
            return false;
        }
    }
    return true;
}

Json PreflightReport::to_dict() const {
    Json out = Json::object();
    out["path"] = path;
    Json sniff_out = Json::object();
    sniff_out["format_id"] = sniff.format_id;
    sniff_out["confidence"] = sniff.confidence;
    sniff_out["evidence"] = sniff.evidence;
    out["sniff"] = sniff_out;
    out["adapter_id"] = adapter_id ? Json(*adapter_id) : Json(nullptr);
    out["inspection"] = inspection ? Json(*inspection) : Json(nullptr);
    Json issue_list = Json::array();
    for (const auto& issue : issues) {
        issue_list.push_back(issue.to_dict());
    }
    out["issues"] = issue_list;
    out["recommendation"] = recommendation;
    out["estimated_disk_bytes"] = estimated_disk_bytes;
    out["ok"] = ok();
    return out;
}

Json ImportPlan::to_dict() const {
    Json out = Json::object();
    out["format_id"] = format_id;
    out["source_path"] = source_path;
    out["action"] = action;
    out["asset_name"] = asset_name;
    out["warnings"] = string_array(warnings);
    out["estimated_bytes"] = estimated_bytes;
    out["transform"] = transform ? Json(*transform) : Json(nullptr);
    out["metadata"] = metadata;
    out["options"] = options;
    return out;
}

std::string path_suffix_lower(const std::filesystem::path& path) {
    const std::string name = path.filename().string();
    const std::size_t dot = name.rfind('.');
    if (dot == std::string::npos || dot == 0 || dot + 1 >= name.size()) {
        return "";
    }
    std::string suffix = name.substr(dot + 1);
    for (char& ch : suffix) {
        if (ch >= 'A' && ch <= 'Z') {
            ch = static_cast<char>(ch - 'A' + 'a');
        }
    }
    return suffix;
}

PreflightReport ImportPreflightService::inspect(
    const std::filesystem::path& path) const {
    PreflightReport report;
    report.path = path.string();
    const std::string extension = path_suffix_lower(path);

    std::error_code ec;
    if (!std::filesystem::exists(path, ec)) {
        report.sniff = SniffResult{"", "low", "missing-file", extension};
        report.issues.push_back({"error", "missing-file", "文件不存在"});
        return report;
    }
    if (std::filesystem::is_directory(path, ec)) {
        report.sniff = SniffResult{"", "low", "directory", ""};
        report.issues.push_back({"error", "directory", "目录导入请使用批量服务"});
        return report;
    }

    if (sniffer_ != nullptr) {
        report.sniff = sniffer_(path);
    }

    const std::string sniffed_id = [&] {
        for (const auto& [family, adapter_id] : sniff_format_aliases()) {
            if (family == report.sniff.format_id) {
                return adapter_id;
            }
        }
        return report.sniff.format_id;
    }();

    const AdapterSpec* adapter =
        report.sniff.determined() ? registry_.get(sniffed_id) : nullptr;
    if (adapter == nullptr) {
        const AdapterSpec* extension_adapter =
            registry_.adapter_for_extension(extension);
        if (extension_adapter != nullptr && report.sniff.determined()) {
            if (report.sniff.confidence == "high") {
                // Content conclusively contradicts the extension: refuse
                // rather than parse a mislabeled file.
                report.issues.push_back(
                    {"error", "extension-content-mismatch",
                     "扩展名 ." + extension + " 指向 "
                         + extension_adapter->format_id + "，但内容嗅探为 "
                         + report.sniff.format_id + "（" + report.sniff.evidence
                         + "）"});
                adapter = nullptr;
            } else {
                // Advisory sniff: trust the extension, surface the doubt.
                report.issues.push_back(
                    {"warning", "sniff-advisory",
                     "内容嗅探提示 " + report.sniff.format_id + "（"
                         + report.sniff.evidence + "，置信度 "
                         + report.sniff.confidence + "）；按扩展名按 "
                         + extension_adapter->format_id + " 解析"});
                adapter = extension_adapter;
            }
        } else if (extension_adapter != nullptr) {
            adapter = extension_adapter;
        }
    } else if (!extension.empty()
               && std::find(adapter->extensions.begin(), adapter->extensions.end(),
                            extension)
                   == adapter->extensions.end()) {
        report.issues.push_back(
            {"warning", "extension-mismatch",
             "内容识别为 " + report.sniff.format_id + "，但扩展名为 ."
                 + extension});
    }

    if (adapter == nullptr) {
        report.issues.push_back(
            {"error", "format-unknown", "无法识别格式（无内容特征且扩展名未注册）"});
        report.recommendation = "unavailable";
        return report;
    }

    InspectionResult inspection = adapter->inspect(path.string());
    for (const auto& error : inspection.errors) {
        report.issues.push_back({"error", "inspect-error", error});
    }
    for (const auto& warning : inspection.warnings) {
        report.issues.push_back({"warning", "inspect-warning", warning});
    }

    std::string recommendation;
    if (!adapter->import_data) {
        report.issues.push_back(
            {"error", "import-unavailable",
             adapter->notes.empty() ? adapter->format_id + " 不支持导入"
                                    : adapter->notes});
        recommendation = "unavailable";
    } else if (!inspection.ok) {
        recommendation = "unavailable";
    } else {
        recommendation = "managed_copy";
    }
    report.adapter_id = adapter->format_id;
    report.inspection = inspection.summary(adapter->format_id);
    report.recommendation = recommendation;
    report.estimated_disk_bytes = inspection.ok ? inspection.size_bytes : 0;
    return report;
}

ImportPlan ImportPreflightService::plan(const std::filesystem::path& path,
                                        std::optional<bool> managed,
                                        std::optional<std::string> asset_name,
                                        Json options) const {
    const PreflightReport report = inspect(path);
    if (!report.ok() || !report.adapter_id.has_value()
        || !report.inspection.has_value()) {
        throw std::runtime_error(
            !join_errors(report).empty()
                ? join_errors(report)
                : "preflight 未通过，无法生成导入计划");
    }
    const AdapterSpec* adapter = registry_.get(*report.adapter_id);
    if (adapter == nullptr) {
        throw std::runtime_error("未知适配器: " + *report.adapter_id);
    }
    // Default FormatAdapter.plan_import.
    const bool inspection_ok =
        report.inspection.has_value() && report.inspection->at("ok").get<bool>();
    const std::string action =
        !inspection_ok ? "unsupported"
                       : (managed.value_or(true) ? "managed_copy"
                                                 : "link_external");
    ImportPlan plan_value;
    plan_value.format_id = adapter->format_id;
    plan_value.source_path = path.string();
    plan_value.action = action;
    plan_value.asset_name =
        (!asset_name.has_value() || asset_name->empty())
        ? path.filename().string()
        : *asset_name;
    if (report.inspection.has_value()) {
        // The frozen inspection summary carries warnings/errors verbatim;
        // the plan copies the warnings list.
        for (const auto& warning :
             report.inspection->at("warnings")) {
            plan_value.warnings.push_back(warning.get<std::string>());
        }
        plan_value.estimated_bytes =
            report.inspection->at("size_bytes").get<long long>();
        plan_value.metadata = report.inspection->at("metadata");
    }
    plan_value.options = options.is_null() ? Json::object() : options;
    return plan_value;
}

}  // namespace pwb::interchange
