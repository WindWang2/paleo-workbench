// CONV-36 — resources/export_service.py Qt-free port. See header.

#include "pwb/ui_data_core/export_service.hpp"

#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <system_error>

#include <pwb/domain/ids.hpp>
#include <pwb/domain/diagnostics.hpp>
#include <pwb/domain/text.hpp>
#include <pwb/ingest/classifier.hpp>
#include <pwb/interchange/atomic_file.hpp>
#include <pwb/interchange/exporters.hpp>
#include <pwb/project/paths.hpp>

namespace pwb::ui_data_core {

namespace {

const std::vector<ViewExportFormatSpec> kViewExportFormats = {
    {"PNG", ".png", "engine", "当前视图栅格截图（全 Tab）"},
    {"SVG", ".svg", "engine", "矢量图（测井 / 连井 / 古地理）"},
    {"PDF", ".pdf", "engine", "矢量 PDF（测井 / 连井 / 古地理）"},
};

// Python exception-class vocabulary for the generic catch branch
// (`导出失败: {exc.__class__.__name__}: {exc}`) — C++ exception types map
// onto the Python classes they stand in for.
std::string exception_class_name(const std::exception& e) {
    if (dynamic_cast<const std::ios_base::failure*>(&e) != nullptr ||
        dynamic_cast<const fs::filesystem_error*>(&e) != nullptr) {
        return "OSError";
    }
    if (dynamic_cast<const std::invalid_argument*>(&e) != nullptr) {
        return "ValueError";
    }
    if (dynamic_cast<const std::out_of_range*>(&e) != nullptr) {
        return "IndexError";
    }
    return "RuntimeError";
}

// artifact → project JSON row (pydantic field order).
domain::Json artifact_json(const ExportArtifact& a) {
    domain::Json j = domain::Json::object();
    j["id"] = a.id;
    j["linked_id"] = a.linked_id;
    j["format"] = a.format;
    j["output_path"] = a.output_path;
    j["options"] = a.options;
    j["included_map_elements"] = a.included_map_elements;
    j["generated_at"] = a.generated_at;
    j["source_task_ids"] = a.source_task_ids;
    j["catalog_version_id"] = a.catalog_version_id.has_value()
                                  ? domain::Json(*a.catalog_version_id)
                                  : domain::Json(nullptr);
    return j;
}

void append_artifact(project::ProjectDocument& project,
                     const ExportArtifact& artifact) {
    domain::Json& root = project.root();
    if (!root.contains("export_artifacts") ||
        !root["export_artifacts"].is_array()) {
        root["export_artifacts"] = domain::Json::array();
    }
    root["export_artifacts"].push_back(artifact_json(artifact));
}

// _register_catalog_output parity: lineage declaration order is
// source_resource_ids → linked_id → source_task_ids (deduped); a missing
// registrar or a thrown registration both land on catalog_version_id=None.
void run_catalog_seam(ExportArtifact& artifact,
                      const std::vector<std::string>& source_resource_ids,
                      std::string_view catalog_output_path,
                      const CatalogExportFn& register_catalog) {
    if (!register_catalog) {
        artifact.catalog_version_id = std::nullopt;
        return;
    }
    try {
        CatalogExportRequest req;
        req.name =
            fs::path(artifact.output_path).filename().string();
        req.output_path = catalog_output_path.empty()
                              ? artifact.output_path
                              : std::string(catalog_output_path);
        req.format = artifact.format;
        req.linked_id = artifact.linked_id;
        req.declared_ids = source_resource_ids;
        if (!artifact.linked_id.empty() &&
            std::find(req.declared_ids.begin(), req.declared_ids.end(),
                      artifact.linked_id) == req.declared_ids.end()) {
            req.declared_ids.push_back(artifact.linked_id);
        }
        for (const auto& tid : artifact.source_task_ids) {
            if (!tid.empty() &&
                std::find(req.declared_ids.begin(), req.declared_ids.end(),
                          tid) == req.declared_ids.end()) {
                req.declared_ids.push_back(tid);
            }
        }
        artifact.catalog_version_id = register_catalog(req);
    } catch (...) {
        // Provenance is best-effort (H14): the domain artifact remains the
        // record that the export happened.
        artifact.catalog_version_id = std::nullopt;
    }
}

// resolve_project_path swallow (export_asset_to_path's try/except-pass).
fs::path resolve_stored(const std::string& stored, const fs::path* project_path) {
    fs::path input = fs::path(stored);
    if (project_path != nullptr) {
        if (auto resolved = project::resolve_project_path(stored, *project_path);
            resolved.is_ok()) {
            input = fs::path(resolved.value());
        }
    }
    if (std::error_code ec; !fs::is_regular_file(input, ec) || ec) {
        // Last resort: expanduser + resolve against CWD for absolute-ish
        // relative paths (Python parity).
        fs::path resolved = input;
        const std::string s = input.generic_string();
        if (!s.empty() && s.front() == '~') {
            if (const char* home = std::getenv("HOME"); home != nullptr) {
                resolved = fs::path(std::string(home) + s.substr(1));
            }
        }
        if (!resolved.is_absolute()) {
            std::error_code ec2;
            const fs::path abs = fs::absolute(resolved, ec2);
            if (!ec2) resolved = abs.lexically_normal();
        }
        input = resolved;
    }
    return input;
}

}  // namespace

const std::vector<ViewExportFormatSpec>& view_export_formats() {
    return kViewExportFormats;
}

int view_format_rank(std::string_view label) {
    std::string upper(label);
    for (char& c : upper)
        c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    if (upper == "PNG") return 0;
    if (upper == "SVG") return 1;
    if (upper == "PDF") return 2;
    return 99;
}

std::vector<std::string> list_asset_export_labels(std::string_view format) {
    std::vector<std::string> labels;
    for (const auto& [label, fn] : interchange::get_available_formats(format)) {
        labels.push_back(label);
    }
    return labels;
}

ExportArtifact record_export(project::ProjectDocument& project,
                             std::string linked_id, std::string output_path,
                             std::string fmt,
                             std::vector<std::string> source_task_ids,
                             std::vector<std::string> source_resource_ids,
                             const CatalogExportFn& register_catalog,
                             std::string_view catalog_output_path) {
    ExportArtifact artifact;
    artifact.id = domain::make_id("artifact_");
    artifact.linked_id = std::move(linked_id);
    artifact.format = std::move(fmt);
    artifact.output_path = std::move(output_path);
    artifact.generated_at = domain::now_iso8601();
    artifact.source_task_ids = std::move(source_task_ids);
    artifact.catalog_version_id = std::nullopt;

    append_artifact(project, artifact);
    run_catalog_seam(artifact, source_resource_ids, catalog_output_path,
                     register_catalog);
    if (artifact.catalog_version_id.has_value()) {
        // Keep the persisted row in sync with the registered version id.
        domain::Json& arts = project.root()["export_artifacts"];
        if (arts.is_array() && !arts.empty()) {
            arts.back()["catalog_version_id"] = *artifact.catalog_version_id;
        }
    }
    return artifact;
}

ExportJobResult export_asset_to_path(
    const ResourceItem& asset, std::string_view format_label,
    const fs::path& output_path, project::ProjectDocument* project,
    const fs::path* project_path, bool do_register,
    std::vector<std::string> source_task_ids,
    const CatalogExportFn& register_catalog) {
    ExportJobResult result;
    const auto formats = interchange::get_available_formats(asset.format);
    interchange::ConvertFn convert;
    for (const auto& [label, fn] : formats) {
        if (label == format_label) {
            convert = fn;
            break;
        }
    }
    if (!convert) {
        result.message = "资源不支持导出为 " + std::string(format_label);
        return result;
    }

    const fs::path input = resolve_stored(asset.path, project_path);
    std::error_code ec;
    if (!fs::is_regular_file(input, ec) || ec) {
        result.message = "源文件不存在: " + input.generic_string();
        return result;
    }

    try {
        convert(input, output_path);
    } catch (const interchange::ExportError& e) {
        result.message = e.what();
        return result;
    } catch (const std::exception& e) {
        result.message = "导出失败: " + exception_class_name(e) + ": " + e.what();
        return result;
    }

    if (do_register && project != nullptr) {
        std::string stored = output_path.generic_string();
        if (project_path != nullptr) {
            stored = project::relativize_path(output_path, *project_path).stored;
        }
        auto artifact = record_export(
            *project, asset.id, stored, domain::lower_ascii(format_label),
            std::move(source_task_ids), {asset.id}, register_catalog,
            output_path.generic_string());
        // UI provenance free-form stash (source:<name>).
        artifact.included_map_elements = {"source:" + asset.name};
        domain::Json& arts = project->root()["export_artifacts"];
        arts.back()["included_map_elements"] =
            domain::Json::array({"source:" + asset.name});
        result.artifact = std::move(artifact);
    }

    result.success = true;
    result.output_path = output_path.generic_string();
    result.format = std::string(format_label);
    result.message = "已导出: " + output_path.filename().generic_string();
    return result;
}

ExportJobResult export_project_inventory(
    project::ProjectDocument& project, const fs::path& output_path,
    const fs::path* project_path, bool do_register,
    const CatalogExportFn& register_catalog) {
    ExportJobResult result;

    domain::Json resources = domain::Json::array();
    const auto& labels = ingest::type_labels();
    const domain::Json* res = project.find_section("resources");
    if (res != nullptr && res->is_array()) {
        for (const auto& r : *res) {
            if (!r.is_object()) continue;
            domain::Json row = domain::Json::object();
            const auto get_str = [&](const char* key) {
                const auto it = r.find(key);
                return it != r.end() && it->is_string()
                           ? it->get<std::string>()
                           : std::string{};
            };
            const std::string type = get_str("type");
            row["id"] = get_str("id");
            row["name"] = get_str("name");
            row["type"] = type;
            const auto label_it = labels.find(type);
            row["type_label"] =
                label_it != labels.end() ? label_it->second : type;
            row["format"] = get_str("format");
            row["path"] = get_str("path");
            row["status"] = get_str("status");
            const auto ext_it = r.find("external");
            row["external"] =
                ext_it != r.end() && ext_it->is_boolean()
                    ? domain::Json(ext_it->get<bool>())
                    : domain::Json(false);
            const auto role_it = r.find("artifact_role");
            row["artifact_role"] =
                role_it != r.end() && role_it->is_string()
                    ? domain::Json(role_it->get<std::string>())
                    : domain::Json(nullptr);
            const auto tags_it = r.find("tags");
            row["tags"] = tags_it != r.end() && tags_it->is_array()
                              ? *tags_it
                              : domain::Json::array();
            const auto ps_it = r.find("parsed_summary");
            row["parsed_summary"] =
                ps_it != r.end() && ps_it->is_object() ? *ps_it
                                                       : domain::Json::object();
            resources.push_back(std::move(row));
        }
    }

    domain::Json artifacts = domain::Json::array();
    const domain::Json* arts = project.find_section("export_artifacts");
    if (arts != nullptr && arts->is_array()) {
        for (const auto& a : *arts) {
            if (!a.is_object()) continue;
            domain::Json row = domain::Json::object();
            for (const char* key : {"id", "linked_id", "format", "output_path"}) {
                const auto it = a.find(key);
                row[key] = it != a.end() && it->is_string()
                               ? domain::Json(it->get<std::string>())
                               : domain::Json("");
            }
            artifacts.push_back(std::move(row));
        }
    }

    domain::Json payload = domain::Json::object();
    const auto meta = project.meta();
    payload["project"] = meta.has_value() ? meta->name : "";
    payload["region"] = meta.has_value() ? meta->region : "";
    payload["resource_count"] = static_cast<std::int64_t>(resources.size());
    payload["artifact_count"] = static_cast<std::int64_t>(artifacts.size());
    payload["resources"] = std::move(resources);
    payload["export_artifacts"] = std::move(artifacts);

    try {
        std::error_code ec;
        fs::create_directories(output_path.parent_path(), ec);
        interchange::AtomicOutputFile out(output_path);
        {
            std::ofstream sink(out.temp_path(),
                               std::ios::binary | std::ios::trunc);
            if (!sink) {
                throw fs::filesystem_error(
                    "open", out.temp_path(),
                    std::make_error_code(std::errc::io_error));
            }
            sink << payload.dump(2);
        }
        out.commit();
    } catch (const std::exception& e) {
        result.message = "写入清单失败: " + std::string(e.what());
        return result;
    }

    if (do_register) {
        std::string stored = output_path.generic_string();
        if (project_path != nullptr) {
            stored = project::relativize_path(output_path, *project_path).stored;
        }
        auto artifact = record_export(
            project, meta.has_value() ? meta->name : "", stored,
            "inventory.json", {}, {}, register_catalog);
        artifact.included_map_elements = {"inventory"};
        domain::Json& rows = project.root()["export_artifacts"];
        rows.back()["included_map_elements"] =
            domain::Json::array({"inventory"});
        result.artifact = std::move(artifact);
    }

    result.success = true;
    result.output_path = output_path.generic_string();
    result.format = "INVENTORY";
    result.message =
        "已导出工程清单: " + output_path.filename().generic_string();
    return result;
}

std::optional<ExportArtifact> register_exported_view(
    std::string_view surface_kind, const fs::path& output_path,
    std::string_view format_label, project::ProjectDocument* project,
    const fs::path* project_path, std::string_view linked_id,
    bool do_register, std::vector<std::string> source_task_ids,
    const CatalogExportFn& register_catalog) {
    if (!do_register || project == nullptr) return std::nullopt;
    std::string stored = output_path.generic_string();
    if (project_path != nullptr) {
        project::ensure_artifact_layout(*project_path);
        stored = project::relativize_path(output_path, *project_path).stored;
    }
    auto artifact = record_export(
        *project, std::string(linked_id), stored,
        domain::lower_ascii(format_label), std::move(source_task_ids), {},
        register_catalog, output_path.generic_string());
    artifact.included_map_elements = {"visualization_view",
                                      std::string(surface_kind)};
    domain::Json& arts = project->root()["export_artifacts"];
    arts.back()["included_map_elements"] = domain::Json::array(
        {"visualization_view", std::string(surface_kind)});
    return artifact;
}

fs::path default_export_dir(const fs::path* project_path) {
    if (project_path == nullptr) {
        const char* home = std::getenv("HOME");
        return fs::path(home != nullptr ? home : ".") / "paleo_exports";
    }
    const fs::path exports =
        project::ensure_artifact_layout(*project_path) / "exports";
    std::error_code ec;
    fs::create_directories(exports, ec);
    return exports;
}

}  // namespace pwb::ui_data_core
