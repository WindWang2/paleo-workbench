#include "pwb/closure_review/report_export.hpp"

#include "pwb/closure_review/review_qc_core.hpp"

#include <pwb/domain/sha256.hpp>
#include <pwb/ui_data_core/map_edit_geometry.hpp>

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <cmath>
#include <sstream>

namespace pwb::closure_review {

namespace {

using domain::Json;

std::string field_string(const Json& object, const char* key) {
    if (!object.is_object()) {
        return {};
    }
    const auto it = object.find(key);
    return it != object.end() && it->is_string() ? it->get<std::string>()
                                                 : std::string();
}

// _json_safe parity: non-finite floats become null so strict JSON parsers
// accept the file (json.dumps(allow_nan=False) would reject them).
Json json_safe(const Json& value) {
    if (value.is_number_float()) {
        const double number = value.get<double>();
        if (!std::isfinite(number)) {
            return Json();
        }
        return value;
    }
    if (value.is_object()) {
        Json out = Json::object();
        for (auto it = value.begin(); it != value.end(); ++it) {
            out[it.key()] = json_safe(it.value());
        }
        return out;
    }
    if (value.is_array()) {
        Json out = Json::array();
        for (const auto& item : value) {
            out.push_back(json_safe(item));
        }
        return out;
    }
    return value;
}

// atomic_output parity: write the payload to a sibling temp file, flush it
// to disk, and rename over the destination. Returns false (+ stderr-worthy
// detail) instead of throwing on any short write / full disk.
bool atomic_write_file(const std::filesystem::path& path,
                       const std::string& payload, std::string* error) {
    namespace fs = std::filesystem;
    std::error_code ec;
    const fs::path parent = path.parent_path();
    if (!parent.empty()) {
        fs::create_directories(parent, ec);
        if (ec) {
            if (error != nullptr) {
                *error = "create_directories failed: " + ec.message();
            }
            return false;
        }
        ec.clear();
    }
    const fs::path temp = parent.empty()
                              ? fs::path("." + path.filename().string() +
                                         ".tmp-" +
                                         domain::Sha256::of_bytes(
                                             payload)
                                             .substr(0, 12))
                              : parent / ("." + path.filename().string() +
                                          ".tmp-" +
                                          domain::Sha256::of_bytes(payload)
                                              .substr(0, 12));
    {
        std::ofstream out(temp, std::ios::binary | std::ios::trunc);
        if (!out.good()) {
            if (error != nullptr) {
                *error = "temp file open failed: " + temp.string();
            }
            return false;
        }
        out.write(payload.data(),
                  static_cast<std::streamsize>(payload.size()));
        out.flush();
        if (!out.good()) {
            // Short write / disk full: the failure IS the receipt.
            if (error != nullptr) {
                *error = "short write or disk full on " + temp.string();
            }
            out.close();
            fs::remove(temp, ec);
            return false;
        }
        out.close();
        if (out.fail()) {
            if (error != nullptr) {
                *error = "temp file close failed: " + temp.string();
            }
            fs::remove(temp, ec);
            return false;
        }
    }
    // Verify the delivered file parses before publishing it (the Python
    // wrapper re-reads + json.loads before the rename).
    {
        std::ifstream in(temp, std::ios::binary);
        std::ostringstream buffer;
        buffer << in.rdbuf();
        const std::string text = buffer.str();
        if (text != payload) {
            if (error != nullptr) {
                *error = "temp file content mismatch (short write?): " +
                         temp.string();
            }
            std::error_code rm;
            fs::remove(temp, rm);
            return false;
        }
        if (domain::Json::parse(text, nullptr, false).is_discarded()) {
            if (error != nullptr) {
                *error = "payload does not parse as JSON";
            }
            std::error_code rm;
            fs::remove(temp, rm);
            return false;
        }
    }
    fs::rename(temp, path, ec);
    if (ec) {
        if (error != nullptr) {
            *error = "rename failed: " + ec.message();
        }
        std::error_code rm;
        fs::remove(temp, rm);
        return false;
    }
    return true;
}

}  // namespace

std::filesystem::path default_export_dir(
    const std::filesystem::path* project_file) {
    namespace fs = std::filesystem;
    if (project_file == nullptr || project_file->empty()) {
        fs::path home;
        if (const char* env = std::getenv("HOME"); env != nullptr) {
            home = fs::path(env);
        } else if (const char* userprofile =
                       std::getenv("USERPROFILE");
                   userprofile != nullptr) {
            home = fs::path(userprofile);
        }
        const fs::path dir = home.empty()
                                 ? fs::path("paleo_exports")
                                 : home / "paleo_exports";
        std::error_code ec;
        fs::create_directories(dir, ec);
        return dir;
    }
    // artifact_dir_for + ensure_artifact_layout parity: the artifact ROOT
    // is the sibling "<project>.artifacts" directory (".paleo.json" suffix
    // stripped); the standard seven subdirs are materialized and exports
    // live at <root>/exports.
    const std::string name = project_file->filename().string();
    const std::string suffix = ".paleo.json";
    std::string stem = name;
    if (name.size() > suffix.size() &&
        name.compare(name.size() - suffix.size(), suffix.size(), suffix) ==
            0) {
        stem = name.substr(0, name.size() - suffix.size());
    }
    const fs::path root = project_file->parent_path() / (stem + ".artifacts");
    std::error_code ec;
    for (const char* subdir : {"cache", "factor_maps", "predictions",
                               "paleomaps", "qc", "exports", "thumbnails"}) {
        fs::create_directories(root / subdir, ec);
    }
    return root / "exports";
}

domain::DataError export_quality_report_json(
    Json& root, const Json& report, const std::filesystem::path& output_path,
    const std::string& iso_now) {
    (void)iso_now;  // generated_at lives on the report itself
    const Json payload = json_safe(report);
    const std::string text =
        domain::dump_json_python_compatible(payload);

    std::string write_error;
    if (!atomic_write_file(output_path, text, &write_error)) {
        return domain::DataError(domain::ErrorCode::IoError,
                                 "质检报告导出失败: " + write_error);
    }

    // record_export parity: append the ExportArtifact (no catalog OUTPUT
    // version yet — the catalog registration is the catalog line's surface;
    // the artifact record itself is the domain truth the data page shows).
    const std::string report_id = field_string(report, "id");
    const std::string linked_map =
        field_string(report, "linked_map_document_id");
    Json artifact = Json::object();
    artifact["id"] = ui_data_core::new_feature_id("artifact");
    artifact["linked_id"] = !linked_map.empty() ? linked_map : report_id;
    artifact["format"] = "qc_json";
    artifact["output_path"] = output_path.string();
    artifact["options"] = Json::object();
    artifact["included_map_elements"] = Json::array();
    artifact["generated_at"] = iso_now;
    Json source_task_ids = Json::array();
    if (!report_id.empty()) {
        source_task_ids.push_back(report_id);
    }
    artifact["source_task_ids"] = source_task_ids;
    artifact["catalog_version_id"] = Json();

    auto artifacts_it = root.find("export_artifacts");
    if (artifacts_it == root.end() || !artifacts_it->is_array()) {
        root["export_artifacts"] = Json::array();
        artifacts_it = root.find("export_artifacts");
    }
    artifacts_it->push_back(artifact);
    // Domain convention: a default DataError carries Unknown — success
    // must be constructed explicitly (see errors.hpp).
    return domain::DataError(domain::ErrorCode::Ok, "");
}

}  // namespace pwb::closure_review
