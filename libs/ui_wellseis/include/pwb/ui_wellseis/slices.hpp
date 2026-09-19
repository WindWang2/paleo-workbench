#pragma once

// UI-09 — host-collected input slices for the well/seismic page cluster.
//
// Convention (mirrors libs/ui_workers): pages never touch a live
// ProjectDocument — the GUI thread collects these narrow field slices and
// hands them in. Every struct carries exactly the fields the Python page
// reads; dict-shaped attributes (result_summary / model_metadata /
// run.parameters / JointAnalysisState) stay domain::Json so the ported
// per-key probes keep Python semantics.

#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_workers/worker_common.hpp>  // ResourceSlice

namespace pwb::ui_wellseis {

using domain::Json;
using ui_workers::ResourceSlice;

// PredictionTask fields the pages read.
struct PredictionTaskSlice {
    std::string id;
    std::string name;
    std::string status;           // raw domain status ("" -> 待开始)
    std::string adapter_kind;
    std::optional<int64_t> seed;  // seismic demo volume seed (task.seed)
    // task.input_refs — e.g. "well_log_resource_ids" / "seismic_resource_ids".
    std::map<std::string, std::vector<std::string>> input_refs;
    Json result_summary = Json::object();
    Json model_metadata = Json::object();
    Json probability_summary = Json::object();
    // task.evidence_contribution — [{name, weight}] rows for the evidence
    // list (Json keeps Python's per-item .get() semantics).
    Json evidence_contribution = Json::array();
    std::size_t review_area_count = 0;  // len(task.review_areas or [])
};

// Inference run record fields (run.id / status / parameters /
// output_version_ids / created_at) — diagnostics + persisted-failure replay.
struct RunSlice {
    std::string id;
    std::string status;
    std::string created_at;
    std::vector<std::string> output_version_ids;
    Json parameters = Json::object();
};

// WellEntity fields the well map / panels read.
struct WellSlice {
    std::string id;
    std::string name;
    std::string uwi;
    std::optional<double> surface_x, surface_y;
    std::optional<double> project_x, project_y;
    std::string coordinate_status;  // ok|untransformed|invalid|missing
    std::string spatial_scope = "workarea";  // workarea|reference
};

// SeismicSurveyEntity fields (survey extent overlay).
struct SurveySlice {
    std::string id;
    std::string name;
    std::string crs;
    std::vector<std::pair<double, double>> extent;  // corners in survey CRS
};

// The project fields the well/seismic pages read.
struct ProjectSlice {
    std::vector<ResourceSlice> resources;
    std::vector<WellSlice> wells;
    std::vector<SurveySlice> seismic_surveys;
    std::string project_crs;
    std::vector<std::pair<double, double>> workarea_boundary;
    std::string workarea_boundary_crs;
    std::string stratigraphy_target_horizon;
    std::string project_root;
};

// WellTablePanel — one well-table row (numeric fields are float-coerced in
// Python; a non-numeric payload is carried as raw text — _fmt parity).
struct WellTableRowSlice {
    std::string well_id;  // stable selection key (row.well_id)
    std::string name;
    std::optional<double> x, y, z, h_s, h_t, r_s, q, b_i, qc_z_star;
    // field name -> str(value) for non-numeric payloads (Python _fmt falls
    // through to str(value) when float() fails).
    std::map<std::string, std::string> raw_text;
    std::string qc_flag = "ok";  // ok|outlier|invalid_ratio|missing
};

struct WellTableSlice {
    std::string id;
    std::string name;
    std::string target_horizon;
    std::string factor_type;
    std::vector<WellTableRowSlice> rows;
};

// CorrelationLinkEditor — FormationTop / CorrelationLink field mirrors.
struct CorrelationTopSlice {
    std::string id;
    std::string well_name;
    std::string marker;
    double depth = 0.0;
    std::string depth_domain;  // str(depth_domain.value)
    std::string method;        // CorrelationMethod value string
    std::string confidence;    // free text ("" renders "—")
    std::string status = "active";  // active|tentative|rejected
    std::string notes;
};

struct CorrelationLinkSlice {
    std::string id;
    std::string top_a_id;
    std::string top_b_id;
    std::string method;
    bool adjacent_only = false;
    std::string notes;
};

// The draft face the editor mutates through the session seams.
struct CorrelationDraftSlice {
    std::vector<CorrelationTopSlice> tops;
    std::vector<CorrelationLinkSlice> links;
    int generation = 0;
};

// WellDetailPanel — catalog.entity_views.WellDataView slice.
struct RoleMemberSlice {
    std::string name;
    bool is_primary = false;
    int version_count = 0;
    std::string current_version_id;  // "" when no current version
};

struct RoleSlotSlice {
    std::string role;
    std::vector<RoleMemberSlice> members;
    bool unresolved = false;
};

struct StaleItemSlice {
    std::string stage;
    std::string version_id;
    bool pinned = false;
};

struct UncommittedEditSlice {
    std::string state;
    std::string source_version_id;
};

struct WellDataViewSlice {
    std::string well_name;
    std::string uwi;
    std::vector<RoleSlotSlice> role_slots;
    std::vector<StaleItemSlice> stale_items;
    std::vector<UncommittedEditSlice> uncommitted_edits;
    std::vector<std::string> missing_source_asset_ids;
};

// JointAnalysisState slice (models.py parity — never stores preview voxels).
struct JointTimeSliceState {
    double time_ms = 0.0;
    bool visible = true;
};

struct JointAnalysisSlice {
    std::map<std::string, bool> tree_checks;
    std::map<std::string, bool> well_visibility;
    std::string well_identity_asset_id;
    std::map<std::string, std::string> well_identity_map;
    std::string seismic_color_scale = "blue-white-red";
    std::string gr_color_scale = "viridis";
    int well_width_px = 5;  // [2, 10]
    std::optional<int> orthogonal_inline_index;
    std::optional<int> orthogonal_crossline_index;
    // Physical survey line numbers — the stable cross-session form (preview
    // indices are LOD-relative; numbers survive a different preview shape).
    std::optional<double> orthogonal_inline_number;
    std::optional<double> orthogonal_crossline_number;
    std::vector<JointTimeSliceState> time_slices;  // max 8
    std::optional<double> active_time_slice_ms;
    int time_slice_opacity = 80;  // [10, 100]
    std::string vertical_domain = "Time";  // Time | Depth
    std::vector<std::string> active_fence_wells;
    std::optional<std::string> active_fence_name;
    std::map<std::string, std::string> path_hints;
};

}  // namespace pwb::ui_wellseis
