// WLE bridge for the LAS preview core — converts well-log-engine
// LasSourceAdapter output into LasPreviewData and installs it as the
// process-wide preview provider. Built only when the WLE SDK participates in
// the build (PWB_SCIENCE_BUILD_VIEWER); without it the registry reports an
// honest capability-unavailable message. The bridge never normalizes input
// ahead of the SDK: preview and the well-log dock share byte-identical WLE
// parse behavior (adjudicated in docs/development/cpp-viz-a/reconciliation.md).
#pragma once

#include <string>

#include "pwb/ingest/preview/las_preview.hpp"

namespace pwb::ingest::preview {

// Parses LAS bytes through WLE LasSourceAdapter and assembles the preview
// facts: ~W well-name scan (the SDK does not surface WELL.), the ~C curve
// table in declaration order (depth channel included), accepted row count,
// and the first kLasPreviewDataRows data rows with the depth channel
// re-inserted at its declared position.
LasPreviewData wle_las_preview_data(const std::string& bytes,
                                    const std::string& path);

// Installs wle_las_preview_data as the LAS preview provider.
void install_wle_las_preview_provider();

}  // namespace pwb::ingest::preview
