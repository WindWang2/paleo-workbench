#include "pwb/prediction/model_package.hpp"

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <vector>

#include "pwb/domain/sha256.hpp"
#include "pwb/ingest/py_compat.hpp"
#include "python_compat.hpp"

namespace pwb::prediction {

namespace {

using detail::py_or;
using detail::py_repr;
using detail::py_str;
using detail::py_strip;
using detail::py_truthy;

const Json kNull;

const Json& get(const Json& obj, const char* key) {
    if (!obj.is_object()) return kNull;
    const auto it = obj.find(key);
    return it == obj.end() ? kNull : *it;
}

std::string ascii_lower(std::string s) {
    for (char& c : s) {
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + 32);
    }
    return s;
}

// _strict_bool(raw, key, default): bool passthrough or "true"/"false"
// (strip + lower); anything else -> ModelPackageError with repr().
bool strict_bool(const Json& raw, const char* key, bool dflt) {
    const Json& v = raw.contains(key) ? raw[key] : Json(dflt);
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_string()) {
        const std::string s =
            ascii_lower(py_strip(v.get_ref<const std::string&>()));
        if (s == "true") return true;
        if (s == "false") return false;
    }
    throw ModelPackageError(std::string(key) + " must be a boolean, got " +
                            py_repr(v));
}

// Python 'utf-8' strict decode error report: position + reason class.
// Only the structural classes Python emits for well-formed-enough streams
// are reproduced (invalid start byte / invalid continuation byte /
// unexpected end of data) — the oracle freezes the concrete case.
struct Utf8Error {
    size_t pos;
    size_t end;       // exclusive; > pos+1 means Python's "N-M" range form
    unsigned byte;    // offending byte at pos (invalid start/continuation)
    const char* reason;
};

std::optional<Utf8Error> utf8_error_at(std::string_view bytes) {
    for (size_t i = 0; i < bytes.size();) {
        const auto c = static_cast<unsigned char>(bytes[i]);
        if (c < 0x80) { ++i; continue; }
        size_t len = 0;
        if (c >= 0xC2 && c <= 0xDF) len = 2;
        else if (c >= 0xE0 && c <= 0xEF) len = 3;
        else if (c >= 0xF0 && c <= 0xF4) len = 4;
        else return Utf8Error{i, i + 1, c, "invalid start byte"};
        if (i + len > bytes.size()) {
            return Utf8Error{i, bytes.size(), c, "unexpected end of data"};
        }
        for (size_t k = 1; k < len; ++k) {
            if ((static_cast<unsigned char>(bytes[i + k]) & 0xC0) != 0x80) {
                return Utf8Error{i + k, i + k + 1,
                                 static_cast<unsigned char>(bytes[i + k]),
                                 "invalid continuation byte"};
            }
        }
        i += len;
    }
    return std::nullopt;
}

std::string unicode_decode_message(const Utf8Error& e) {
    char buf[160];
    if (e.end > e.pos + 1) {
        std::snprintf(buf, sizeof buf,
                      "'utf-8' codec can't decode bytes in position %zu-%zu: %s",
                      e.pos, e.end - 1, e.reason);
    } else {
        std::snprintf(buf, sizeof buf,
                      "'utf-8' codec can't decode byte 0x%02x in position %zu: %s",
                      e.byte, e.pos, e.reason);
    }
    return std::string(buf);
}

}  // namespace

Json ModelPackageManifest::to_dict() const {
    return Json{
        {"model_id", model_id},
        {"model_version", model_version},
        {"model_name", model_name},
        {"capability", capability},
        {"provider", provider},
        {"artifact", artifact},
        {"checksum", checksum ? Json(*checksum) : Json()},
        {"input_schema", input_schema},
        {"output_schema", output_schema},
        {"preprocessing_version", preprocessing_version},
        {"runtime", runtime},
        {"deterministic", deterministic},
        {"spatial_output_type", spatial_output_type},
        {"model_type", model_type},
        {"demo_only", demo_only},
        {"scientific", scientific},
        {"provenance", provenance},
        {"metadata", metadata},
    };
}

