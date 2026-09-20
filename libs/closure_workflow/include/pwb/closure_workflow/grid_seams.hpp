#pragma once

// Production host seams for the Stage-3 integrated compilation fusion
// (V14-COMPILATION-PUBLISH).
//
// `run_integrated_fusion` documents its byte-loading seams as "the closure
// does not own" them: Python loads grids via catalog.grid_artifact (npz
// bytes) and project.factor_grid_artifacts (live cache → npz → inline).
// This header is the C++ production implementation of exactly that
// surface, so the fusion has a real loading path instead of a test-only
// seam:
//
//   * decode_grid_artifact — the inverse of encode_grid_artifact (the
//     catalog seam's string transport: identity is the checksum, the
//     container is a Json document);
//   * grid_from_version    — a PINNED catalog version's payload → FactorGrid
//     (nullopt == unloadable, which the caller treats as a REFUSAL);
//   * grid_for_task        — the task's CURRENT grid: live cache → npz
//     artifact → inline (the same三级 resolution Python performs).
//
// A seam that cannot resolve returns nullopt — never a substitute grid.
// Qt-free, Python-free.

#include <pwb/closure_workflow/integrated_compilation.hpp>
#include <pwb/factor_fusion/factor_grid.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::closure_workflow {

using pwb::factor_fusion::FactorGrid;
using pwb::workflow_runtime::CatalogRepository;
using Json = pwb::domain::Json;

// Decode a grid artifact payload (encode_grid_artifact's wire form).
// Returns nullopt when the payload is not a decodable factor-grid artifact
// (wrong kind, ragged arrays, non-numeric cells other than "NaN") — the
// caller refuses, it never guesses.
[[nodiscard]] std::optional<FactorGrid> decode_grid_artifact(
    const std::string& payload);

// The catalog-backed pin loader: version_id → payload → decoded grid.
[[nodiscard]] std::optional<FactorGrid> load_grid_from_version(
    CatalogRepository* catalog, const std::string& version_id);

// Live-grid resolver seam: the host supplies the三级 resolution (live
// cache → npz artifact → inline). Returning nullopt == unresolvable.
using LiveGridResolver = std::function<std::optional<FactorGrid>(const Json& task)>;

// Compose the IntegratedGridSeams bundle for production:
//   * grid_from_version — catalog payload decode;
//   * grid_for_task     — the injected live resolver (absent ⇒ every
//     current-grid lookup refuses, which is honest: a missing resolver is
//     a missing capability, not a silent fallback to the pin).
[[nodiscard]] IntegratedGridSeams make_production_grid_seams(
    CatalogRepository* catalog, LiveGridResolver live_resolver = nullptr);

}  // namespace pwb::closure_workflow
