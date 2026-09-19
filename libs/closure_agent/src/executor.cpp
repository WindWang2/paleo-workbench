// executor.cpp — the guarded pipeline (harness/executor.py port). Guard
// order, status mapping and message strings are frozen against the Python
// behaviour: guard refusals reject before any work; cancellation is a
// first-class terminal outcome; a missing production capability is honest
// unavailability; admission refusal (pressure shedding) is rejection.
#include <pwb/closure_agent/executor.hpp>

#include <pwb/providers/errors.hpp>
#include <pwb/providers/execution.hpp>
#include <pwb/providers/schema.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <exception>
#include <memory>

namespace pwb::closure_agent {

ActionPermissionError::ActionPermissionError(std::string action_id, ActionRisk risk)
    : std::runtime_error("action " + pwb::providers::python_repr(action_id) +
                         " requires " + to_string(risk) + " permission"),
      action_id_(std::move(action_id)),
      risk_(risk) {}

ActionValidationError::ActionValidationError(std::string action_id,
                                             std::vector<std::string> problems,
                                             std::string label)
    : std::runtime_error(label + " for " +
                         pwb::providers::python_repr(action_id) + " invalid: " +
                         [&] {
                             std::string joined;
                             for (std::size_t i = 0; i < problems.size(); ++i) {
                                 if (i) joined += "; ";
                                 joined += problems[i];
                             }
                             return joined;
                         }()),
      problems_(std::move(problems)) {}

bool ActionResult::ok() const {
    return status == to_string(ActionStatus::Success) ||
           status == to_string(ActionStatus::Degraded);
}

bool ActionResult::degraded() const {
    return status == to_string(ActionStatus::Degraded);
}

ActionStatus ActionResult::status_value() const {
    if (status == "success") return ActionStatus::Success;
    if (status == "degraded") return ActionStatus::Degraded;
    if (status == "cancelled") return ActionStatus::Cancelled;
    if (status == "rejected") return ActionStatus::Rejected;
    if (status == "unavailable") return ActionStatus::Unavailable;
    return ActionStatus::Failed;
}

Json ActionResult::to_dict() const {
    Json dict = Json::object();
    dict["action_id"] = action_id;
    dict["status"] = status;
    dict["outputs"] = outputs;
    dict["verification"] = verification;
    dict["warnings"] = warnings;
    dict["metrics"] = metrics;
    dict["error"] = error ? Json(*error) : Json(nullptr);
    Json elapsed = std::round(elapsed_ms * 1000.0) / 1000.0;
    dict["elapsed_ms"] = elapsed;
    return dict;
}

namespace {

double monotonic_ms() {
    using Clock = std::chrono::steady_clock;
    return std::chrono::duration<double, std::milli>(
               Clock::now().time_since_epoch())
        .count();
}

void check_cancelled(const ActionContext* context) {
    if (context == nullptr || !context->is_cancelled()) return;
    if (context->cancel != nullptr) {
        context->cancel->raise_if_cancelled();
    }
    throw providers::TaskCancelled("operation cancelled");
}

bool value_has_grid(const Json& value) {
    if (!value.is_object()) return false;
    return value.contains("grid_z");
}

// Flatten nested numeric arrays; null counts as nodata.
void collect_numbers(const Json& value, std::vector<double>& out,
                     std::size_t& nodata) {
    if (value.is_array()) {
        for (const auto& entry : value) collect_numbers(entry, out, nodata);
        return;
    }
    if (value.is_null()) {
        ++nodata;
        return;
    }
    if (value.is_number()) {
        out.push_back(value.get<double>());
        return;
    }
}

}  // namespace

Json ScientificValidator::validate_grid(const Json& grid,
                                        const std::string& label) const {
    Json report = Json::object();
    std::vector<std::string> reasons;
    std::string verdict{kVerdictPass};
    auto add = [&](const char* level, const std::string& reason) {
        reasons.push_back(reason);
        if (level == kVerdictFail ||
            (level == kVerdictWarning && verdict == kVerdictPass)) {
            verdict = level;
        }
    };
    Json array = grid;
    if (grid.is_object()) {
        const auto it = grid.find("grid_z");
        if (it != grid.end()) array = *it;
    }
    if (!array.is_array()) {
        report["verdict"] = kVerdictFail;
        report["reasons"] = std::vector<std::string>{
            label + ": output is not an array (" +
            pwb::providers::json_python_type_name(array) + ")"};
        return report;
    }
    std::vector<double> numbers;
    std::size_t nodata = 0;
    collect_numbers(array, numbers, nodata);
    const std::size_t total = numbers.size() + nodata;
    if (total == 0) {
        report["verdict"] = kVerdictFail;
        report["reasons"] = std::vector<std::string>{label + ": empty array"};
        return report;
    }
    const double finite_ratio =
        static_cast<double>(numbers.size()) / static_cast<double>(total);
    if (finite_ratio == 0.0) {
        add(kVerdictFail, label +
                              ": all values are NaN/nodata — computation "
                              "produced nothing");
    } else if (finite_ratio < (1.0 - max_nan_ratio)) {
        char buffer[64];
        std::snprintf(buffer, sizeof(buffer), "%.1f%%",
                      (1.0 - finite_ratio) * 100.0);
        add(kVerdictWarning,
            label + ": " + buffer + " NaN/nodata (coverage thin)");
    } else if (static_cast<int>(numbers.size()) < min_finite_values) {
        add(kVerdictWarning, label + ": only " +
                                 std::to_string(numbers.size()) +
                                 " finite values");
    }
    if (!numbers.empty()) {
        double vmin = numbers[0];
        double vmax = numbers[0];
        for (const double v : numbers) {
            vmin = std::min(vmin, v);
            vmax = std::max(vmax, v);
        }
        if (vmax < vmin) add(kVerdictFail, label + ": inverted value range");
        if (vmin == vmax) {
            add(kVerdictWarning,
                label + ": constant value " +
                    pwb::providers::python_repr(Json(vmin)) +
                    " (degenerate field)");
        }
    }
    report["verdict"] = verdict;
    report["reasons"] = reasons;
    return report;
}

namespace {

Json validation_report(const char* verdict, std::vector<std::string> reasons) {
    Json report = Json::object();
    report["verdict"] = verdict;
    report["reasons"] = std::move(reasons);
    return report;
}

}  // namespace

Json MapValidationHook::validate(const Json& document, const Json& composition,
                                 bool require_components) const {
    std::vector<std::string> reasons;
    std::string verdict{kVerdictPass};
    auto add = [&](const char* level, const std::string& reason) {
        reasons.push_back(reason);
        if (level == kVerdictFail ||
            (level == kVerdictWarning && verdict == kVerdictPass)) {
            verdict = level;
        }
    };
    const Json empty = Json::object();
    const Json& doc = document.is_object() ? document : empty;
    const Json& layers = doc.contains("layers") && doc["layers"].is_array()
                             ? doc["layers"]
                             : Json(Json::array());
    if (layers.empty()) {
        return validation_report(kVerdictFail, {"map: no layers"});
    }
    std::vector<const Json*> visible;
    for (const auto& layer : layers) {
        const auto it = layer.find("visible");
        if (it == layer.end() || it->is_null() || it->get<bool>()) {
            visible.push_back(&layer);
        }
    }
    if (visible.empty()) add(kVerdictFail, "map: all layers hidden");
    for (const auto* layer : visible) {
        const auto& features = layer->find("features") != layer->end()
                                   ? (*layer)["features"]
                                   : Json(nullptr);
        bool empty_layer = features.is_null();
        if (features.is_array() && !features.empty()) empty_layer = false;
        if (empty_layer) {
            std::string name = layer->contains("name") && (*layer)["name"].is_string()
                                   ? (*layer)["name"].get<std::string>()
                                   : (layer->contains("id") &&
                                              (*layer)["id"].is_string()
                                          ? (*layer)["id"].get<std::string>()
                                          : std::string("?"));
            add(kVerdictFail, "map: empty visible layers ['" + name + "']");
        }
    }
    const Json& extent =
        doc.contains("extent") && doc["extent"].is_array() &&
                doc["extent"].size() >= 4
            ? doc["extent"]
            : Json(nullptr);
    if (extent.is_null()) {
        add(kVerdictFail, "map: invalid extent None");
    } else {
        bool finite = true;
        for (const auto& v : extent) {
            if (!v.is_number() || !std::isfinite(v.get<double>())) finite = false;
        }
        if (!finite) {
            add(kVerdictFail, "map: invalid extent " +
                                  pwb::providers::python_repr(extent));
        } else {
            const double x0 = extent[0].get<double>();
            const double y0 = extent[1].get<double>();
            const double x1 = extent[2].get<double>();
            const double y1 = extent[3].get<double>();
            if (x1 <= x0 || y1 <= y0) {
                add(kVerdictFail,
                    "map: inverted extent [" + std::to_string(x0) + ", " +
                        std::to_string(y0) + ", " + std::to_string(x1) + ", " +
                        std::to_string(y1) + "]");
            }
        }
    }
    if (!doc.contains("crs") || doc["crs"].is_null()) {
        add(kVerdictWarning, "map: no declared CRS");
    }
    if (composition.is_object() && !composition.empty()) {
        std::vector<std::string> present;
        if (composition.contains("elements") && composition["elements"].is_array()) {
            for (const auto& element : composition["elements"]) {
                if (element.contains("element_type") &&
                    element["element_type"].is_string()) {
                    std::string type = element["element_type"].get<std::string>();
                    const auto pos = type.rfind('.');
                    if (pos != std::string::npos) type = type.substr(pos + 1);
                    for (auto& ch : type) ch = std::tolower(ch);
                    present.push_back(type);
                }
            }
        }
        const std::pair<const char*, const char*> needed[] = {
            {"legend", "legend binding"},
            {"scale_bar", "scale bar"},
            {"north_arrow", "north arrow"},
            {"title", "title"},
        };
        std::vector<std::string> missing;
        for (const auto& [key, label] : needed) {
            if (std::find(present.begin(), present.end(), key) == present.end()) {
                missing.push_back(label);
            }
        }
        if (!missing.empty()) {
            std::string joined = "[";
            for (std::size_t i = 0; i < missing.size(); ++i) {
                if (i) joined += ", ";
                joined += "'" + missing[i] + "'";
            }
            joined += "]";
            add(require_components ? kVerdictFail : kVerdictWarning,
                "composition: missing " + joined);
        }
        if (std::find(present.begin(), present.end(), "main_map") == present.end()) {
            add(kVerdictFail, "composition: no main map frame element");
        }
        if (!composition.contains("title") ||
            (composition["title"].is_string() &&
             composition["title"].get<std::string>().empty())) {
            add(kVerdictWarning, "composition: untitled map");
        }
    } else if (require_components) {
        add(kVerdictFail,
            "map: no composition attached (legend/scale/north arrow missing)");
    }
    return validation_report(verdict.c_str(), std::move(reasons));
}

HarnessExecutor::HarnessExecutor(const ActionRegistry& registry,
                                 ExecutorConfig config)
    : registry_(&registry), config_(std::move(config)) {
    if (!config_.scientific_validator) {
        ScientificValidator default_scientific;
        config_.scientific_validator =
            [default_scientific](const Json& grid, const std::string& label) {
                return default_scientific.validate_grid(grid, label);
            };
    }
    if (!config_.map_validator) {
        MapValidationHook default_map;
        config_.map_validator = [default_map](const Json& document,
                                              const Json& composition,
                                              bool require_components) {
            return default_map.validate(document, composition, require_components);
        };
    }
}

Json HarnessExecutor::execute_provider_action(const ActionSpec& spec,
                                              const Json& parameters,
                                              ActionContext& context,
                                              ActionResult& result) const {
    if (config_.providers == nullptr) {
        throw ActionUnavailableError(
            "provider registry unavailable for action " + spec.action_id);
    }
    providers::ProviderInputs inputs;
    if (context.active_volume.has_value()) {
        inputs.set("volume", *context.active_volume);
    }
    providers::ProviderContext provider_context = context.provider_context();
    providers::ProviderResult provider_result = providers::execute_provider(
        *config_.providers, *spec.provider_id, inputs, parameters,
        &provider_context, nullptr);
    for (const auto& warning : provider_result.warnings) {
        result.warnings.push_back(warning);
    }
    for (auto it = provider_result.metrics.begin();
         it != provider_result.metrics.end(); ++it) {
        result.metrics[it.key()] = it.value();
    }
    result.metrics["provenance"] = provider_result.provenance;
    Json values = Json::array();
    Json artifacts = Json::array();
    for (const auto& artifact : provider_result.artifacts) {
        artifacts.push_back(artifact.to_json());
        if (!artifact.value.is_null()) values.push_back(artifact.value);
    }
    Json payload = Json::object();
    payload["provider"] = *spec.provider_id;
    payload["artifacts"] = artifacts;
    if (!values.empty()) payload["values"] = values;
    return payload;
}

Json HarnessExecutor::verify(const ActionSpec& spec, const Json& payload,
                             const Json& parameters,
                             ActionContext& context) const {
    Json verification = Json::object();
    std::vector<Json> grid_reports;
    std::vector<Json> values;
    if (payload.is_object()) {
        const auto it = payload.find("values");
        if (it != payload.end() && it->is_array()) {
            for (const auto& value : *it) values.push_back(value);
        }
    } else if (!payload.is_null()) {
        values.push_back(payload);
    }
    for (const auto& value : values) {
        if (value_has_grid(value) || value.is_array()) {
            grid_reports.push_back(
                config_.scientific_validator(value, spec.action_id));
        }
    }
    if (!grid_reports.empty()) {
        std::string worst{kVerdictPass};
        std::vector<std::string> reasons;
        for (const auto& report : grid_reports) {
            const std::string& verdict = report["verdict"].get<std::string>();
            if (verdict == kVerdictFail) worst = kVerdictFail;
            if (worst != kVerdictFail && verdict == kVerdictWarning) {
                worst = kVerdictWarning;
            }
            for (const auto& reason : report["reasons"]) reasons.push_back(reason);
        }
        verification["verdict"] = worst;
        verification["reasons"] = reasons;
        verification["grids"] = grid_reports;
    }
    // Map validation: actions flag a map document explicitly.
    const Json* document = nullptr;
    if (payload.is_object()) {
        const auto it = payload.find("map_document");
        if (it != payload.end() && it->is_object()) document = &(*it);
        if (document == nullptr) {
            const auto other = payload.find("document");
            if (other != payload.end() && other->is_object()) document = &(*other);
        }
    }
    if (document != nullptr && document->contains("layers")) {
        const Json* composition = nullptr;
        if (payload.is_object()) {
            const auto it = payload.find("composition");
            if (it != payload.end()) composition = &(*it);
        }
        const bool require =
            parameters.is_object() && parameters.contains("require_components") &&
            parameters["require_components"].is_boolean() &&
            parameters["require_components"].get<bool>();
        Json report = config_.map_validator(
            *document, composition ? *composition : Json(nullptr), require);
        verification = merge_verification(verification, "map", report);
    }
    return verification;
}

Json HarnessExecutor::merge_verification(const Json& verification,
                                         const std::string& key,
                                         const Json& report) {
    if (!verification.is_object() || verification.empty()) {
        Json merged = report;
        merged[key] = report;
        return merged;
    }
    const std::string& left = verification["verdict"].get<std::string>();
    const std::string& right =
        report.contains("verdict") && report["verdict"].is_string()
            ? report["verdict"].get<std::string>()
            : std::string(kVerdictFail);
    std::string worst{kVerdictPass};
    if (left == kVerdictFail || right == kVerdictFail) {
        worst = kVerdictFail;
    } else if (left == kVerdictWarning || right == kVerdictWarning) {
        worst = kVerdictWarning;
    }
    // Key order parity with the Python dict literal: verdict, reasons,
    // <key>, then the verification's extra keys (ordered JSON freezes it).
    Json merged = Json::object();
    merged["verdict"] = worst;
    std::vector<std::string> reasons;
    if (verification.contains("reasons") && verification["reasons"].is_array()) {
        for (const auto& reason : verification["reasons"]) reasons.push_back(reason);
    }
    if (report.contains("reasons") && report["reasons"].is_array()) {
        for (const auto& reason : report["reasons"]) reasons.push_back(reason);
    }
    merged["reasons"] = reasons;
    merged[key] = report;
    for (auto it = verification.begin(); it != verification.end(); ++it) {
        if (it.key() == "verdict" || it.key() == "reasons") continue;
        merged[it.key()] = it.value();
    }
    return merged;
}

ActionResult HarnessExecutor::execute(const std::string& action_id,
                                      const Json& parameters,
                                      ActionContext* context) const {
    ActionContext default_context;
    ActionContext& ctx = context != nullptr ? *context : default_context;
    Json params = parameters.is_object() ? parameters : Json::object();
    const double t0 = monotonic_ms();
    ActionResult result;
    result.action_id = action_id;
    // RAII stand-in for Python's `finally: lease.release()` — every return
    // path releases the admission lease exactly once.
    struct LeaseGuard {
        std::unique_ptr<providers::IAdmissionLease> lease;
        ~LeaseGuard() {
            if (lease) lease->release();
        }
    } lease_guard;

    const ActionSpec* spec = nullptr;
    try {
        spec = &registry_->get(action_id);
    } catch (const std::exception& exc) {
        result.status = to_string(ActionStatus::Rejected);
        result.error = exc.what();
        result.elapsed_ms = monotonic_ms() - t0;
        return result;
    }

    try {
        check_cancelled(&ctx);
        // Python harness executor uses the validator's default root label.
        auto problems =
            providers::validate_parameters(spec->input_schema.is_object()
                                               ? spec->input_schema
                                               : Json(Json::object()),
                                           params);
        if (!problems.empty()) {
            throw ActionValidationError(action_id, std::move(problems));
        }
        if (!ctx.permits(spec->risk)) {
            throw ActionPermissionError(action_id, spec->risk);
        }
        for (const auto& attr : spec->required_context) {
            if (!ctx.has(attr)) {
                // Message parity with the Python ActionContextError text for
                // a single missing attribute.
                std::string joined;
                for (std::size_t i = 0; i < spec->required_context.size(); ++i) {
                    if (i) joined += ", ";
                    joined += spec->required_context[i];
                }
                throw ActionContextError(
                    "action " + pwb::providers::python_repr(action_id) +
                    " requires context." + attr + " (" + joined + " must be set)");
            }
        }
    } catch (const providers::TaskCancelled& exc) {
        result.status = to_string(ActionStatus::Cancelled);
        result.error = std::string("cancelled: ") + exc.what();
        result.elapsed_ms = monotonic_ms() - t0;
        return result;
    } catch (const std::exception& exc) {
        // Guard refusals happen before any work: rejected, never failed.
        result.status = to_string(ActionStatus::Rejected);
        result.error = exc.what();
        result.elapsed_ms = monotonic_ms() - t0;
        return result;
    }

    try {
        check_cancelled(&ctx);
        if (config_.admission != nullptr) {
            const Json profile = spec->effective_resource_profile();
            const auto cores = profile.find("estimated_cpu_cores");
            const auto ram = profile.find("estimated_ram_bytes");
            const auto vram = profile.find("estimated_vram_bytes");
            const auto io = profile.find("io_weight");
            providers::AdmissionRequest request;
            request.category = spec->category;
            request.title = "action:" + spec->action_id;
            request.estimated_cpu_cores =
                cores != profile.end() && cores->is_number() ? cores->get<double>()
                                                             : 0.5;
            request.estimated_ram_bytes =
                ram != profile.end() && ram->is_number_integer()
                    ? ram->get<long long>()
                    : 0;
            request.estimated_vram_bytes =
                vram != profile.end() && vram->is_number_integer()
                    ? vram->get<long long>()
                    : 0;
            request.io_weight =
                io != profile.end() && io->is_number() ? io->get<double>() : 0.5;
            lease_guard.lease = config_.admission->admit(request);
            ctx.extras["admission_lease"] = Json::object();
            ctx.extras["admission_lease"]["ptr"] =
                static_cast<long long>(
                    reinterpret_cast<std::intptr_t>(lease_guard.lease.get()));
        }
        Json payload;
        if (spec->provider_id.has_value()) {
            payload = execute_provider_action(*spec, params, ctx, result);
        } else {
            if (!spec->handler) {
                throw std::runtime_error("action " + spec->action_id +
                                         " has neither handler nor provider");
            }
            payload = spec->handler(&ctx, params);
        }
        // Output schema gate (#1178): a shape-mismatched result never
        // passes. Python validates the WRAPPED result.outputs (a non-dict
        // payload is wrapped as {"value": payload}) — mirror that exactly,
        // including the ActionValidationError message template.
        result.outputs = payload.is_object() ? payload : Json(Json::object());
        if (!payload.is_null() && !payload.is_object()) {
            result.outputs = Json::object();
            result.outputs["value"] = payload;
        }
        if (spec->output_schema.is_object() && !spec->output_schema.empty()) {
            auto out_problems = providers::validate_parameters(
                spec->output_schema, result.outputs, "output");
            if (!out_problems.empty()) {
                ActionValidationError mismatch(action_id, std::move(out_problems),
                                              "output schema mismatch");
                result.status = to_string(ActionStatus::Failed);
                result.error = mismatch.what();
                result.elapsed_ms = monotonic_ms() - t0;
                if (ctx.extras.is_object()) {
                    ctx.extras.erase("admission_lease");
                }
                return result;
            }
        }
        Json verification = verify(*spec, payload, params, ctx);
        if (spec->verifier) {
            Json custom;
            try {
                custom = spec->verifier(payload, params, &ctx);
            } catch (const std::exception& exc) {
                custom = Json::object();
                custom["verdict"] = kVerdictFail;
                custom["reasons"] = std::vector<std::string>{
                    std::string("verifier crashed: ") + exc.what()};
            }
            if (!custom.is_object() || !custom.contains("verdict")) {
                custom = Json::object();
                custom["verdict"] = kVerdictFail;
                custom["reasons"] =
                    std::vector<std::string>{"verifier returned no report"};
            }
            verification = merge_verification(verification, "verifier", custom);
        }
        result.verification = verification;
        // result.outputs already holds the wrapped payload from the
        // output-schema gate above (Python order: wrap -> validate).
        const std::string& verdict =
            verification.is_object() && verification.contains("verdict") &&
                    verification["verdict"].is_string()
                ? verification["verdict"].get<std::string>()
                : std::string();
        if (verdict == kVerdictFail) {
            result.status = to_string(ActionStatus::Failed);
            std::string joined;
            if (verification.contains("reasons") &&
                verification["reasons"].is_array()) {
                bool first = true;
                for (const auto& reason : verification["reasons"]) {
                    if (reason.is_null()) continue;
                    if (!first) joined += "; ";
                    joined += reason.get<std::string>();
                    first = false;
                }
            }
            result.error = "verification failed: " + joined;
        } else if (verdict == kVerdictWarning) {
            result.status = to_string(ActionStatus::Degraded);
            if (verification.contains("reasons") &&
                verification["reasons"].is_array()) {
                for (const auto& reason : verification["reasons"]) {
                    if (!reason.is_null()) {
                        result.warnings.push_back(reason.get<std::string>());
                    }
                }
            }
        }
    } catch (const providers::TaskCancelled& exc) {
        // Cooperative cancellation is a first-class terminal outcome —
        // "cancelled", never "failed".
        result.status = to_string(ActionStatus::Cancelled);
        result.error = std::string("cancelled: ") + exc.what();
    } catch (const providers::AdmissionRejected& exc) {
        // Governor refusal (capacity/pressure): never admitted — rejected.
        result.status = to_string(ActionStatus::Rejected);
        result.error = exc.what();
    } catch (const ActionValidationError& exc) {
        result.status = to_string(ActionStatus::Failed);
        result.error = exc.what();
    } catch (const providers::InvalidParametersError& exc) {
        result.status = to_string(ActionStatus::Failed);
        result.error = exc.what();
    } catch (const ActionUnavailableError& exc) {
        result.status = to_string(ActionStatus::Unavailable);
        result.error = std::string("unavailable: ") + exc.what();
    } catch (const providers::UnknownProviderError& exc) {
        // A missing production provider is honest unavailability.
        result.status = to_string(ActionStatus::Unavailable);
        result.error = std::string("unavailable: ") + exc.what();
    } catch (const std::exception& exc) {
        // Python prefixes the error with the exception class name
        // (f"{type(exc).__name__}: {exc}"); C++ exception type names are not
        // portably matchable, so the message carries the text only.
        result.status = to_string(ActionStatus::Failed);
        result.error = exc.what();
    } catch (...) {
        result.status = to_string(ActionStatus::Failed);
        result.error = "unknown error";
    }

    if (ctx.extras.is_object()) {
        const auto lease_slot = ctx.extras.find("admission_lease");
        if (lease_slot != ctx.extras.end()) {
            ctx.extras.erase("admission_lease");
        }
    }
    result.elapsed_ms = monotonic_ms() - t0;
    return result;
}

}  // namespace pwb::closure_agent