ModelPackageManifest ModelPackageManifest::from_dict(const Json& d) {
    ModelPackageManifest m;
    auto str_or = [&](const char* k, std::string& dst) {
        if (d.contains(k) && d[k].is_string()) dst = d[k].get<std::string>();
    };
    auto bool_or = [&](const char* k, bool& dst) {
        if (d.contains(k) && d[k].is_boolean()) dst = d[k].get<bool>();
    };
    auto obj_or = [&](const char* k, Json& dst) {
        if (d.contains(k) && d[k].is_object()) dst = d[k];
    };
    str_or("model_id", m.model_id);
    str_or("model_version", m.model_version);
    str_or("model_name", m.model_name);
    str_or("capability", m.capability);
    str_or("provider", m.provider);
    str_or("artifact", m.artifact);
    if (d.contains("checksum") && d["checksum"].is_string()) {
        m.checksum = d["checksum"].get<std::string>();
    }
    obj_or("input_schema", m.input_schema);
    obj_or("output_schema", m.output_schema);
    str_or("preprocessing_version", m.preprocessing_version);
    str_or("runtime", m.runtime);
    bool_or("deterministic", m.deterministic);
    str_or("spatial_output_type", m.spatial_output_type);
    str_or("model_type", m.model_type);
    bool_or("demo_only", m.demo_only);
    bool_or("scientific", m.scientific);
    obj_or("provenance", m.provenance);
    obj_or("metadata", m.metadata);
    return m;
}

Json load_manifest_dict(const Json& source) {
    if (source.is_object()) return source;
    if (!source.is_string()) {
        throw ModelPackageError(
            "expected str, bytes or os.PathLike object, not '" +
            detail::py_type_name(source) + "'");
    }
    const std::string path_str = source.get_ref<const std::string&>();
    const std::filesystem::path path(path_str);
    if (!std::filesystem::is_regular_file(path)) {
        throw ModelPackageError("Manifest not found: " + path_str);
    }
    std::ifstream in(path, std::ios::binary);
    std::ostringstream buf;
    buf << in.rdbuf();
    const std::string bytes = buf.str();
    // Path.read_text(encoding="utf-8") — strict; the decode failure escapes
    // unwrapped as UnicodeDecodeError (not ModelPackageError).
    if (const auto err = utf8_error_at(bytes)) {
        throw UnicodeDecodeError(unicode_decode_message(*err));
    }
    Json data;
    try {
        data = Json::parse(bytes);
    } catch (const std::exception& exc) {
        // Detail text differs from CPython's json error wording — the
        // "Invalid manifest JSON: " prefix is the frozen contract (D9).
        throw ModelPackageError(std::string("Invalid manifest JSON: ") +
                                exc.what());
    }
    if (!data.is_object()) {
        throw ModelPackageError("Manifest root must be a JSON object");
    }
    return data;
}

