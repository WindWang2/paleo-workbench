#include <pwb/closure_science/catalog_payload_source.hpp>

#include <pwb/domain/json.hpp>
#include <pwb/science_service/legacy_grid_codec.hpp>

#include <fstream>
#include <string>
#include <vector>

namespace pwb::closure_science {

using pwb::domain::Json;
using pwb::science::AlgorithmError;
using pwb::science_service::Payload;

namespace {

[[nodiscard]] AlgorithmError make_error(const std::string& message) {
    pwb::science::Diagnostic diagnostic;
    diagnostic.code = "payload.resolve";
    diagnostic.message = message;
    diagnostic.severity = "error";
    AlgorithmError error;
    error.diagnostics.push_back(std::move(diagnostic));
    return error;
}

[[nodiscard]] std::string json_text(const Json& value,
                                    const std::string& fallback = {}) {
    return value.is_string() ? value.get<std::string>() : fallback;
}

[[nodiscard]] std::string read_file(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream.good()) {
        throw make_error("cannot read payload file: " + path.string());
    }
    std::string content((std::istreambuf_iterator<char>(stream)),
                        std::istreambuf_iterator<char>());
    if (stream.bad()) {
        throw make_error("cannot read payload file: " + path.string());
    }
    return content;
}

}  // namespace

CatalogPayloadSource::CatalogPayloadSource(
    const catalog::CatalogDocument& document,
    std::filesystem::path project_dir)
    : document_(document), project_dir_(std::move(project_dir)) {}

pwb::science::Result<Payload> CatalogPayloadSource::resolve(
    const pwb::science::VersionRef& ref) {
    try {
        const catalog::DataVersion* version = nullptr;
        const catalog::DataAsset* asset = nullptr;
        for (const catalog::DataVersion& candidate : document_.versions) {
            if (candidate.id.str() == ref.version_id) {
                version = &candidate;
                break;
            }
        }
        if (version == nullptr && !ref.asset_id.empty()) {
            for (const catalog::DataAsset& candidate : document_.assets) {
                if (candidate.id.str() == ref.asset_id) {
                    asset = &candidate;
                    break;
                }
            }
            if (asset != nullptr && asset->current_version_id.has_value()) {
                for (const catalog::DataVersion& candidate :
                     document_.versions) {
                    if (candidate.id == *asset->current_version_id) {
                        version = &candidate;
                        break;
                    }
                }
            }
        }
        if (version == nullptr) {
            throw make_error("Unknown version: " + ref.version_id);
        }
        if (version->trashed) {
            throw make_error("输入版本已被删除: " + version->id.str());
        }
        if (!ref.asset_id.empty() && version->asset_id.str() != ref.asset_id) {
            throw make_error("version " + version->id.str() +
                             " does not belong to asset " + ref.asset_id);
        }

        std::filesystem::path payload_path(version->path);
        if (payload_path.empty()) {
            throw make_error("version " + version->id.str() +
                             " records no payload path");
        }
        if (payload_path.is_relative() && !project_dir_.empty()) {
            payload_path = project_dir_ / payload_path;
        }
        std::error_code ec;
        if (!std::filesystem::exists(payload_path, ec)) {
            throw make_error("payload file missing: " + payload_path.string());
        }

        const std::string payload_kind =
            version->metadata.is_object() &&
                    version->metadata.contains("payload_kind")
                ? json_text(version->metadata["payload_kind"])
                : std::string();
        const std::string content = read_file(payload_path);

        auto parse_json = [&](const char* what) -> Json {
            try {
                return Json::parse(content);
            } catch (const std::exception&) {
                throw make_error(std::string(what) + " is not valid JSON: " +
                                 payload_path.string());
            }
        };

        if (payload_kind == "well_log") {
            Json parsed = parse_json("well_log payload");
            if (!parsed.is_object() || !parsed.contains("depth") ||
                !parsed.contains("values") || !parsed["depth"].is_array() ||
                !parsed["values"].is_array()) {
                throw make_error(
                    "well_log payload must be a JSON object with depth[]/"
                    "values[] arrays");
            }
            Payload payload;
            payload.kind = Payload::Kind::well_log;
            for (const auto& value : parsed["depth"]) {
                payload.depth.push_back(value.get<double>());
            }
            for (const auto& value : parsed["values"]) {
                payload.values.push_back(value.get<double>());
            }
            if (payload.depth.size() != payload.values.size()) {
                throw make_error(
                    "well_log payload depth/values length mismatch");
            }
            const std::string unit = json_text(parsed["unit"]);
            if (!unit.empty()) payload.unit = unit;
            const std::string axis_unit = json_text(parsed["axis_unit"]);
            if (!axis_unit.empty()) payload.axis_unit = axis_unit;
            return payload;
        }

        if (payload_kind == "grid") {
            Json parsed = parse_json("grid payload");
            Payload payload;
            payload.kind = Payload::Kind::grid;
            try {
                payload.grid =
                    pwb::science_service::legacy_dict_to_mapping_grid(
                        parsed, json_text(parsed["factor"], "factor"));
            } catch (const std::exception& exc) {
                throw make_error(std::string("grid payload invalid: ") +
                                 exc.what());
            }
            return payload;
        }

        if (version->format == "json" || payload_kind == "table") {
            Json parsed = parse_json("table payload");
            Payload payload;
            payload.kind = Payload::Kind::table;
            if (parsed.is_array()) {
                payload.table = std::move(parsed);
            } else if (parsed.is_object() && parsed.contains("records") &&
                       parsed["records"].is_array()) {
                payload.table = parsed["records"];
            } else {
                throw make_error(
                    "table payload must be a JSON array of records");
            }
            return payload;
        }

        Payload payload;
        payload.kind = Payload::Kind::bytes;
        payload.bytes = std::move(content);
        payload.media_type = version->format;
        return payload;
    } catch (const AlgorithmError& error) {
        return error;
    } catch (const std::exception& exc) {
        return make_error(std::string("payload resolve failed: ") +
                          exc.what());
    }
}

}  // namespace pwb::closure_science
