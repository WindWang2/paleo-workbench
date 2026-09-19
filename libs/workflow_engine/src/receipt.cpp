// CONV-32 — dag/receipt.py port (frozen header receipt.hpp). Python is
// authoritative; coercions in from_dict are total (never throw) with the
// Python defaults, and to_dict emits keys in the frozen member order with
// duration_ms rounded through Python's decimal half-to-even round(x, 3).
#include <pwb/workflow_engine/receipt.hpp>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <utility>

namespace pwb::workflow_engine {
namespace {

// Python round(x, 3): correctly-rounded decimal rounding of the EXACT
// binary value, half-to-even, returning the nearest double to the rounded
// decimal (what json.dumps then prints shortest-round-trip). Formatting
// through %.3f and re-parsing reproduces it bit-for-bit — std::round(x*1000)
// would round to a binary multiple instead and drift by one ulp.
double python_round3(double value) {
    if (!std::isfinite(value)) return value;
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.3f", value);
    return std::strtod(buffer, nullptr);
}

// Python repr() of a float: shortest round-trip digits, ".0" kept for
// integral values (only the str() coercions of stray non-string fields can
// reach this; receipts carry strings).
std::string py_repr_double(double value) {
    if (std::isnan(value)) return "nan";
    if (std::isinf(value)) return value > 0 ? "inf" : "-inf";
    char buffer[64] = {0};
    for (int precision = 1; precision <= 17; ++precision) {
        std::snprintf(buffer, sizeof(buffer), "%.*g", precision, value);
        if (std::strtod(buffer, nullptr) == value) break;
    }
    std::string text(buffer);
    if (text.find('.') == std::string::npos && text.find('e') == std::string::npos
        && text.find('E') == std::string::npos) {
        text += ".0";
    }
    return text;
}

// Python str() of a JSON value (str(None) == "None", str(True) == "True",
// numbers via repr). Containers would print through Python repr(); the
// JSON dump fallback only guards totality and is unreachable for receipts.
std::string py_str(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_null()) return "None";
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_number_integer() || value.is_number_unsigned()) {
        return std::to_string(value.get<long long>());
    }
    if (value.is_number_float()) return py_repr_double(value.get<double>());
    return value.dump();
}

// bool(x) Python truthiness (never throws).
bool py_truthy(const Json& value) {
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number()) return value.get<double>() != 0.0;
    if (value.is_string()) return !value.get<std::string>().empty();
    return !value.empty();
}

// str(data.get(key, default)) — null presence yields "None" exactly like
// Python str(None).
std::string str_field(const Json& data, const char* key,
                      std::string fallback = "") {
    if (!data.is_object()) return fallback;
    const auto it = data.find(key);
    if (it == data.end()) return fallback;
    return py_str(*it);
}

// data.get(key) passthrough for optional strings (absent/null -> nullopt).
std::optional<std::string> opt_string(const Json& data, const char* key) {
    if (!data.is_object()) return std::nullopt;
    const auto it = data.find(key);
    if (it == data.end() || it->is_null()) return std::nullopt;
    if (it->is_string()) return it->get<std::string>();
    return py_str(*it);
}

// dict(data.get(key) or {}) — non-object (or empty) -> {}.
Json dict_or_empty(const Json& data, const char* key) {
    if (!data.is_object()) return Json::object();
    const auto it = data.find(key);
    if (it == data.end() || !it->is_object()) return Json::object();
    return *it;
}

// tuple(data.get(key) or ()) — elements str()-coerced (Python keeps the
// raw values; receipts only ever carry strings).
std::vector<std::string> str_tuple(const Json& data, const char* key) {
    std::vector<std::string> out;
    if (!data.is_object()) return out;
    const auto it = data.find(key);
    if (it == data.end() || !it->is_array()) return out;
    for (const Json& item : *it) out.push_back(py_str(item));
    return out;
}

