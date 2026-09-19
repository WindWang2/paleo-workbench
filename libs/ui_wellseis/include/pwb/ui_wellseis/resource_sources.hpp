#pragma once

// UI-09 — data-management resource filtering + combo refill (Qt-free).
//
// Ports:
//   seismic_prediction_page.py::_is_segy_resource /
//       _sync_seismic_sources / _selected_seismic_resource
//   well_log_prediction_page.py::_sync_well_sources /
//       _selected_well_resource
//
// The combo entries are ("{name} · {FORMAT}", resource_id); the refill keeps
// the previous selection when its id still resolves, drops it otherwise —
// and a signature comparison lets callers skip the widget refill entirely
// when the entry list is unchanged (V6 scalability note).

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_wellseis {

using ui_workers::ResourceSlice;

// type=="seismic" and (format in {sgy,segy} or path ends .sgy/.segy).
bool is_segy_resource(const ResourceSlice& resource);

// type=="well_log" (any format — the Python page shows all well_log
// resources; the LAS/XML load seam decides readability).
bool is_well_log_resource(const ResourceSlice& resource);

// "{name} · {FORMAT}" or bare name when no format is declared.
std::string resource_combo_label(const ResourceSlice& resource,
                                 const std::string& unnamed_fallback);

// One combo row: visible label + the resource id it resolves to (empty id
// marks the placeholder row the Python page inserts for an empty list).
struct SourceComboEntry {
    std::string label;
    std::string resource_id;  // "" = no resource (placeholder)
};

// Build the combo entry list for the filtered resources; `placeholder`
// labels the single disabled row when the list is empty (the Python pages
// differ here: well-log inserts a placeholder row, seismic clears).
std::vector<SourceComboEntry> source_combo_entries(
    const std::vector<ResourceSlice>& resources,
    const std::string& unnamed_fallback,
    const std::string& placeholder_when_empty);

// The refill decision: index the previous selection resolves to (-1 =
// clear/none). resources/entries are parallel lists minus the placeholder —
// i.e. index into `resources`.
int resolved_source_index(const std::vector<ResourceSlice>& resources,
                          const std::string& previous_resource_id);

// Well-log page parity helper: entries signature for the skip-refill fast
// path (Python compares the (label, id) tuple list).
using SourceSignature = std::vector<std::pair<std::string, std::string>>;
SourceSignature source_signature(
    const std::vector<SourceComboEntry>& entries);

// Find the resource by id within a filtered resource set.
const ResourceSlice* find_resource(
    const std::vector<ResourceSlice>& resources,
    const std::string& resource_id);

// task.input_refs[key][0] -> the bound resource (None-safe: empty ids or
// missing project -> nullptr). The Python `_primary_resource` lookup.
const ResourceSlice* primary_resource(
    const std::map<std::string, std::vector<std::string>>& input_refs,
    const std::string& key,
    const std::vector<ResourceSlice>& resources);

}  // namespace pwb::ui_wellseis
