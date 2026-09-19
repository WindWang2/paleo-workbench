// report_export — workflow/qc_report_export.py parity: write a
// QualityReport as UTF-8 JSON through an atomic write (temp file → fsync →
// parse verification → rename) and register the ExportArtifact record. A
// failed write (short write, disk full, unparseable payload) surfaces as a
// DataError and NEVER leaves a success receipt: no artifact record, no
// report mutation.

#pragma once

#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"

#include <filesystem>
#include <optional>
#include <string>

namespace pwb::closure_review {

// default_export_dir parity: a project file yields (and creates)
// <sibling .artifacts root>/exports (artifact_dir_for parity); no project
// → ~/paleo_exports.
std::filesystem::path default_export_dir(
    const std::filesystem::path* project_file);

// export_quality_report_json parity. Serializes the report with the
// non-finite-floats→null normalization, writes it atomically, verifies the
// published file parses, then appends the ExportArtifact record to
// root["export_artifacts"] (linked_id = the report's map document when
// present, else the report id; format "qc_json"; source_task_ids =
// [report id]). root may carry mutable state; iso_now stamps
// generated_at. Failure → DataError with no artifact appended.
domain::DataError export_quality_report_json(
    domain::Json& root, const domain::Json& report,
    const std::filesystem::path& output_path, const std::string& iso_now);

}  // namespace pwb::closure_review
