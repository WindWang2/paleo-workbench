// XML well-log preview — port of
// resources/preview_parsers/well_log_parsers.xml_well_log_preview
// (SpreadsheetML sheets first, then WITSML logCurveInfo/logData, then
// record/datapoint shapes).
#pragma once

#include <optional>
#include <string>
#include <string_view>

#include "pwb/ingest/preview/models.hpp"

namespace pwb::ingest::preview {

// Returns nullopt when nothing could be parsed (caller falls through).
std::optional<PreviewResult> xml_well_log_preview(const ResourceRef& resource,
                                                  std::string_view bytes,
                                                  const PreviewSettings& settings);

}  // namespace pwb::ingest::preview
