// ProjectDocument — the portable `.paleo.json` tree with schema-parity
// normalization (schema.hpp machinery) plus typed read accessors for the
// fields the data kernel consumes.
#pragma once

#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/json.hpp"

#include <optional>
#include <string>

namespace pwb::project {

// Highest schema_version this build understands. Files above → read-only +
// future-schema diagnostics (contracts.md §3). v2 = WorkArea sections
// (domain_migration.py SCHEMA_VERSION_WORKAREA); in-memory migration itself
// is app-layer and out of scope for the data kernel.
inline constexpr int kKnownProjectSchemaVersion = 2;

struct ProjectMetaView {
    std::string name;
    std::string region;
    std::string app_version;  // "version" (0.2.17a0)
    std::string created_at;
    std::string updated_at;
    std::string project_root;  // portable form: "."
};

class ProjectDocument {
public:
    ProjectDocument() = default;

    // Fresh document equivalent to ProjectDocument.new(name, region) +
    // full default materialization.
    static ProjectDocument create_new(const std::string& name,
                                      const std::string& region);

    // Parse + normalize. Returns nullopt-equivalent via Result error on
    // hard JSON/schema failures; diagnostics carry the details.
    static domain::Result<ProjectDocument> parse(
        const std::string& text, domain::DiagnosticList& diagnostics);

    domain::Json& root() { return root_; }
    const domain::Json& root() const { return root_; }
    const domain::DiagnosticList& diagnostics() const { return diagnostics_; }
    domain::DiagnosticList& diagnostics() { return diagnostics_; }

    int schema_version() const;
    bool future_schema() const;
    bool read_only() const { return read_only_; }
    void set_read_only(bool value) { read_only_ = value; }

    std::optional<ProjectMetaView> meta() const;
    const domain::Json* find_section(std::string_view key) const;

    // ---- mutable sections the data kernel owns --------------------------
    domain::Json& mapping_workspace();          // creates default object
    const domain::Json& mapping_workspace() const;

    void touch_updated_at(const std::string& iso_now);

private:
    domain::Json root_ = domain::Json::object();
    domain::DiagnosticList diagnostics_;
    bool read_only_ = false;
};

}  // namespace pwb::project