// float(data.get(key, fallback)) — total: non-numeric values fall back
// (Python would raise on them; from_dict is non-throwing by contract).
double float_field(const Json& data, const char* key, double fallback) {
    if (!data.is_object()) return fallback;
    const auto it = data.find(key);
    if (it == data.end() || it->is_null()) return fallback;
    if (it->is_number()) return it->get<double>();
    if (it->is_boolean()) return it->get<bool>() ? 1.0 : 0.0;
    if (it->is_string()) {
        const std::string text = it->get<std::string>();
        char* end = nullptr;
        const double parsed = std::strtod(text.c_str(), &end);
        if (end != nullptr && end != text.c_str() && *end == '\0') {
            return parsed;
        }
    }
    return fallback;
}

// int(data.get(key, fallback)) — truncation toward zero for floats.
int int_field(const Json& data, const char* key, int fallback) {
    if (!data.is_object()) return fallback;
    const auto it = data.find(key);
    if (it == data.end() || it->is_null()) return fallback;
    if (it->is_number_integer() || it->is_number_unsigned()) {
        return static_cast<int>(it->get<long long>());
    }
    if (it->is_number_float()) {
        return static_cast<int>(it->get<double>());
    }
    if (it->is_boolean()) return it->get<bool>() ? 1 : 0;
    if (it->is_string()) {
        const std::string text = it->get<std::string>();
        char* end = nullptr;
        const long parsed = std::strtol(text.c_str(), &end, 10);
        if (end != nullptr && end != text.c_str() && *end == '\0') {
            return static_cast<int>(parsed);
        }
    }
    return fallback;
}

// optional timestamps: data.get(key) — absent/null -> nullopt, number ->
// double (Python keeps int timestamps as ints; the JSON surface only ever
// sees the fractional epoch values the harness emits).
std::optional<double> opt_double(const Json& data, const char* key) {
    if (!data.is_object()) return std::nullopt;
    const auto it = data.find(key);
    if (it == data.end() || it->is_null()) return std::nullopt;
    if (it->is_number()) return it->get<double>();
    if (it->is_boolean()) return it->get<bool>() ? 1.0 : 0.0;
    return std::nullopt;
}

Json string_array(const std::vector<std::string>& values) {
    Json array = Json::array();
    for (const std::string& value : values) array.push_back(value);
    return array;
}

}  // namespace

// ------------------------------------------------------ EnvironmentIdentity --

Json EnvironmentIdentity::to_dict() const {
    Json dict;
    dict["python"] = python;
    dict["platform"] = platform;
    dict["workbench"] = workbench;
    return dict;
}

// --------------------------------------------------------- ExecutionReceipt --

Json ExecutionReceipt::to_dict() const {
    Json dict;
    dict["schema_version"] = schema_version;
    dict["node_id"] = node_id.has_value() ? Json(*node_id) : Json(nullptr);
    dict["workflow_run_id"] =
        workflow_run_id.has_value() ? Json(*workflow_run_id) : Json(nullptr);
    dict["action_id"] = action_id;
    dict["action_version"] = action_version;
    dict["description"] = description;
    dict["parameters"] = parameters;
    dict["input_version_ids"] = string_array(input_version_ids);
    dict["provider_id"] =
        provider_id.has_value() ? Json(*provider_id) : Json(nullptr);
    dict["provider_version"] =
        provider_version.has_value() ? Json(*provider_version) : Json(nullptr);
    dict["resource_category"] = resource_category.has_value()
                                    ? Json(*resource_category)
                                    : Json(nullptr);
    dict["estimated_resources"] = estimated_resources;
    dict["status"] = status;
    dict["started_at"] = started_at.has_value() ? Json(*started_at) : Json(nullptr);
    dict["finished_at"] =
        finished_at.has_value() ? Json(*finished_at) : Json(nullptr);
    dict["duration_ms"] = python_round3(duration_ms);
    dict["output_version_ids"] = string_array(output_version_ids);
    dict["outputs_summary"] = outputs_summary;
    dict["catalog_run_id"] =
        catalog_run_id.has_value() ? Json(*catalog_run_id) : Json(nullptr);
    dict["verification"] = verification;
    dict["qc_metrics"] = qc_metrics;
    dict["warnings"] = string_array(warnings);
    dict["degraded_reason"] =
        degraded_reason.has_value() ? Json(*degraded_reason) : Json(nullptr);
    dict["error"] = error.has_value() ? Json(*error) : Json(nullptr);
    dict["cache_identity"] =
        cache_identity.has_value() ? Json(*cache_identity) : Json(nullptr);
    dict["from_cache"] = from_cache;
    dict["attempt"] = attempt;
    // Shallow copy (Python dict(self.environment)).
    dict["environment"] = environment;
    return dict;
}

