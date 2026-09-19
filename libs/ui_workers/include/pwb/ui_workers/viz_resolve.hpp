#pragma once

// UI-04 — the VizAdapter halves the page workers depend on.
// Ports of paleo_workbench/viz/adapter.py (_absolute_path is in
// worker_common) restricted to the surfaces CorrelationLoadWorker and
// WellLogLoadWorker consume:
//   * supports_resource / ref_from_resource (type+format tables verbatim);
//   * _find_resource (id match then path match);
//   * _resolve_well_log (message payloads, never raises; WellLogLoadCancelled
//     propagates — honest cancellation, never a fake "resolved" payload).
// The engine LAS/XML parse (load_well_log_from_path) stays a seam — the
// `load_fn` returns the resolved data object or nullopt (Python `None`).

#include <any>
#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_workers {

// Typed cooperative cancellation from the load pipeline — parity of
// paleo_workbench.viz.well_log_load.WellLogLoadCancelled. NEVER converted
// into a soft-fail message payload.
struct WellLogLoadCancelled : std::exception {
    const char* what() const noexcept override {
        return "cancelled at a load checkpoint";
    }
};

// Adapter type/format tables (adapter.py verbatim).
namespace viz_tables {
extern const std::set<std::string> kWellTypes;       // {"well_log"}
extern const std::set<std::string> kWellFormats;     // {"las","xml"}
extern const std::set<std::string> kSeismicTypes;    // {"seismic"}
extern const std::set<std::string> kSeismicFormats;  // {"sgy","segy"}
extern const std::set<std::string> kMapTypes;        // {"geojson"}
extern const std::set<std::string> kMapFormats;      // {"geojson","json"}
extern const std::set<std::string> kEnginePreviewTypes;  // 5 entries
}  // namespace viz_tables

// Normalized lower/strip used by the adapter tables (type keeps case-fold,
// format also drops a leading dot).
std::string viz_norm_type(const std::string& value);
std::string viz_norm_format(const std::string& value);

// VizAdapter.supports_resource — resource kind support check.
bool supports_resource(const ResourceSlice& resource);

// VizAdapter.ref_from_resource — table dispatch -> VizRef or nullopt.
std::optional<VizRefSlice> ref_from_resource(const ResourceSlice& resource);

// VizAdapter._find_resource — id match first, then path match.
const ResourceSlice* find_resource(const VizRefSlice& ref,
                                   const std::vector<ResourceSlice>& resources);

// The parsed well-log data + its display name (the payload assembly reads
// getattr(data, "well_name", "") — the seam reports it alongside the
// type-erased engine object).
struct LoadedWellLog {
    std::any data;
    std::string well_name;
};

// The engine LAS/XML load seam (load_well_log_from_path): path +
// cooperative cancel-check callable -> the parsed data object or nullopt
// (Python `None` = unreadable). Throwing WellLogLoadCancelled propagates;
// other exceptions are the seam's own failure.
using WellLogLoadFn =
    std::function<std::optional<LoadedWellLog>(
        const std::string& path,
        const std::function<bool()>& is_cancelled)>;

// VizAdapter._resolve_well_log — resource/path resolution -> file check ->
// load_fn -> payload assembly. Message payloads for missing/unparseable
// files; `kind="well_log"` with well_log/well_logs/well_names on success.
VizPayloadSlice resolve_well_log(const VizRefSlice& ref,
                                 const std::vector<ResourceSlice>& resources,
                                 const std::string& project_root,
                                 const std::function<bool()>& is_cancelled,
                                 const WellLogLoadFn& load_fn);

// VizAdapter.resolve dispatch for the worker (well_log kind only).
// Kinds that resolve to other (unported) resolvers — seismic/map/
// cross_well/engine_preview/prediction — throw KernelUnavailable rather
// than emit the "不支持的可视化类型" message (that message is only for
// kinds outside Python's resolver table).
VizPayloadSlice viz_resolve(const VizRefSlice& ref,
                            const std::vector<ResourceSlice>& resources,
                            const std::string& project_root,
                            const std::function<bool()>& is_cancelled,
                            const WellLogLoadFn& load_fn);

}  // namespace pwb::ui_workers
