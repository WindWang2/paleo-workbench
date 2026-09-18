// pwb::science_service — ScienceEnvelope codec (CONV-28).

#include <pwb/science_service/envelope.hpp>

#include <pwb/domain/json.hpp>
#include <pwb/factor_host/canonical_json.hpp>
#include <pwb/factor_host/fingerprint.hpp>

#include <stdexcept>
#include <utility>

namespace pwb::science_service {

using pwb::domain::Json;

namespace {

// Strict-JSON-safe number: non-finite doubles encode as null (the envelope
// payload contract mirrors factor_grid_io's allow_nan=False discipline).
Json safe_number(double v) {
    return std::isfinite(v) ? Json(v) : Json(nullptr);
}

Json extent_to_json(const std::optional<std::array<double, 4>>& extent) {
    if (!extent) {
        return Json(nullptr);
    }
    Json arr = Json::array();
    for (double v : *extent) {
        arr.push_back(safe_number(v));
    }
    return arr;
}

std::optional<std::array<double, 4>> extent_from_json(const Json& data) {
    if (data.is_null() || !data.is_array() || data.size() != 4) {
        return std::nullopt;
    }
    std::array<double, 4> out{};
    for (std::size_t i = 0; i < 4; ++i) {
        if (!data.at(i).is_number()) {
            return std::nullopt;
        }
        out[i] = data.at(i).get<double>();
    }
    return out;
}

}  // namespace

std::string ScienceEnvelope::compute_fingerprint() const {
    fingerprint = pwb::factor_host::stable_sha256(payload);
    return fingerprint;
}

Json ScienceEnvelope::to_json() const {
    Json out = Json::object();
    out["schema_version"] = schema_version;
    out["result_type"] = result_type;
    out["units"] = units.empty() ? Json(nullptr) : Json(units);
    out["crs"] = crs.empty() ? Json(nullptr) : Json(crs);
    out["extent"] = extent_to_json(extent);
    out["quality"] = quality;
    out["provenance"] = provenance;
    out["fingerprint"] = fingerprint;
    out["payload"] = payload;
    out["diagnostics"] = diagnostics;
    return out;
}

ScienceEnvelope ScienceEnvelope::from_json(const Json& data) {
    if (!data.is_object()) {
        throw std::invalid_argument("envelope must be a JSON object");
    }
    ScienceEnvelope env;
    if (!data.contains("schema_version") || !data.contains("result_type")
        || !data.contains("fingerprint") || !data.contains("payload")) {
        throw std::invalid_argument(
            "envelope object missing required keys (schema_version / "
            "result_type / fingerprint / payload)");
    }
    env.schema_version = data.at("schema_version").get<int>();
    env.result_type = data.at("result_type").get<std::string>();
    env.units = data.value("units", std::string());
    if (data.at("units").is_null()) {
        env.units = "";
    }
    env.crs = data.value("crs", std::string());
    if (data.at("crs").is_null()) {
        env.crs = "";
    }
    env.extent = extent_from_json(data.contains("extent")
                                      ? data.at("extent")
                                      : Json(nullptr));
    env.quality = data.contains("quality") ? data.at("quality") : Json::object();
    env.provenance =
        data.contains("provenance") ? data.at("provenance") : Json::object();
    env.fingerprint = data.at("fingerprint").get<std::string>();
    env.payload = data.at("payload");
    env.diagnostics =
        data.contains("diagnostics") ? data.at("diagnostics") : Json::array();
    return env;
}

std::string dump_envelope(const ScienceEnvelope& envelope) {
    return pwb::domain::dump_json_python_compatible(envelope.to_json());
}

}  // namespace pwb::science_service