ModelPackageManifest parse_model_package_manifest(const Json& source,
                                                  const Json& base_dir) {
    const Json raw = load_manifest_dict(source);
    const std::string model_id =
        py_strip(py_str(py_or(get(raw, "model_id"), Json(""))));
    const std::string model_version = py_strip(py_str(
        py_or(get(raw, "model_version"), py_or(get(raw, "version"), Json("1")))));
    const std::string model_name = py_strip(py_str(py_or(
        py_or(get(raw, "model_name"), get(raw, "name")), Json(model_id))));
    const std::string capability =
        py_strip(py_str(py_or(get(raw, "capability"), Json(""))));
    const std::string provider =
        py_strip(py_str(py_or(get(raw, "provider"), Json(""))));
    if (model_id.empty()) throw ModelPackageError("model_id is required");
    if (model_name.empty()) throw ModelPackageError("model_name is required");
    if (capability.empty()) throw ModelPackageError("capability is required");
    if (provider.empty()) throw ModelPackageError("provider is required");

    std::string model_type =
        py_strip(py_str(py_or(get(raw, "model_type"), Json("ml"))));
    if (model_type.empty()) model_type = "ml";
    const bool demo_only = strict_bool(raw, "demo_only", false);
    const bool scientific = strict_bool(raw, "scientific", !demo_only);
    const bool deterministic = strict_bool(raw, "deterministic", true);
    const std::string spatial = py_strip(
        py_str(py_or(get(raw, "spatial_output_type"),
                     Json(std::string(kSpatialVectorPolygons)))));
    if (!kKnownSpatialTypes.count(spatial)) {
        throw ModelPackageError("Unknown spatial_output_type: " +
                                py_repr(Json(spatial)));
    }

    std::string artifact = py_strip(py_str(
        py_or(get(raw, "artifact"), py_or(get(raw, "artifact_uri"), Json("")))));
    if (!artifact.empty() && !base_dir.is_null()) {
        const std::filesystem::path art_path(artifact);
        if (!art_path.is_absolute()) {
            const std::filesystem::path base(
                base_dir.is_string() ? base_dir.get_ref<const std::string&>()
                                     : py_str(base_dir));
            // Path.resolve(strict=False) ~= weakly_canonical (D9).
            artifact = std::filesystem::weakly_canonical(base / art_path)
                           .generic_string();
        }
    }

    std::optional<std::string> checksum;
    const Json& checksum_v = get(raw, "checksum");
    if (!checksum_v.is_null()) {
        const std::string s = py_strip(py_str(checksum_v));
        if (!s.empty()) checksum = s;
    }

    const Json input_schema =
        py_or(get(raw, "input_schema"), Json::object());
    const Json output_schema_raw =
        py_or(get(raw, "output_schema"), Json::object());
    if (!input_schema.is_object() || !output_schema_raw.is_object()) {
        throw ModelPackageError(
            "input_schema and output_schema must be objects");
    }
    const Json metadata =
        py_or(get(raw, "metadata"), Json::object());
    const Json provenance =
        py_or(get(raw, "provenance"), Json::object());
    if (!metadata.is_object() || !provenance.is_object()) {
        throw ModelPackageError("metadata and provenance must be objects");
    }

    Json output_schema = output_schema_raw;
    if (!spatial.empty() && !output_schema.contains("spatial_output_type")) {
        output_schema["spatial_output_type"] = spatial;
    }

    ModelPackageManifest m;
    m.model_id = model_id;
    m.model_version = model_version;
    m.model_name = model_name;
    m.capability = capability;
    m.provider = provider;
    m.artifact = artifact;
    m.checksum = checksum;
    m.input_schema = input_schema;
    m.output_schema = output_schema;
    m.preprocessing_version =
        py_str(py_or(get(raw, "preprocessing_version"), Json("")));
    m.runtime = py_str(py_or(get(raw, "runtime"), Json("python_callable")));
    m.deterministic = deterministic;
    m.spatial_output_type = spatial.empty() ? std::string(kSpatialNone) : spatial;
    m.model_type = model_type;
    m.demo_only = demo_only;
    m.scientific = scientific;
    m.provenance = provenance;
    m.metadata = metadata;
    return m;
}

Json validate_model_package(ModelPackageManifest& manifest,
                            bool require_artifact,
                            bool allow_non_scientific) {
    Json errors = Json::array();
    if (!allow_non_scientific &&
        kNonPromotableProviders.count(manifest.provider)) {
        errors.push_back("provider " + py_repr(Json(manifest.provider)) +
                         " cannot be registered as a production package");
    }
    if (!allow_non_scientific &&
        kNonPromotableModelTypes.count(manifest.model_type)) {
        errors.push_back("model_type " + py_repr(Json(manifest.model_type)) +
                         " cannot be a production package");
    }
    if (!allow_non_scientific && manifest.demo_only) {
        errors.push_back(
            "demo_only packages cannot be registered as production");
    }
    if (!allow_non_scientific && !manifest.scientific) {
        errors.push_back(
            "scientific=false packages cannot be registered as production");
    }
    if (require_artifact) {
        if (manifest.artifact.empty()) {
            errors.push_back(
                "artifact path is required for production packages");
        } else {
            const std::filesystem::path path(manifest.artifact);
            if (!std::filesystem::is_regular_file(path)) {
                errors.push_back("artifact file missing: " + manifest.artifact);
            } else {
                const auto digest = pwb::domain::Sha256::of_file(path);
                if (!digest) {
                    throw std::runtime_error("artifact vanished: " +
                                             manifest.artifact);
                }
                if (manifest.checksum && *manifest.checksum != *digest) {
                    errors.push_back("checksum mismatch: manifest=" +
                                     *manifest.checksum + " file=" + *digest);
                } else if (!manifest.checksum) {
                    manifest.checksum = *digest;
                }
            }
        }
    }
    if (!allow_non_scientific && !py_truthy(manifest.input_schema)) {
        errors.push_back("input_schema is required for production packages");
    }
    return errors;
}

}  // namespace pwb::prediction