ExecutionReceipt ExecutionReceipt::from_dict(const Json& data) {
    ExecutionReceipt receipt;
    receipt.schema_version = str_field(data, "schema_version",
                                       std::string(kReceiptSchemaVersion));
    receipt.node_id = opt_string(data, "node_id");
    receipt.workflow_run_id = opt_string(data, "workflow_run_id");
    receipt.action_id = str_field(data, "action_id");
    receipt.action_version = str_field(data, "action_version");
    receipt.description = str_field(data, "description");
    receipt.parameters = dict_or_empty(data, "parameters");
    receipt.input_version_ids = str_tuple(data, "input_version_ids");
    receipt.provider_id = opt_string(data, "provider_id");
    receipt.provider_version = opt_string(data, "provider_version");
    receipt.resource_category = opt_string(data, "resource_category");
    receipt.estimated_resources = dict_or_empty(data, "estimated_resources");
    receipt.status = str_field(data, "status", "success");
    receipt.started_at = opt_double(data, "started_at");
    receipt.finished_at = opt_double(data, "finished_at");
    receipt.duration_ms = float_field(data, "duration_ms", 0.0);
    receipt.output_version_ids = str_tuple(data, "output_version_ids");
    receipt.outputs_summary = dict_or_empty(data, "outputs_summary");
    receipt.catalog_run_id = opt_string(data, "catalog_run_id");
    receipt.verification = dict_or_empty(data, "verification");
    receipt.qc_metrics = dict_or_empty(data, "qc_metrics");
    if (data.is_object()) {
        const auto it = data.find("warnings");
        if (it != data.end() && it->is_array()) {
            for (const Json& warning : *it) {
                receipt.warnings.push_back(py_str(warning));
            }
        }
    }
    receipt.degraded_reason = opt_string(data, "degraded_reason");
    receipt.error = opt_string(data, "error");
    receipt.cache_identity = opt_string(data, "cache_identity");
    if (data.is_object()) {
        const auto it = data.find("from_cache");
        if (it != data.end()) receipt.from_cache = py_truthy(*it);
    }
    receipt.attempt = int_field(data, "attempt", 1);
    receipt.environment = dict_or_empty(data, "environment");
    return receipt;
}

// ------------------------------------------------------------ build_receipt --

ExecutionReceipt build_receipt(const ActionResultView& result,
                               const BuildReceiptArgs& args,
                               EnvironmentProvider env, Clock clock) {
    // provenance = result.metrics.get("provenance") or {}
    Json provenance = Json::object();
    if (result.metrics.is_object()) {
        const auto it = result.metrics.find("provenance");
        if (it != result.metrics.end() && it->is_object() && !it->empty()) {
            provenance = *it;
        }
    }

    ExecutionReceipt receipt;
    receipt.node_id = args.node_id;
    receipt.workflow_run_id = args.workflow_run_id;
    receipt.action_id = args.action_id;
    receipt.action_version = args.action_version;
    receipt.description = args.description;
    receipt.parameters = args.parameters;
    receipt.input_version_ids = args.input_version_ids;
    receipt.provider_id = opt_string(provenance, "provider_id");
    receipt.provider_version = opt_string(provenance, "provider_version");
    receipt.resource_category = args.resource_category;
    receipt.estimated_resources =
        args.estimated_resources.is_object() ? args.estimated_resources
                                             : Json::object();
    receipt.status = result.status;
    receipt.started_at = args.started_at;
    receipt.finished_at = clock();
    receipt.duration_ms = result.elapsed_ms;  // raw; to_dict rounds to 3dp
    receipt.output_version_ids =
        collect_output_version_ids(result.outputs);
    receipt.outputs_summary = summarize_outputs(result.outputs);
    receipt.catalog_run_id = opt_string(provenance, "run_id");
    receipt.verification =
        result.verification.is_object() ? result.verification : Json::object();
    // qc_metrics = metrics minus "provenance", insertion order kept.
    if (result.metrics.is_object()) {
        for (const auto& [key, value] : result.metrics.items()) {
            if (key != "provenance") receipt.qc_metrics[key] = value;
        }
    }
    receipt.warnings = result.warnings;
    if (result.status == "degraded") {
        std::string joined;
        for (const std::string& warning : result.warnings) {
            if (!joined.empty()) joined += "; ";
            joined += warning;
        }
        receipt.degraded_reason =
            joined.empty() ? std::string("verification warnings") : joined;
    }
    receipt.error = result.error;
    receipt.cache_identity = args.cache_identity;
    receipt.from_cache = args.from_cache;
    receipt.attempt = args.attempt;
    receipt.environment = env().to_dict();
    return receipt;
}

