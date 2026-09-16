#include "pwb/project/document.hpp"

#include "pwb/project/schema.hpp"

namespace pwb::project {

using pwb::domain::Diagnostic;
using pwb::domain::Json;
using pwb::domain::Result;

ProjectDocument ProjectDocument::create_new(const std::string& name,
                                            const std::string& region) {
    Json seed = Json::object();
    Json meta = Json::object();
    meta["name"] = name;
    meta["region"] = region;
    seed["meta"] = std::move(meta);
    ProjectDocument doc;
    doc.diagnostics_.clear();
    normalize(seed, project_document_spec(), doc.diagnostics_);
    doc.root_ = std::move(seed);
    return doc;
}

Result<ProjectDocument> ProjectDocument::parse(
    const std::string& text, domain::DiagnosticList& diagnostics) {
    Json parsed;
    try {
        parsed = Json::parse(text);
    } catch (const Json::exception& error) {
        diagnostics.push_back(
            Diagnostic::error("corrupt_json", std::string(error.what())));
        return domain::DataError(domain::ErrorCode::CorruptJson,
                                 std::string(error.what()));
    }
    if (!parsed.is_object()) {
        diagnostics.push_back(
            Diagnostic::error("corrupt_json", "project root is not an object"));
        return domain::DataError(domain::ErrorCode::CorruptJson,
                                 "project root is not an object");
    }
    // Unknown top-level sections are preserved but reported (#1170 parity).
    for (auto it = parsed.begin(); it != parsed.end(); ++it) {
        bool declared = false;
        for (const FieldSpec& field : *project_document_spec().fields) {
            if (field.name == it.key()) {
                declared = true;
                break;
            }
        }
        if (!declared) {
            diagnostics.push_back(Diagnostic::warning(
                "unknown_section",
                "project file has unknown section '" + it.key() +
                    "' (newer schema?) — preserved verbatim, not interpreted",
                Json{{"section", it.key()}}));
        }
    }
    ProjectDocument doc;
    if (!normalize(parsed, project_document_spec(), diagnostics)) {
        return domain::DataError(domain::ErrorCode::CorruptJson,
                                 "project schema validation failed",
                                 Json{{"diagnostics", diagnostics.size()}});
    }
    doc.root_ = std::move(parsed);
    if (doc.schema_version() > kKnownProjectSchemaVersion) {
        doc.set_read_only(true);
        diagnostics.push_back(Diagnostic::warning(
            "future_schema",
            "schema_version " + std::to_string(doc.schema_version()) +
                " is newer than supported (" +
                std::to_string(kKnownProjectSchemaVersion) +
                ") — opened read-only",
            Json{{"schema_version", doc.schema_version()}}));
    }
    return doc;
}

int ProjectDocument::schema_version() const {
    const auto it = root_.find("schema_version");
    if (it == root_.end() || !it->is_number_integer()) return 1;
    return it->get<int>();
}

bool ProjectDocument::future_schema() const {
    return schema_version() > kKnownProjectSchemaVersion;
}

std::optional<ProjectMetaView> ProjectDocument::meta() const {
    const auto it = root_.find("meta");
    if (it == root_.end() || !it->is_object()) return std::nullopt;
    const Json& meta = *it;
    ProjectMetaView view;
    view.name = meta.value("name", "");
    view.region = meta.value("region", "");
    view.app_version = meta.value("version", std::string("0.2.17a0"));
    view.created_at = meta.value("created_at", "");
    view.updated_at = meta.value("updated_at", "");
    view.project_root = meta.value("project_root", std::string("."));
    return view;
}

const Json* ProjectDocument::find_section(std::string_view key) const {
    const auto it = root_.find(std::string(key));
    return it == root_.end() ? nullptr : &(*it);
}

Json& ProjectDocument::mapping_workspace() {
    auto it = root_.find("mapping_workspace");
    if (it == root_.end()) {
        root_["mapping_workspace"] = Json::object();
        return root_["mapping_workspace"];
    }
    return *it;
}

const Json& ProjectDocument::mapping_workspace() const {
    static const Json kEmpty = Json::object();
    const auto it = root_.find("mapping_workspace");
    return it == root_.end() ? kEmpty : *it;
}

void ProjectDocument::touch_updated_at(const std::string& iso_now) {
    auto it = root_.find("meta");
    if (it == root_.end() || !it->is_object()) return;
    (*it)["updated_at"] = iso_now;
    (*it)["project_root"] = ".";
}

}  // namespace pwb::project
