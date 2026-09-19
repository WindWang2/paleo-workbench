// UI-08 — paleo_workbench/mapping/document_io.features_from_document +
// geometry_schema.py normalize_facies / normalize_well / normalize_line /
// normalize_label, ported locally to this slice.
//
// Why local: libs/mapping_document already carries the same port behind
// PWB_BUILD_CONV_02 (pwb::mapping_document::features_from_document), but
// that target is conditional and outside the required UI-08 link set
// (UiDataCore/UiDataQt/UiWidgets/UiShellQt/Qt6::Widgets). This port keeps
// the identical semantics over ui_data_core kernels; the record fields
// are the frozen oracle contract.
//
// Document shape: a domain::Json object mirroring PaleoMapDocument
// (facies_polygons / well_overlays / line_features / label_features /
// edit_history). Malformed per-kind records are skipped, never fatal.
#pragma once

#include "pwb/domain/json.hpp"
#include "pwb/ui_data_core/map_edit_geometry.hpp"

#include <optional>
#include <vector>

namespace pwb::ui_pages_mapedit {

// normalize_facies(raw) — canonical geometry + preserved prediction /
// compiler attributes (facies/probability/region_id/properties).
domain::Json normalize_facies(
    const domain::Json& raw,
    const ui_data_core::FeatureIdFn& ids = nullptr);

// normalize_well(raw) — malformed coordinates are flagged
// coordinate_status="invalid"/"missing", never crash.
domain::Json normalize_well(
    const domain::Json& raw,
    const ui_data_core::FeatureIdFn& ids = nullptr);

// normalize_line(raw).
domain::Json normalize_line(
    const domain::Json& raw,
    const ui_data_core::FeatureIdFn& ids = nullptr);

// normalize_label(raw) — returns nullopt where the Python raises
// ValueError on a malformed anchor (callers skip + log).
std::optional<domain::Json> normalize_label(
    const domain::Json& raw,
    const ui_data_core::FeatureIdFn& ids = nullptr);

// features_from_document(doc) — ordered facies/well/line/label records;
// per-record failures are skipped (the Python try/except + log parity).
// ``ids`` mints missing feature ids (injectable for deterministic tests).
std::vector<domain::Json> features_from_document(
    const domain::Json& doc,
    const ui_data_core::FeatureIdFn& ids = nullptr);

}  // namespace pwb::ui_pages_mapedit