// --------------------------------------------------- version id collection --

std::vector<std::string> collect_output_version_ids(const Json& outputs) {
    std::vector<std::string> ids;
    if (!outputs.is_object()) return ids;

    // artifacts[].version: a dict with truthy "version_id" counts (the
    // DataVersionRef branch has no JSON shape; a plain-string version —
    // like {"version": "v1"} — does NOT count, mirroring Python).
    const auto artifacts = outputs.find("artifacts");
    if (artifacts != outputs.end() && artifacts->is_array()) {
        for (const Json& artifact : *artifacts) {
            if (!artifact.is_object()) continue;
            const auto version = artifact.find("version");
            if (version == artifact.end() || !version->is_object()) continue;
            const auto version_id = version->find("version_id");
            if (version_id == version->end() || !py_truthy(*version_id)) {
                continue;
            }
            ids.push_back(py_str(*version_id));
        }
    }

    // version_ids: declared plain-handler version ids, truthy ones only.
    const auto declared = outputs.find("version_ids");
    if (declared != outputs.end() && declared->is_array()) {
        for (const Json& value : *declared) {
            if (py_truthy(value)) ids.push_back(py_str(value));
        }
    }

    // Singular contract: actions returning exactly one catalog version.
    const auto singular = outputs.find("version_id");
    if (singular != outputs.end() && singular->is_string()) {
        const std::string& value = singular->get_ref<const std::string&>();
        if (!value.empty()) ids.push_back(value);
    }

    // Dedupe keep-first, encounter order.
    std::vector<std::string> ordered;
    for (const std::string& id : ids) {
        bool seen = false;
        for (const std::string& existing : ordered) {
            if (existing == id) {
                seen = true;
                break;
            }
        }
        if (!seen) ordered.push_back(id);
    }
    return ordered;
}

// ---------------------------------------------------------- output summary --

Json summarize_outputs(const Json& outputs) {
    Json summary = Json::object();
    if (!outputs.is_object()) return summary;
    for (const auto& [key, value] : outputs.items()) {
        if (key == "artifacts") {
            summary["artifact_count"] =
                value.is_array() ? Json(static_cast<std::int64_t>(value.size()))
                                 : Json(nullptr);
            continue;
        }
        if (key == "values" || key == "map_document" || key == "document"
            || key == "composition") {
            summary[key] = "<in-process handle>";
            continue;
        }
        if (value.is_string() || value.is_number() || value.is_boolean()
            || value.is_null()) {
            summary[key] = value;  // JSON scalars pass through
        } else if (value.is_array()) {
            summary[key] = "<" + std::to_string(value.size()) + " items>";
        } else if (value.is_object()) {
            summary[key] = "<" + std::to_string(value.size()) + " keys>";
        } else {
            summary[key] = value.type_name();  // unreachable from JSON
        }
    }
    return summary;
}

}  // namespace pwb::workflow_engine
