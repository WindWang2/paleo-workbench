#pragma once

// CLOSURE-PREVIEW (task 04) — pure adapters of the preview closure.
// Qt-free except the types they produce; NO AppShell/window glue here so
// tests can link them without the shell closure.
//
// Contents:
//   * settings mappers between the three frozen PreviewSettings PODs
//     (ui_pages_preview / ui_data_core / ingest — one Python dataclass);
//   * pwb::ingest::preview::PreviewResult → reader view / ui_data_core result;
//   * AssetRow / AssetObjectData → ingest ResourceRef (registry input);
//   * the bounded JSON payload re-resolution the json_tree hook needs;
//   * catalog snapshot → AssetRow (the data page's asset source).

#include <QString>

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_data_core/asset_view.hpp>
#include <pwb/ui_data_core/preview_provider.hpp>
#include <pwb/ui_data_core/preview_types.hpp>
#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/qt/data_reader_panel.hpp>
#include <pwb/ui_pages_preview/preview_settings.hpp>

#include <pwb/ingest/preview/models.hpp>
#include <pwb/ingest/preview/registry.hpp>

namespace pwb::data {
struct ProjectSnapshotV1;
}

namespace pwb::closure_preview {

// --- settings mappers --------------------------------------------------------

pwb::ingest::preview::PreviewSettings to_ingest_settings(
    const ui_pages_preview::PreviewSettings& s);
ui_data_core::PreviewSettings to_core_settings(
    const ui_pages_preview::PreviewSettings& s);

// --- ingest result mapping ---------------------------------------------------

ui_pages_data::qt::PreviewResultView view_from_ingest(
    const pwb::ingest::preview::PreviewResult& r,
    const pwb::ingest::preview::ResourceRef& ref);
ui_data_core::PreviewResult core_from_ingest(
    const pwb::ingest::preview::PreviewResult& r);

// --- registry input mapping --------------------------------------------------

pwb::ingest::preview::ResourceRef ref_from_view(
    const ui_pages_data::AssetView& v);
pwb::ingest::preview::ResourceRef ref_from_asset(
    const ui_data_core::AssetObjectData& asset);

// Bounded re-read + parse for the json_tree family (the ingest registry
// reports json_ok but carries no payload field). Returns nullptr when the
// payload cannot be resolved; `ok=false` then.
std::shared_ptr<const void> load_json_payload(const std::string& path,
                                              int limit_mib, bool& truncated,
                                              bool& ok);

// --- catalog asset source ----------------------------------------------------

std::vector<ui_pages_data::AssetRow> asset_rows_from_snapshot(
    const pwb::data::ProjectSnapshotV1& snapshot);

// --- the data page's base preview builder (ingest registry adapter) ---------

// Runs the REAL parser registry for one asset row and maps the result to
// the reader view (json_tree payloads ride the view's shared owner).
// Worker-thread entry — no QWidget API inside.
ui_pages_data::qt::PreviewResultView build_registry_view(
    const ui_pages_data::AssetRow& row,
    const ui_pages_preview::PreviewSettings& settings);

// --- the VisualizationPage provider (parser-registry backed) -----------------

ui_data_core::PreviewProvider registry_preview_provider();

}  // namespace pwb::closure_preview
