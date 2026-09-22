// cartographic_qa.cpp — C++ port of
// paleo_workbench/mapping/cartographic_qa.py (V7 §14 cartographic QA rule
// set). See cartographic_qa.hpp for the contract and the Python line
// anchors this file follows.
//
// Structural difference vs Python (documented, honest):
//   * `project` is the ProjectDocument Json root — `user_vector_layers`,
//     `workarea`, `workstation_reference_layers`, `prediction_tasks`,
//     `map_products`, `mapping_workspace` and `compositions` are read as
//     sections. Python's harness-context `compositions` dict maps onto the
//     `compositions` section (object map_id→composition, or array); an
//     absent/empty section is the "no compositions" skip.
//   * There is no pyproj — the C++ port always runs Python's
//     `have_pyproj == False` path: `pwb::mapping::crs_is_geographic` is the
//     single axis-units oracle (nullopt → unit_unknown). `crs_invalid`
//     therefore counts evaluated but can only report through the pyproj
//     branch in Python; kept for summary parity.
//   * The inline MappingDependencyService fallback of _stale_issues is NOT
//     ported (hpp notes): no inputs.stale_summary → explicit skip note.
//   * `role_specs` (the GeologicalLayerSpec registry mirror) arrives via
//     CartographicQaOptions — cartography cannot link ui_composite.
//   * FACTOR_CHILD_ORDER / is_factor_group / factor_task_of_group /
//     MATURITY_ORDER are frozen vocabulary re-declared locally (the
//     canonical C++ homes live in ui_composite — same link reason).

#include <pwb/cartography/cartographic_qa.hpp>

#include <pwb/cartography/geological_symbols.hpp>
#include <pwb/cartography/scalar_style.hpp>
#include <pwb/mapping/crs_policy.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/qc.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace pwb::cartography {
namespace {

// ------------------------------------------------------ frozen vocabulary --

// CARTOGRAPHIC_QA_RULES (cartographic_qa.py L60-76) — cartographic_qa_rules()
// is the exported accessor; this local copy feeds the summary builder.
const std::vector<std::string>& rule_order() {
    static const std::vector<std::string> kRules = {
        "crs_invalid",
        "unit_unknown",
        "geometry_invalid",
        "layer_outside_extent",
        "stale_input",
        "missing_source",
        "renderer_domain_mismatch",
        "legend_empty",
        "core_furniture_missing",
        "low_confidence",
        "fallback_renderer",
        "unpublished_data_in_export",
        "style_binding_unknown",
        "raster_range_invalid",
        "broken_factor_group",
    };
    return kRules;
}

// _LEGEND_FAMILY_VALUES (L84-86).
bool is_legend_family(const std::string& type_value) {
    return type_value == "legend" || type_value == "facies_legend"
           || type_value == "well_legend"
           || type_value == "lithology_legend";
}

// _CORE_FURNITURE_VALUES (L91).
const char* kCoreFurniture[] = {"main_map", "scale_bar", "north_arrow",
                                "title"};

// FACTOR_CHILD_ORDER (mapping_workspace/layer_groups.py L173-180) — role
// VALUES (LayerRole.value, layer_roles.py L41-46).
const char* kFactorChildOrder[] = {
    "factor_input",       "factor_grid",        "factor_contour",
    "factor_classification", "factor_uncertainty", "factor_qc",
};

// MATURITY_ORDER + _MATURITY_EXPORT_FLOOR (stage_state.py L44-49 /
// cartographic_qa.py L80).
int maturity_rank(const std::string& maturity) {
    if (maturity == "draft") return 0;
    if (maturity == "reviewed") return 1;
    if (maturity == "frozen") return 2;
    if (maturity == "published") return 3;
    return -1;
}
constexpr int kExportFloor = 1;  // ArtifactMaturity.REVIEWED

// is_factor_group / factor_task_of_group (layer_groups.py L204-211).
bool is_factor_group(const std::string& group_id) {
    return group_id.rfind("factor.", 0) == 0;
}
std::string factor_task_of_group(const std::string& group_id) {
    return is_factor_group(group_id) ? group_id.substr(7) : "";
}

// ------------------------------------------------------- json micro-reads --

const Json* member(const Json& obj, const char* key) {
    if (!obj.is_object()) return nullptr;
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null()) return nullptr;
    return &*it;
}

const Json* array_member(const Json& obj, const char* key) {
    const Json* v = member(obj, key);
    return (v != nullptr && v->is_array()) ? v : nullptr;
}

// _field(obj, name, default) for the string reads (Mapping.get parity —
// non-string Json values stringify via dump? No: Python str(value) of a
// non-string is its repr; the call sites here all feed string-typed fields,
// so non-string → fallback keeps semantics honest).
std::string str_field(const Json& obj, const char* key,
                      const std::string& fallback = "") {
    const Json* v = member(obj, key);
    if (v == nullptr) return fallback;
    if (v->is_string()) return v->get<std::string>();
    if (v->is_number_integer()) return std::to_string(v->get<long long>());
    if (v->is_number_unsigned())
        return std::to_string(v->get<unsigned long long>());
    if (v->is_number_float()) {
        // str(float) — %g trims like repr for integral-free values.
        char buf[64];
        std::snprintf(buf, sizeof buf, "%g", v->get<double>());
        return buf;
    }
    if (v->is_boolean()) return v->get<bool>() ? "True" : "False";
    return fallback;
}

bool bool_field(const Json& obj, const char* key, bool fallback) {
    const Json* v = member(obj, key);
    if (v != nullptr && v->is_boolean()) return v->get<bool>();
    return fallback;
}

// Truthy-list parity: Python `len(p) >= 2` on a boundary point.
std::optional<double> num_at(const Json& arr, std::size_t i) {
    if (!arr.is_array() || i >= arr.size() || !arr[i].is_number()) {
        return std::nullopt;
    }
    return arr[i].get<double>();
}

// repr() of a Python string list — used inside issue messages verbatim
// (f"{sorted(offenders)}" / f"{missing}" parity).
std::string py_list_repr(const std::vector<std::string>& items) {
    std::string out = "[";
    bool first = true;
    for (const auto& item : items) {
        if (!first) out += ", ";
        out += "'" + item + "'";
        first = false;
    }
    return out + "]";
}

// repr() of a Python float list after round(v, 2).
std::string py_rounded_repr(double v) {
    const double r = std::round(v * 100.0) / 100.0;
    char buf[64];
    std::snprintf(buf, sizeof buf, "%g", r);
    std::string s = buf;
    // Python repr keeps ".0" on integral floats.
    if (s.find_first_of(".eE") == std::string::npos) s += ".0";
    return s;
}
std::string py_bbox_repr(const std::vector<double>& box) {
    std::string out = "[";
    bool first = true;
    for (double v : box) {
        if (!first) out += ", ";
        out += py_rounded_repr(v);
        first = false;
    }
    return out + "]";
}

// ------------------------------------------------------------- accounting --

// _RuleStats (L99-122).
struct RuleStats {
    std::map<std::string, long long> evaluated;
    std::map<std::string, long long> skipped;
    std::map<std::string, std::vector<std::string>> notes;

    void count(const char* rule, long long n = 1) { evaluated[rule] += n; }
    void skip(const char* rule, const std::string& note, long long n = 1) {
        skipped[rule] += n;
        notes[rule].push_back(note);
    }
    Json summary() const {
        Json out = Json::object();
        for (const auto& rule : rule_order()) {
            Json entry;
            entry["evaluated"] = evaluated.count(rule) ? evaluated.at(rule) : 0;
            entry["skipped"] = skipped.count(rule) ? skipped.at(rule) : 0;
            Json notes_arr = Json::array();
            const auto it = notes.find(rule);
            if (it != notes.end()) {
                for (const auto& n : it->second) notes_arr.push_back(n);
            }
            entry["notes"] = std::move(notes_arr);
            out[rule] = std::move(entry);
        }
        return out;
    }
};

Json issue(const char* rule, const char* severity,
           const std::string& message,
           const workflow_runtime::QcIssueFields& fields = {}) {
    return workflow_runtime::make_issue(rule, severity, message, fields);
}

// ------------------------------------------------------- input snapshots --

// _snapshot_layers (L131-137): snapshot may be {layers: [...]} or a bare
// layer array.
std::vector<const Json*> snapshot_layers(const Json& snapshot) {
    std::vector<const Json*> out;
    if (snapshot.is_null()) return out;
    const Json* layers = nullptr;
    if (snapshot.is_object()) {
        layers = member(snapshot, "layers");
    } else if (snapshot.is_array()) {
        layers = &snapshot;
    }
    if (layers != nullptr && layers->is_array()) {
        for (const Json& layer : *layers) out.push_back(&layer);
    }
    return out;
}

// _compositions (L152-153): the `compositions` section — object
// map_id→composition dict or an array of composition dicts.
std::vector<const Json*> compositions_of(const Json& project) {
    std::vector<const Json*> out;
    const Json* comps = member(project, "compositions");
    if (comps == nullptr) return out;
    if (comps->is_object()) {
        for (auto it = comps->begin(); it != comps->end(); ++it) {
            if (it.value().is_object()) out.push_back(&it.value());
        }
    } else if (comps->is_array()) {
        for (const Json& c : *comps) {
            if (c.is_object()) out.push_back(&c);
        }
    }
    return out;
}

// _workspace_state (L140-149): project.mapping_workspace — absent or
// non-object is Python's `not raw` / unparsable → None.
const Json* workspace_state_of(const Json& project) {
    const Json* ws = member(project, "mapping_workspace");
    if (ws == nullptr || !ws->is_object()) return nullptr;
    return ws;
}

const Json* memberships_of(const Json* workspace) {
    if (workspace == nullptr) return nullptr;
    const Json* m = member(*workspace, "memberships");
    return (m != nullptr && m->is_object()) ? m : nullptr;
}

// ------------------------------------------------------------ the rules ----

// _crs_issues (L169-239) — always the no-pyproj path (see file header).
void crs_issues(const Json& project,
                const std::vector<const Json*>& snap_layers,
                RuleStats& stats, Json& issues) {
    std::vector<std::pair<std::string, std::string>> checked;
    if (const Json* layers = array_member(project, "user_vector_layers")) {
        for (const Json& layer : *layers) {
            checked.emplace_back(str_field(layer, "id"),
                                 str_field(layer, "crs"));
        }
    }
    for (const Json* layer : snap_layers) {
        checked.emplace_back(str_field(*layer, "id"),
                             str_field(*layer, "crs"));
    }
    if (checked.empty()) {
        stats.skip("crs_invalid",
                   "no layers to check (project/snapshot empty)");
        stats.skip("unit_unknown",
                   "no layers to check (project/snapshot empty)");
        return;
    }
    for (const auto& [layer_id, crs] : checked) {
        if (crs.empty()) {
            const std::string note =
                "undeclared CRS — the domain of the existing "
                "crs_undeclared rule (workflow.map_qa_rules)";
            stats.skip("crs_invalid", note);
            stats.skip("unit_unknown", note);
            continue;
        }
        stats.count("crs_invalid");
        stats.count("unit_unknown");
        // pyproj is absent in the native build — crs_is_geographic is the
        // whole oracle (nullopt ⇔ Python `crs_is_geographic(crs) is None`).
        if (!pwb::mapping::crs_is_geographic(crs).has_value()) {
            workflow_runtime::QcIssueFields f;
            f.feature_kind = "layer";
            f.ref = layer_id;
            f.extra = Json::object({{"layer_id", layer_id}, {"crs", crs}});
            issues.push_back(issue(
                "unit_unknown", "warning",
                "图层 " + layer_id + " 的 CRS '" + crs +
                    "' 轴单位无法验证（无 pyproj 且非内置已知系）"
                    "——比例尺/距离标注不可信",
                f));
        }
    }
}

// _geometry_issues (L242-298).
void geometry_issues(const Json& project, RuleStats& stats, Json& issues,
                     const CartographicQaOptions& options) {
    const Json* layers = array_member(project, "user_vector_layers");
    if (layers == nullptr || layers->empty()) {
        stats.skip("geometry_invalid", "no user vector layers to validate");
        return;
    }
    const auto validate =
        options.validate_geometry
            ? options.validate_geometry
            : std::function<std::optional<GeometryValidity>(const Json&)>(
                  &validate_geojson_geometry);
    bool engine_ok = true;
    for (const Json& layer : *layers) {
        const std::string layer_id = str_field(layer, "id");
        const Json* features = array_member(layer, "features");
        if (features == nullptr) continue;
        for (const Json& feature : *features) {
            const Json* geometry = member(feature, "geometry");
            if (geometry == nullptr || !geometry->is_object()
                || str_field(*geometry, "type").empty()) {
                stats.skip("geometry_invalid", "feature without geometry", 1);
                continue;
            }
            if (!engine_ok) {
                stats.skip(
                    "geometry_invalid",
                    "no validation engine (qgis bridge + shapely both "
                    "absent)",
                    1);
                continue;
            }
            stats.count("geometry_invalid");
            std::optional<GeometryValidity> result;
            try {
                result = validate(*geometry);
            } catch (const std::runtime_error&) {
                // Python RuntimeError ⇔ "no validation engine".
                result = std::nullopt;
            }
            if (!result.has_value()) {
                engine_ok = false;
                stats.skip(
                    "geometry_invalid",
                    "no validation engine (qgis bridge + shapely both "
                    "absent)",
                    1);
                continue;
            }
            if (!result->valid) {
                const std::string feature_id =
                    str_field(feature, "id");
                workflow_runtime::QcIssueFields f;
                f.feature_id = feature_id;
                f.feature_kind = "layer";
                f.ref = layer_id;
                f.geometry = *geometry;
                f.extra = Json::object(
                    {{"layer_id", layer_id},
                     {"engine", result->engine},
                     {"reason", result->reason}});
                issues.push_back(issue(
                    "geometry_invalid", "error",
                    "图层 " + layer_id + " 要素 " + feature_id +
                        " 几何无效：" +
                        (result->reason.empty() ? "invalid"
                                                : result->reason) +
                        "（" + result->engine + "）",
                    f));
            }
        }
    }
}

// _layer_bbox (L301-319): union bbox of feature geometries, else the
// declared layer extent when it is not the (0,0,1,1) placeholder.
std::optional<std::array<double, 4>> geojson_union_bbox(
    const Json& layer) {
    double x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    bool any = false;
    const Json* features = array_member(layer, "features");
    if (features != nullptr) {
        for (const Json& feature : *features) {
            const Json* geometry = member(feature, "geometry");
            if (geometry == nullptr || !geometry->is_object()) continue;
            // coordinate walk — the same recursion _geojson_bbox uses.
            std::vector<const Json*> stack{member(*geometry, "coordinates")};
            while (!stack.empty()) {
                const Json* node = stack.back();
                stack.pop_back();
                if (node == nullptr || !node->is_array()) continue;
                if (node->size() >= 2 && (*node)[0].is_number()
                    && (*node)[1].is_number()) {
                    const double x = (*node)[0].get<double>();
                    const double y = (*node)[1].get<double>();
                    if (!any) {
                        x0 = x1 = x;
                        y0 = y1 = y;
                        any = true;
                    } else {
                        x0 = std::min(x0, x);
                        y0 = std::min(y0, y);
                        x1 = std::max(x1, x);
                        y1 = std::max(y1, y);
                    }
                    continue;
                }
                for (const Json& child : *node) stack.push_back(&child);
            }
        }
    }
    if (any) return std::array<double, 4>{x0, y0, x1, y1};
    const Json* extent = array_member(layer, "extent");
    if (extent != nullptr && extent->size() == 4) {
        double v[4];
        bool ok = true;
        for (int i = 0; i < 4; ++i) {
            if (!(*extent)[i].is_number()) {
                ok = false;
                break;
            }
            v[i] = (*extent)[i].get<double>();
        }
        // (0,0,1,1) placeholder extent is not evidence.
        if (ok && !(v[0] == 0.0 && v[1] == 0.0 && v[2] == 1.0 && v[3] == 1.0)) {
            return std::array<double, 4>{v[0], v[1], v[2], v[3]};
        }
    }
    return std::nullopt;
}

// geometry_operations.bbox_intersects — closed-interval AABB overlap.
bool bbox_intersects(const std::array<double, 4>& a,
                     const std::array<double, 4>& b) {
    return !(a[2] < b[0] || b[2] < a[0] || a[3] < b[1] || b[3] < a[1]);
}

// _outside_extent_issues (L322-393).
void outside_extent_issues(const Json& project,
                           const std::vector<const Json*>& snap_layers,
                           RuleStats& stats, Json& issues) {
    const Json* workarea = member(project, "workarea");
    const Json* boundary =
        workarea != nullptr ? array_member(*workarea, "boundary") : nullptr;
    if (boundary == nullptr || boundary->empty()) {
        stats.skip(
            "layer_outside_extent",
            "no workarea boundary on the project — nothing to compare "
            "against");
        return;
    }
    double x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    bool any = false;
    for (const Json& point : *boundary) {
        const auto x = num_at(point, 0);
        const auto y = num_at(point, 1);
        if (!x.has_value() || !y.has_value()) continue;
        if (!any) {
            x0 = x1 = *x;
            y0 = y1 = *y;
            any = true;
        } else {
            x0 = std::min(x0, *x);
            y0 = std::min(y0, *y);
            x1 = std::max(x1, *x);
            y1 = std::max(y1, *y);
        }
    }
    if (!any) {
        stats.skip("layer_outside_extent",
                   "workarea boundary has no coordinates");
        return;
    }
    const std::array<double, 4> ref_box{x0, y0, x1, y1};
    const std::string project_crs =
        str_field(*workarea, "project_crs");

    std::set<std::string> user_layer_ids;
    auto check = [&](const Json& layer) {
        const std::string layer_id = str_field(layer, "id");
        const auto bbox = geojson_union_bbox(layer);
        if (!bbox.has_value()) {
            stats.skip("layer_outside_extent",
                       "layer " + layer_id + " has no usable extent");
            return;
        }
        const std::string layer_crs = str_field(layer, "crs");
        if (!project_crs.empty() && !layer_crs.empty()
            && layer_crs != project_crs) {
            stats.skip("layer_outside_extent",
                       "layer " + layer_id + " CRS " + layer_crs +
                           " ≠ workarea CRS " + project_crs +
                           "; comparison needs a transform");
            return;
        }
        stats.count("layer_outside_extent");
        if (!bbox_intersects(*bbox, ref_box)) {
            const std::vector<double> lb{bbox->begin(), bbox->end()};
            const std::vector<double> rb{ref_box.begin(), ref_box.end()};
            workflow_runtime::QcIssueFields f;
            f.feature_kind = "layer";
            f.ref = layer_id;
            f.extra = Json::object(
                {{"layer_id", layer_id},
                 {"layer_bbox", lb},
                 {"workarea_bbox", rb}});
            issues.push_back(issue(
                "layer_outside_extent", "warning",
                "图层 " + layer_id + " 完全位于工区范围之外（图层 " +
                    py_bbox_repr(lb) + " vs 工区 " + py_bbox_repr(rb) +
                    "）",
                f));
        }
    };

    if (const Json* layers = array_member(project, "user_vector_layers")) {
        for (const Json& layer : *layers) {
            user_layer_ids.insert(str_field(layer, "id"));
            check(layer);
        }
    }
    for (const Json* layer : snap_layers) {
        if (user_layer_ids.count(str_field(*layer, "id"))) continue;
        check(*layer);
    }
}

// _stale_issues (L396-449). The inline MappingDependencyService fallback is
// NOT ported — a missing stale_summary skips with an explicit note.
void stale_issues(const Json* workspace, const Json& stale_summary,
                  RuleStats& stats, Json& issues) {
    if (stale_summary.is_null()) {
        if (workspace == nullptr) {
            stats.skip("stale_input",
                       "no workspace state — staleness not computable");
        } else {
            stats.skip(
                "stale_input",
                "no precomputed stale summary — the inline "
                "MappingDependencyService fallback is not ported "
                "(workflow_runtime/staleness.hpp documents the seam)");
        }
        return;
    }
    const Json* artifacts = array_member(stale_summary, "artifacts");
    if (artifacts == nullptr) return;
    for (const Json& entry : *artifacts) {
        stats.count("stale_input");
        if (!bool_field(entry, "is_problem", false)) continue;
        const std::string status = str_field(entry, "status");
        const std::string artifact_key = str_field(entry, "artifact_key");
        Json culprits = Json::array();
        if (const Json* c = array_member(entry, "upstream_culprits")) {
            culprits = *c;
        }
        workflow_runtime::QcIssueFields f;
        f.feature_kind = "artifact";
        f.ref = artifact_key;
        f.extra = Json::object({{"artifact_key", artifact_key},
                                {"status", status},
                                {"upstream_culprits", culprits}});
        issues.push_back(issue(
            "stale_input",
            status == "missing_input" ? "error" : "warning",
            "成果 " + artifact_key + " 输入" +
                str_field(entry, "status_label", status) + "：" +
                str_field(entry, "detail"),
            f));
    }
}

// _missing_source_issues (L452-577).
void missing_source_issues(
    const Json& project, const std::vector<const Json*>& snap_layers,
    const Json* workspace,
    const workflow_runtime::CatalogRepository* catalog, RuleStats& stats,
    Json& issues) {
    long long surfaces = 0;
    auto resolves = [&](const std::string& version_id) -> bool {
        try {
            // The seam is declared non-const on the abstract rail; the
            // inputs hand us a const view — resolve is a read path.
            return const_cast<workflow_runtime::CatalogRepository*>(catalog)
                ->resolve_version(version_id)
                .has_value();
        } catch (...) {
            return false;
        }
    };

    if (catalog != nullptr) {
        for (const Json* layer : snap_layers) {
            const std::string version_id =
                str_field(*layer, "source_version_id");
            if (version_id.empty()) continue;
            ++surfaces;
            stats.count("missing_source");
            if (!resolves(version_id)) {
                const std::string layer_id = str_field(*layer, "id");
                workflow_runtime::QcIssueFields f;
                f.feature_kind = "layer";
                f.ref = layer_id;
                f.extra = Json::object({{"layer_id", layer_id},
                                        {"version_id", version_id}});
                issues.push_back(issue(
                    "missing_source", "error",
                    "图层 " + str_field(*layer, "id") +
                        " 引用的数据版本 " + version_id +
                        " 在目录中不存在（已被清理？）",
                    f));
            }
        }
        if (const Json* memberships = memberships_of(workspace)) {
            for (auto it = memberships->begin(); it != memberships->end();
                 ++it) {
                const Json& record = it.value();
                if (!record.is_object()) continue;
                const std::string version_id =
                    str_field(record, "source_version_id");
                if (version_id.empty()) continue;
                ++surfaces;
                stats.count("missing_source");
                if (!resolves(version_id)) {
                    const std::string layer_id = it.key();
                    workflow_runtime::QcIssueFields f;
                    f.feature_kind = "layer";
                    f.ref = layer_id;
                    f.extra = Json::object({{"layer_id", layer_id},
                                            {"version_id", version_id}});
                    issues.push_back(issue(
                        "missing_source", "error",
                        "图层 " + layer_id + " 溯源钉住的输入版本 " +
                            version_id + " 缺失",
                        f));
                }
            }
        }
    }
    for (const Json* layer : snap_layers) {
        if (str_field(*layer, "layer_type") != "raster_source") continue;
        const Json* path_j = member(*layer, "renderer_payload");
        if (path_j == nullptr || !path_j->is_string()
            || path_j->get<std::string>().empty()) {
            continue;
        }
        const std::string path = path_j->get<std::string>();
        ++surfaces;
        stats.count("missing_source");
        std::error_code ec;
        if (!std::filesystem::exists(path, ec)) {
            const std::string layer_id = str_field(*layer, "id");
            workflow_runtime::QcIssueFields f;
            f.feature_kind = "layer";
            f.ref = layer_id;
            f.extra = Json::object({{"layer_id", layer_id},
                                    {"source_path", path}});
            issues.push_back(issue(
                "missing_source", "error",
                "栅格图层 " + layer_id + " 源文件缺失：" + path, f));
        }
    }
    if (const Json* ref_layers =
            array_member(project, "workstation_reference_layers")) {
        for (const Json& ref_layer : *ref_layers) {
            const std::string source_path =
                str_field(ref_layer, "source_path");
            const std::string status = str_field(ref_layer, "status");
            if (source_path.empty()
                && (status.empty() || status == "ready")) {
                continue;
            }
            ++surfaces;
            stats.count("missing_source");
            const std::string layer_id = str_field(ref_layer, "id");
            if (status == "offline" || status == "failed") {
                workflow_runtime::QcIssueFields f;
                f.feature_kind = "layer";
                f.ref = layer_id;
                f.extra = Json::object({{"layer_id", layer_id},
                                        {"status", status}});
                issues.push_back(issue(
                    "missing_source", "warning",
                    "参考图层 " + str_field(ref_layer, "name") +
                        " 状态为 " + status + "：" +
                        str_field(ref_layer, "error_message"),
                    f));
            } else if (!source_path.empty()) {
                std::error_code ec;
                if (!std::filesystem::exists(source_path, ec)) {
                    workflow_runtime::QcIssueFields f;
                    f.feature_kind = "layer";
                    f.ref = layer_id;
                    f.extra = Json::object({{"layer_id", layer_id},
                                            {"source_path", source_path}});
                    issues.push_back(issue(
                        "missing_source", "error",
                        "参考图层 " + str_field(ref_layer, "name") +
                            " 源文件缺失：" + source_path,
                        f));
                }
            }
        }
    }
    if (surfaces == 0) {
        stats.skip(
            "missing_source",
            "no layer carries a catalog version id, raster file path or "
            "reference-layer status to verify");
    }
}

// _renderer_domain_issues (L580-686): categorized values must stay inside
// the spec's closed domain. role→spec arrives through options.role_specs.
void renderer_domain_issues(
    const Json& project, const std::vector<const Json*>& snap_layers,
    const Json* workspace, const Json* role_specs, RuleStats& stats,
    Json& issues) {
    const Json* memberships = memberships_of(workspace);
    if (memberships == nullptr || memberships->empty()) {
        stats.skip(
            "renderer_domain_mismatch",
            "no layer roles recorded (workspace state empty) — domain "
            "check needs the role→spec binding");
        return;
    }
    std::map<std::string, const Json*> layers_by_id;
    if (const Json* layers = array_member(project, "user_vector_layers")) {
        for (const Json& layer : *layers) {
            layers_by_id[str_field(layer, "id")] = &layer;
        }
    }
    for (const Json* layer : snap_layers) {
        layers_by_id.try_emplace(str_field(*layer, "id"), layer);
    }

    long long known_roles = 0;
    for (auto it = memberships->begin(); it != memberships->end(); ++it) {
        const std::string& layer_id = it.key();
        const Json& record = it.value();
        const std::string role = record.is_object()
                                     ? str_field(record, "role")
                                     : "";
        const Json* spec =
            (role_specs != nullptr && role_specs->is_object()
             && !role.empty())
                ? member(*role_specs, role.c_str())
                : nullptr;
        if (spec == nullptr || !spec->is_object()) {
            stats.skip("renderer_domain_mismatch",
                       "layer " + layer_id + " role '" + role +
                           "' has no GeologicalLayerSpec");
            continue;
        }
        ++known_roles;
        const auto layer_it = layers_by_id.find(layer_id);
        if (layer_it == layers_by_id.end()) {
            stats.skip("renderer_domain_mismatch",
                       "layer " + layer_id + " (role " + role +
                           ") not present in the project/snapshot");
            continue;
        }
        const Json& layer = *layer_it->second;
        const Json* style = member(layer, "style");
        if (style == nullptr || !style->is_object()
            || str_field(*style, "renderer") != "categorized") {
            stats.count("renderer_domain_mismatch");
            continue;
        }
        std::string field_name = str_field(*style, "field");
        if (field_name.empty()) {
            if (const Json* binding = member(*spec, "renderer_binding");
                binding != nullptr && binding->is_object()) {
                field_name = str_field(*binding, "field");
            }
        }
        const std::string spec_id = str_field(*spec, "spec_id");
        if (field_name.empty()) {
            stats.skip("renderer_domain_mismatch",
                       "layer " + layer_id +
                           " categorized style declares no field and spec " +
                           spec_id + " binds none");
            continue;
        }
        const Json* spec_field = nullptr;
        if (const Json* fields = array_member(*spec, "fields")) {
            for (const Json& f : *fields) {
                if (str_field(f, "name") == field_name) {
                    spec_field = &f;
                    break;
                }
            }
        }
        const Json* choices =
            spec_field != nullptr ? array_member(*spec_field, "choices")
                                  : nullptr;
        if (choices == nullptr || choices->empty()) {
            stats.skip("renderer_domain_mismatch",
                       "spec " + spec_id +
                           " declares no closed domain for field " +
                           field_name + " — nothing to check against");
            continue;
        }
        stats.count("renderer_domain_mismatch");
        std::set<std::string> domain;
        for (const Json& c : *choices) {
            if (c.is_string()) domain.insert(c.get<std::string>());
        }
        std::vector<std::string> offenders;
        if (const Json* features = array_member(layer, "features")) {
            for (const Json& feature : *features) {
                const Json* props = member(feature, "properties");
                if (props == nullptr || !props->is_object()) continue;
                const Json* value = member(*props, field_name.c_str());
                if (value == nullptr) continue;
                // str(value) parity: strings raw, numbers formatted,
                // bools Python-cased; other types never match a domain.
                std::string text;
                if (value->is_string()) text = value->get<std::string>();
                else if (value->is_number_integer())
                    text = std::to_string(value->get<long long>());
                else if (value->is_number_float()) {
                    char buf[64];
                    std::snprintf(buf, sizeof buf, "%g",
                                  value->get<double>());
                    text = buf;
                } else if (value->is_boolean()) {
                    text = value->get<bool>() ? "True" : "False";
                } else {
                    text = value->dump();
                }
                if (!domain.count(text)
                    && std::find(offenders.begin(), offenders.end(), text)
                           == offenders.end()) {
                    offenders.push_back(text);
                }
            }
        }
        if (!offenders.empty()) {
            std::sort(offenders.begin(), offenders.end());
            const std::vector<std::string> sorted_domain(domain.begin(),
                                                         domain.end());
            workflow_runtime::QcIssueFields f;
            f.feature_kind = "layer";
            f.ref = layer_id;
            f.extra = Json::object({{"layer_id", layer_id},
                                    {"field", field_name},
                                    {"out_of_domain", offenders},
                                    {"spec_id", spec_id}});
            issues.push_back(issue(
                "renderer_domain_mismatch", "warning",
                "图层 " + layer_id + "（角色 " + role + "）字段 " +
                    field_name + " 出现域外值 " + py_list_repr(offenders) +
                    "——规范 " + spec_id + " 闭域为 " +
                    py_list_repr(sorted_domain),
                f));
        }
    }
    if (known_roles == 0) {
        stats.skip("renderer_domain_mismatch",
                   "no membership carries a spec-bound role");
    }
}

// _legend_backed_types proven set (layout_export.py L215-221 +
// _mirror_proves L153-184): mirror layer_type vocab — COLORBAR←scalar_grid,
// FACIES_LEGEND←polygon/facies or categorized vector, WELL_LEGEND←
// well_point/well.
std::set<std::string> legend_backed_types(
    const std::vector<const Json*>& snap_layers) {
    std::set<std::string> proven;
    std::set<std::string> layer_types;
    for (const Json* layer : snap_layers) {
        layer_types.insert(str_field(*layer, "layer_type"));
    }
    if (layer_types.count("scalar_grid")) proven.insert("colorbar");
    bool facies = layer_types.count("polygon") || layer_types.count("facies");
    if (!facies) {
        for (const Json* layer : snap_layers) {
            const Json* style = member(*layer, "style");
            if (str_field(*layer, "layer_type") == "vector"
                && style != nullptr && style->is_object()
                && str_field(*style, "renderer") == "categorized") {
                facies = true;
                break;
            }
        }
    }
    if (facies) proven.insert("facies_legend");
    if (layer_types.count("well_point") || layer_types.count("well")) {
        proven.insert("well_legend");
    }
    return proven;
}

// _legend_issues (L689-737).
void legend_issues(const Json& project,
                   const std::vector<const Json*>& snap_layers,
                   RuleStats& stats, Json& issues) {
    const auto comps = compositions_of(project);
    if (comps.empty()) {
        stats.skip("legend_empty", "no compositions on the project");
        return;
    }
    const std::set<std::string> proven = legend_backed_types(snap_layers);
    for (const Json* composition : comps) {
        const std::string comp_id = str_field(*composition, "id");
        const Json* elements = array_member(*composition, "elements");
        if (elements == nullptr) continue;
        for (const Json& element : *elements) {
            const std::string type_value =
                str_field(element, "element_type");
            if (!is_legend_family(type_value)) continue;
            if (!bool_field(element, "visible", true)) continue;
            stats.count("legend_empty");
            const Json* props = member(element, "properties");
            const Json* items =
                props != nullptr ? member(*props, "items") : nullptr;
            if (items != nullptr
                && ((items->is_array() && !items->empty())
                    || (items->is_object() && !items->empty()))) {
                continue;  // explicit legend items → resolvable
            }
            if (proven.count(type_value)) continue;
            workflow_runtime::QcIssueFields f;
            f.feature_kind = "composition_element";
            f.feature_id = str_field(element, "id");
            f.ref = comp_id;
            f.extra = Json::object({{"composition_id", comp_id},
                                    {"element_type", type_value}});
            issues.push_back(issue(
                "legend_empty", "warning",
                "组图 " + comp_id + " 的 " + type_value + " 组件 " +
                    str_field(element, "id") +
                    " 无可解析的图例项（items 为空且镜像中无对应图层）",
                f));
        }
    }
}

// _furniture_issues (L740-789).
void furniture_issues(const Json& project, RuleStats& stats, Json& issues) {
    const auto comps = compositions_of(project);
    if (comps.empty()) {
        stats.skip("core_furniture_missing",
                   "no compositions on the project");
        return;
    }
    long long checked = 0;
    for (const Json* composition : comps) {
        const std::string comp_id = str_field(*composition, "id");
        const Json* metadata = member(*composition, "metadata");
        const Json* template_id =
            metadata != nullptr ? member(*metadata, "template_id") : nullptr;
        const bool promised =
            template_id != nullptr && !template_id->is_null()
            && !(template_id->is_string()
                 && template_id->get<std::string>().empty());
        if (!promised) {
            stats.skip(
                "core_furniture_missing",
                "composition " + comp_id +
                    " records no template expectation "
                    "(metadata.template_id absent) — furniture set not "
                    "promised");
            continue;
        }
        ++checked;
        std::set<std::string> visible_values;
        if (const Json* elements =
                array_member(*composition, "elements")) {
            for (const Json& el : *elements) {
                if (!bool_field(el, "visible", true)) continue;
                visible_values.insert(str_field(el, "element_type"));
            }
        }
        for (const char* required : kCoreFurniture) {
            stats.count("core_furniture_missing");
            if (!visible_values.count(required)) {
                workflow_runtime::QcIssueFields f;
                f.feature_kind = "composition";
                f.ref = comp_id;
                f.extra = Json::object({{"composition_id", comp_id},
                                        {"missing", required},
                                        {"template_id", *template_id}});
                issues.push_back(issue(
                    "core_furniture_missing", "warning",
                    "模板组图 " + comp_id + " 缺少核心成图组件 " + required,
                    f));
            }
        }
    }
    if (checked == 0) {
        stats.skip(
            "core_furniture_missing",
            "no composition is template-built; furniture set not promised");
    }
}

// _confidence_issues (L792-842).
void confidence_issues(const Json& project, RuleStats& stats, Json& issues,
                       double threshold) {
    const Json* tasks = array_member(project, "prediction_tasks");
    std::vector<const Json*> with_summary;
    if (tasks != nullptr) {
        for (const Json& task : *tasks) {
            if (member(task, "probability_summary") != nullptr) {
                with_summary.push_back(&task);
            }
        }
    }
    if (with_summary.empty()) {
        stats.skip("low_confidence",
                   "no prediction overlays with probability stats");
        return;
    }
    char thr[16];
    std::snprintf(thr, sizeof thr, "%.2f", threshold);
    for (const Json* task : with_summary) {
        stats.count("low_confidence");
        const Json* summary = member(*task, "probability_summary");
        const std::string task_id = str_field(*task, "id");
        const Json* mean = member(*summary, "mean");
        if (mean == nullptr) {
            mean = member(*summary, "mean_probability");
        }
        const Json* minimum = member(*summary, "min");
        if (minimum == nullptr) {
            minimum = member(*summary, "min_probability");
        }
        long long low_regions = 0;
        if (const Json* lr = member(*summary, "low_confidence_regions");
            lr != nullptr && lr->is_number()) {
            low_regions = lr->get<long long>();
        }
        const bool below =
            (mean != nullptr && mean->is_number()
             && mean->get<double>() < threshold)
            || (minimum != nullptr && minimum->is_number()
                && minimum->get<double>() < threshold);
        if (below || low_regions > 0) {
            workflow_runtime::QcIssueFields f;
            f.feature_kind = "prediction_task";
            f.ref = task_id;
            f.extra = Json::object(
                {{"prediction_task_id", task_id},
                 {"mean", mean != nullptr ? *mean : Json(nullptr)},
                 {"min", minimum != nullptr ? *minimum : Json(nullptr)},
                 {"threshold", threshold},
                 {"low_confidence_regions", low_regions}});
            const std::string mean_str =
                mean != nullptr && mean->is_number()
                    ? str_field(*summary,
                                member(*summary, "mean") ? "mean"
                                                         : "mean_probability")
                    : "None";
            const std::string min_str =
                minimum != nullptr && minimum->is_number()
                    ? str_field(*summary,
                                member(*summary, "min") ? "min"
                                                        : "min_probability")
                    : "None";
            issues.push_back(issue(
                "low_confidence", "warning",
                "预测 " + task_id + "（" + str_field(*task, "name") +
                    "）置信度低：mean=" + mean_str + " min=" + min_str +
                    " 阈值=" + thr + " 低置信区域 " +
                    std::to_string(low_regions) + " 个",
                f));
        }
    }
}

// _capability_says_qgis_available (L845-853).
std::optional<bool> capability_qgis_available(const Json& capability) {
    if (capability.is_null() || !capability.is_object()) {
        return std::nullopt;
    }
    if (const Json* v = member(capability, "qgis_available")) {
        if (v->is_boolean()) return v->get<bool>();
        return !v->is_null() && v->get<bool>();
    }
    // capability.get("engine") or capability.get("backend") or "" —
    // empty-string engine falls through to backend (Python `or` parity).
    std::string engine = str_field(capability, "engine");
    if (engine.empty()) engine = str_field(capability, "backend");
    if (!engine.empty()) {
        std::string lower = engine;
        std::transform(lower.begin(), lower.end(), lower.begin(),
                       [](unsigned char c) { return std::tolower(c); });
        return lower == "qgis" || lower == "qgis_layout";
    }
    return std::nullopt;
}

// _fallback_renderer_issues (L856-903).
void fallback_renderer_issues(
    const std::vector<const Json*>& snap_layers, const Json& capability,
    RuleStats& stats, Json& issues) {
    const auto available = capability_qgis_available(capability);
    if (!available.has_value()) {
        stats.skip(
            "fallback_renderer",
            "no capability snapshot provided — renderer degradation "
            "cannot be asserted");
        return;
    }
    std::vector<const Json*> scalar_layers;
    for (const Json* layer : snap_layers) {
        const std::string t = str_field(*layer, "layer_type");
        if (t == "scalar_grid" || t == "grid") scalar_layers.push_back(layer);
    }
    if (scalar_layers.empty() || *available) {
        stats.count("fallback_renderer");
        return;
    }
    const std::string reason =
        capability.is_object() ? str_field(capability, "reason") : "";
    for (const Json* layer : scalar_layers) {
        stats.count("fallback_renderer");
        const std::string layer_id = str_field(*layer, "id");
        workflow_runtime::QcIssueFields f;
        f.feature_kind = "layer";
        f.ref = layer_id;
        f.extra = Json::object({{"layer_id", layer_id},
                                {"qgis_available", false},
                                {"reason", reason}});
        issues.push_back(issue(
            "fallback_renderer", "warning",
            "QGIS 渲染不可用但标量图层 " + layer_id +
                " 存在——栅格走降级渲染路径（RGBA 镜像而非 QGIS 伪彩色）" +
                (reason.empty() ? "" : "：" + reason) +
                "，屏显与导出可能存在符号差异",
            f));
    }
}

// _maturity_issues (L906-956).
void maturity_issues(const Json& project, const Json* workspace,
                     RuleStats& stats, Json& issues) {
    const Json* products = array_member(project, "map_products");
    if (products == nullptr || products->empty()) {
        stats.skip(
            "unpublished_data_in_export",
            "no MapProduct record — rule is scoped to export-bound "
            "projects");
        return;
    }
    const Json* maturity_map =
        workspace != nullptr ? member(*workspace, "artifact_maturity")
                             : nullptr;
    if (maturity_map == nullptr || !maturity_map->is_object()
        || maturity_map->empty()) {
        stats.skip(
            "unpublished_data_in_export",
            "no artifact maturity recorded — nothing to assert "
            "(unrecorded maturity is never guessed as draft)");
        return;
    }
    for (auto it = maturity_map->begin(); it != maturity_map->end(); ++it) {
        stats.count("unpublished_data_in_export");
        const std::string& artifact_key = it.key();
        const std::string maturity =
            it.value().is_string() ? it.value().get<std::string>() : "";
        const int rank = maturity_rank(maturity);
        if (rank < 0) {
            stats.skip("unpublished_data_in_export",
                       "artifact " + artifact_key +
                           " carries unknown maturity '" + maturity + "'");
            continue;
        }
        if (rank < kExportFloor) {
            std::string layer_id;
            const auto colon = artifact_key.find(':');
            if (colon != std::string::npos) {
                const std::string tail = artifact_key.substr(colon + 1);
                if (tail.rfind("factor", 0) != 0
                    && tail.rfind("mapproduct", 0) != 0) {
                    layer_id = tail;
                }
            }
            workflow_runtime::QcIssueFields f;
            f.feature_kind = "artifact";
            f.ref = artifact_key;
            f.extra = Json::object({{"artifact_key", artifact_key},
                                    {"maturity", maturity},
                                    {"layer_id", layer_id}});
            issues.push_back(issue(
                "unpublished_data_in_export", "warning",
                "成果 " + artifact_key + " 成熟度为 " + maturity +
                    "（低于 reviewed）却参与了绑定导出的成图产品",
                f));
        }
    }
}

// _style_binding_issues (L994-1068): the probe is the V2 registry's
// symbol_by_id (alias-aware, std::out_of_range ⇔ Python KeyError).
void style_binding_issues(const Json& project,
                          const std::vector<const Json*>& snap_layers,
                          RuleStats& stats, Json& issues) {
    auto probe = [](const std::string& symbol_id) -> bool {
        try {
            return &symbol_by_id(symbol_id) != nullptr;
        } catch (const std::out_of_range&) {
            return false;
        }
    };
    auto binding_id = [](const Json& layer) -> std::string {
        for (const char* source_key : {"style", "metadata"}) {
            const Json* source = member(layer, source_key);
            if (source == nullptr || !source->is_object()) continue;
            const Json* binding = member(*source, "style_binding");
            if (binding == nullptr) continue;
            if (binding->is_string()
                && !binding->get<std::string>().empty()) {
                return binding->get<std::string>();
            }
            if (binding->is_object()) {
                return str_field(*binding, "symbol_id");
            }
        }
        return "";
    };

    long long checked = 0;
    if (const Json* layers = array_member(project, "user_vector_layers")) {
        for (const Json& layer : *layers) {
            const std::string symbol_id = binding_id(layer);
            if (symbol_id.empty()) continue;
            ++checked;
            stats.count("style_binding_unknown");
            if (!probe(symbol_id)) {
                const std::string layer_id = str_field(layer, "id");
                workflow_runtime::QcIssueFields f;
                f.feature_kind = "layer";
                f.ref = layer_id;
                f.extra = Json::object({{"layer_id", layer_id},
                                        {"symbol_id", symbol_id}});
                issues.push_back(issue(
                    "style_binding_unknown", "warning",
                    "图层 " + layer_id + " 的 style_binding 引用符号 " +
                        symbol_id + "，但 V2 符号库中不存在",
                    f));
            }
        }
    }
    for (const Json* layer : snap_layers) {
        const std::string symbol_id = binding_id(*layer);
        if (symbol_id.empty()) continue;
        ++checked;
        stats.count("style_binding_unknown");
        if (!probe(symbol_id)) {
            const std::string layer_id = str_field(*layer, "id");
            workflow_runtime::QcIssueFields f;
            f.feature_kind = "layer";
            f.ref = layer_id;
            f.extra = Json::object({{"layer_id", layer_id},
                                    {"symbol_id", symbol_id}});
            issues.push_back(issue(
                "style_binding_unknown", "warning",
                "快照图层 " + layer_id +
                    " 的 style_binding 引用未知符号 " + symbol_id,
                f));
        }
    }
    if (checked == 0) {
        stats.skip("style_binding_unknown",
                   "no layer records a style_binding");
    }
}

// _raster_range_issues (L1071-1139).
void raster_range_issues(const std::vector<const Json*>& snap_layers,
                         RuleStats& stats, Json& issues) {
    std::vector<const Json*> scalar_layers;
    for (const Json* layer : snap_layers) {
        const std::string t = str_field(*layer, "layer_type");
        if (t == "scalar_grid" || t == "grid") scalar_layers.push_back(layer);
    }
    if (scalar_layers.empty()) {
        stats.skip("raster_range_invalid",
                   "no scalar layers in the snapshot");
        return;
    }
    auto bad_range = [](const Json& lo, const Json& hi) -> std::string {
        if (!lo.is_number() || !hi.is_number()) {
            return "non-numeric range [" + lo.dump() + ", " + hi.dump() + "]";
        }
        const double lo_f = lo.get<double>();
        const double hi_f = hi.get<double>();
        if (std::isnan(lo_f) || std::isnan(hi_f)) {
            return "NaN in range [" + lo.dump() + ", " + hi.dump() + "]";
        }
        if (!(hi_f > lo_f)) {
            char buf[96];
            std::snprintf(buf, sizeof buf, "hi<=lo in range [%g, %g]", lo_f,
                          hi_f);
            return buf;
        }
        return "";
    };

    for (const Json* layer : scalar_layers) {
        stats.count("raster_range_invalid");
        const std::string layer_id = str_field(*layer, "id");
        const Json* style_j = member(*layer, "style");
        const Json empty_style = Json::object();
        const Json& style =
            (style_j != nullptr && style_j->is_object()) ? *style_j
                                                         : empty_style;
        std::string problem;
        const Json* nested = member(style, "scalar_style");
        const bool nested_ok =
            nested != nullptr && nested->is_object() && !nested->empty();
        if (nested_ok) {
            try {
                ScalarStyleSpec::from_dict(*nested);
            } catch (const std::invalid_argument& exc) {
                problem = exc.what();
            }
        }
        if (problem.empty()) {
            // Python precedence: (style.manual or nested.manual) when nested
            // is a Mapping, else style.manual.
            const Json* manual = member(style, "manual_range");
            if ((manual == nullptr || manual->is_null()) && nested_ok) {
                manual = member(*nested, "manual_range");
            }
            if (manual != nullptr && manual->is_array()
                && manual->size() == 2) {
                problem = bad_range((*manual)[0], (*manual)[1]);
            }
        }
        if (problem.empty()) {
            if (const Json* legacy = member(style, "color_range");
                legacy != nullptr && legacy->is_array()
                && legacy->size() == 2) {
                problem = bad_range((*legacy)[0], (*legacy)[1]);
            }
        }
        if (problem.empty()) {
            if (const Json* stats_range = member(style, "value_range");
                stats_range != nullptr && stats_range->is_array()
                && stats_range->size() == 2) {
                problem =
                    bad_range((*stats_range)[0], (*stats_range)[1]);
            }
        }
        if (problem.empty()) {
            const Json* grid_stats = member(*layer, "metadata");
            if (grid_stats != nullptr && grid_stats->is_object()) {
                for (const char* key : {"min", "max"}) {
                    const Json* value = member(*grid_stats, key);
                    if (value != nullptr && value->is_number_float()
                        && std::isnan(value->get<double>())) {
                        problem = std::string("NaN ") + key +
                                  " in grid stats";
                        break;
                    }
                }
            }
        }
        if (!problem.empty()) {
            workflow_runtime::QcIssueFields f;
            f.feature_kind = "layer";
            f.ref = layer_id;
            f.extra = Json::object({{"layer_id", layer_id},
                                    {"problem", problem}});
            issues.push_back(issue(
                "raster_range_invalid", "error",
                "标量图层 " + layer_id +
                    " 的显示范围无效：" + problem,
                f));
        }
    }
}

// _factor_group_issues (L1142-1207).
void factor_group_issues(const Json* workspace, RuleStats& stats,
                         Json& issues) {
    if (workspace == nullptr) {
        stats.skip("broken_factor_group",
                   "no workspace state — groups unknown");
        return;
    }
    const Json* tree = member(*workspace, "tree");
    if (tree == nullptr || !tree->is_object() || tree->empty()) {
        stats.skip("broken_factor_group",
                   "workspace tree empty — no groups");
        return;
    }
    const Json* memberships = memberships_of(workspace);

    // _walk_group (L1154-1169): non-layer children recurse; their layer
    // ids fold back into the parent's list.
    std::vector<std::pair<std::string, std::vector<std::string>>> groups;
    std::vector<const Json*> stack{tree};
    std::function<std::vector<std::string>(const Json&)> walk =
        [&](const Json& node) -> std::vector<std::string> {
        std::string group_id = str_field(node, "id");
        if (group_id.empty()) group_id = str_field(node, "group_id");
        std::vector<std::string> layer_ids;
        if (const Json* children = array_member(node, "children")) {
            for (const Json& child : *children) {
                const bool is_layer =
                    str_field(child, "type") == "layer"
                    || member(child, "layer_id") != nullptr;
                if (is_layer) {
                    std::string lid = str_field(child, "id");
                    if (lid.empty()) lid = str_field(child, "layer_id");
                    layer_ids.push_back(lid);
                } else {
                    auto sub = walk(child);
                    layer_ids.insert(layer_ids.end(), sub.begin(),
                                     sub.end());
                }
            }
        }
        groups.emplace_back(group_id, layer_ids);
        return layer_ids;
    };
    walk(*tree);

    bool saw_factor_group = false;
    for (const auto& [group_id, layer_ids] : groups) {
        if (!is_factor_group(group_id)) continue;
        saw_factor_group = true;
        stats.count("broken_factor_group");
        std::set<std::string> present_roles;
        if (memberships != nullptr) {
            for (const auto& lid : layer_ids) {
                const Json* record = member(*memberships, lid.c_str());
                if (record != nullptr && record->is_object()) {
                    present_roles.insert(str_field(*record, "role"));
                }
            }
        }
        std::vector<std::string> missing;
        for (const char* role : kFactorChildOrder) {
            if (!present_roles.count(role)) missing.emplace_back(role);
        }
        if (!missing.empty()) {
            const std::string task_id = factor_task_of_group(group_id);
            const std::vector<std::string> all(
                std::begin(kFactorChildOrder), std::end(kFactorChildOrder));
            workflow_runtime::QcIssueFields f;
            f.feature_kind = "layer_group";
            f.ref = group_id;
            f.extra = Json::object({{"group_id", group_id},
                                    {"missing_roles", missing},
                                    {"factor_task_id", task_id}});
            issues.push_back(issue(
                "broken_factor_group", "warning",
                "单因素组 " + group_id + "（任务 " + task_id +
                    "）缺少子角色 " + py_list_repr(missing) +
                    "——FACTOR_CHILD_ORDER 应为 " + py_list_repr(all),
                f));
        }
    }
    if (!saw_factor_group) {
        stats.skip("broken_factor_group",
                   "no factor.<task> groups in the tree");
    }
}

// -------------------------------------------------- the builtin validator --

// validate_geojson_geometry helpers — bounded pure-C++ GeoJSON validity
// (the facade's "host" engine label).

struct Pt {
    double x = 0, y = 0;
    bool ok = false;
};

Pt position_of(const Json& node) {
    Pt p;
    if (!node.is_array() || node.size() < 2 || !node[0].is_number()
        || !node[1].is_number()) {
        return p;
    }
    p.x = node[0].get<double>();
    p.y = node[1].get<double>();
    p.ok = std::isfinite(p.x) && std::isfinite(p.y);
    return p;
}

// Proper crossing test (segments share no endpoint in the caller's filter):
// orientations strictly opposite on both sides.
int orient(const Pt& a, const Pt& b, const Pt& c) {
    const double cross =
        (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
    constexpr double eps = 1e-12;
    if (cross > eps) return 1;
    if (cross < -eps) return -1;
    return 0;
}

bool on_segment(const Pt& a, const Pt& b, const Pt& p) {
    return std::min(a.x, b.x) - 1e-12 <= p.x
           && p.x <= std::max(a.x, b.x) + 1e-12
           && std::min(a.y, b.y) - 1e-12 <= p.y
           && p.y <= std::max(a.y, b.y) + 1e-12;
}

// Proper interior crossing OR collinear interior overlap — the invalid
// classes shapely is_valid flags for ring self-intersection.
bool segments_bad_cross(const Pt& a1, const Pt& a2, const Pt& b1,
                        const Pt& b2) {
    const int o1 = orient(a1, a2, b1);
    const int o2 = orient(a1, a2, b2);
    const int o3 = orient(b1, b2, a1);
    const int o4 = orient(b1, b2, a2);
    if (o1 != o2 && o3 != o4 && o1 != 0 && o2 != 0 && o3 != 0 && o4 != 0) {
        return true;  // proper crossing
    }
    // Collinear overlap: same support line + interior overlap beyond a
    // shared endpoint.
    if (o1 == 0 && o2 == 0 && o3 == 0 && o4 == 0) {
        // Parameterize by the dominant axis.
        const bool use_x =
            std::fabs(a2.x - a1.x) >= std::fabs(a2.y - a1.y);
        auto coord = [&](const Pt& p) { return use_x ? p.x : p.y; };
        const double a_lo = std::min(coord(a1), coord(a2));
        const double a_hi = std::max(coord(a1), coord(a2));
        const double b_lo = std::min(coord(b1), coord(b2));
        const double b_hi = std::max(coord(b1), coord(b2));
        const double overlap =
            std::min(a_hi, b_hi) - std::max(a_lo, b_lo);
        if (overlap > 1e-12) return true;  // real interior overlap
    }
    return false;
}

GeometryValidity invalid(const std::string& reason) {
    GeometryValidity v;
    v.valid = false;
    v.reason = reason;
    v.engine = "host";
    return v;
}

GeometryValidity check_ring(const Json& ring) {
    if (!ring.is_array() || ring.size() < 4) {
        return invalid("ring needs >= 4 positions");
    }
    const std::size_t n = ring.size();
    std::vector<Pt> pts(n);
    for (std::size_t i = 0; i < n; ++i) {
        pts[i] = position_of(ring[i]);
        if (!pts[i].ok) return invalid("malformed position in ring");
    }
    if (pts.front().x != pts.back().x || pts.front().y != pts.back().y) {
        return invalid("ring is not closed");
    }
    // Signed area (shoelace over the open ring).
    double area = 0;
    for (std::size_t i = 0; i + 1 < n; ++i) {
        area += pts[i].x * pts[i + 1].y - pts[i + 1].x * pts[i].y;
    }
    if (std::fabs(area) <= 1e-18) {
        return invalid("ring has zero signed area");
    }
    // Non-adjacent duplicate vertices (closing pair excluded).
    for (std::size_t i = 0; i + 1 < n; ++i) {
        for (std::size_t j = i + 1; j + 1 < n; ++j) {
            if (j == i + 1) continue;
            if (pts[i].x == pts[j].x && pts[i].y == pts[j].y) {
                return invalid("duplicate non-adjacent vertex in ring");
            }
        }
    }
    // Non-adjacent segment pairs: proper crossing / collinear overlap.
    const std::size_t segs = n - 1;
    for (std::size_t i = 0; i < segs; ++i) {
        for (std::size_t j = i + 1; j < segs; ++j) {
            if (j == i + 1) continue;
            if (i == 0 && j == segs - 1) continue;  // closing adjacency
            if (segments_bad_cross(pts[i], pts[i + 1], pts[j],
                                   pts[j + 1])) {
                return invalid("ring self-intersects");
            }
        }
    }
    return GeometryValidity{};
}

GeometryValidity check_linestring(const Json& line) {
    if (!line.is_array() || line.size() < 2) {
        return invalid("linestring needs >= 2 positions");
    }
    for (const Json& node : line) {
        if (!position_of(node).ok) {
            return invalid("malformed position in linestring");
        }
    }
    return GeometryValidity{};
}

GeometryValidity check_point_coords(const Json& node) {
    if (!position_of(node).ok) return invalid("malformed point");
    return GeometryValidity{};
}

GeometryValidity check_polygon(const Json& polygon) {
    if (!polygon.is_array() || polygon.empty()) {
        return invalid("polygon needs >= 1 ring");
    }
    for (const Json& ring : polygon) {
        const GeometryValidity v = check_ring(ring);
        if (!v.valid) return v;
    }
    return GeometryValidity{};
}

GeometryValidity check_geometry(const Json& geometry) {
    if (!geometry.is_object()) return invalid("geometry is not an object");
    const Json* type = member(geometry, "type");
    const std::string t =
        type != nullptr && type->is_string() ? type->get<std::string>() : "";
    if (t == "Point") {
        const Json* c = member(geometry, "coordinates");
        return c != nullptr ? check_point_coords(*c)
                            : invalid("missing coordinates");
    }
    if (t == "MultiPoint") {
        const Json* c = member(geometry, "coordinates");
        if (c == nullptr || !c->is_array()) {
            return invalid("missing coordinates");
        }
        for (const Json& node : *c) {
            const GeometryValidity v = check_point_coords(node);
            if (!v.valid) return v;
        }
        return GeometryValidity{};
    }
    if (t == "LineString") {
        const Json* c = member(geometry, "coordinates");
        return c != nullptr ? check_linestring(*c)
                            : invalid("missing coordinates");
    }
    if (t == "MultiLineString") {
        const Json* c = member(geometry, "coordinates");
        if (c == nullptr || !c->is_array()) {
            return invalid("missing coordinates");
        }
        for (const Json& line : *c) {
            const GeometryValidity v = check_linestring(line);
            if (!v.valid) return v;
        }
        return GeometryValidity{};
    }
    if (t == "Polygon") {
        const Json* c = member(geometry, "coordinates");
        return c != nullptr ? check_polygon(*c)
                            : invalid("missing coordinates");
    }
    if (t == "MultiPolygon") {
        const Json* c = member(geometry, "coordinates");
        if (c == nullptr || !c->is_array()) {
            return invalid("missing coordinates");
        }
        for (const Json& polygon : *c) {
            const GeometryValidity v = check_polygon(polygon);
            if (!v.valid) return v;
        }
        return GeometryValidity{};
    }
    if (t == "GeometryCollection") {
        const Json* geoms = member(geometry, "geometries");
        if (geoms == nullptr || !geoms->is_array()) {
            return invalid("missing geometries");
        }
        for (const Json& child : *geoms) {
            const GeometryValidity v = check_geometry(child);
            if (!v.valid) return v;
        }
        return GeometryValidity{};
    }
    return invalid("unknown geometry type");
}

// _geojson_bbox (L1281-1302) — issues_for_interactive_hub adapter.
std::optional<std::array<double, 4>> geojson_bbox(const Json& geometry) {
    if (!geometry.is_object()) return std::nullopt;
    double x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    bool any = false;
    std::vector<const Json*> stack{member(geometry, "coordinates")};
    while (!stack.empty()) {
        const Json* node = stack.back();
        stack.pop_back();
        if (node == nullptr || !node->is_array()) continue;
        if (node->size() >= 2 && (*node)[0].is_number()
            && (*node)[1].is_number()) {
            const double x = (*node)[0].get<double>();
            const double y = (*node)[1].get<double>();
            if (!any) {
                x0 = x1 = x;
                y0 = y1 = y;
                any = true;
            } else {
                x0 = std::min(x0, x);
                y0 = std::min(y0, y);
                x1 = std::max(x1, x);
                y1 = std::max(y1, y);
            }
            continue;
        }
        for (const Json& child : *node) stack.push_back(&child);
    }
    if (!any) return std::nullopt;
    return std::array<double, 4>{x0, y0, x1, y1};
}

}  // namespace

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

const std::vector<std::string>& cartographic_qa_rules() {
    return rule_order();
}

std::optional<GeometryValidity> validate_geojson_geometry(
    const Json& geometry) {
    return check_geometry(geometry);
}

CartographicQaReport collect_cartographic_qa(
    const Json& project, const workflow_runtime::CartographicQaInputs& inputs,
    const CartographicQaOptions& options) {
    RuleStats stats;
    const Json* workspace = workspace_state_of(project);
    const auto snap_layers = snapshot_layers(inputs.snapshot);
    Json issues = Json::array();

    crs_issues(project, snap_layers, stats, issues);
    geometry_issues(project, stats, issues, options);
    outside_extent_issues(project, snap_layers, stats, issues);
    stale_issues(workspace, inputs.stale_summary, stats, issues);
    missing_source_issues(project, snap_layers, workspace, inputs.catalog,
                          stats, issues);
    renderer_domain_issues(project, snap_layers, workspace,
                           options.role_specs, stats, issues);
    legend_issues(project, snap_layers, stats, issues);
    furniture_issues(project, stats, issues);
    confidence_issues(project, stats, issues,
                      inputs.confidence_threshold);
    fallback_renderer_issues(snap_layers, inputs.capability, stats, issues);
    maturity_issues(project, workspace, stats, issues);
    style_binding_issues(project, snap_layers, stats, issues);
    raster_range_issues(snap_layers, stats, issues);
    factor_group_issues(workspace, stats, issues);

    return {std::move(issues), stats.summary()};
}

Json collect_cartographic_qa_issues(
    const Json& project, const workflow_runtime::CartographicQaInputs& inputs,
    const CartographicQaOptions& options) {
    return collect_cartographic_qa(project, inputs, options).issues;
}

Json cartographic_rule_summary(
    const Json& project, const workflow_runtime::CartographicQaInputs& inputs,
    const CartographicQaOptions& options) {
    return collect_cartographic_qa(project, inputs, options).summary;
}

Json issues_for_interactive_hub(
    const Json& project, const workflow_runtime::CartographicQaInputs& inputs,
    const CartographicQaOptions& options) {
    Json issues = collect_cartographic_qa_issues(project, inputs, options);
    Json adapted = Json::array();
    if (!issues.is_array()) return adapted;
    for (Json& item : issues) {
        if (!item.is_object()) {
            adapted.push_back(item);
            continue;
        }
        if (!item.contains("bbox")) {
            const Json* geometry = member(item, "geometry");
            auto bbox =
                geometry != nullptr ? geojson_bbox(*geometry) : std::nullopt;
            if (!bbox.has_value()) {
                const Json* centroid = array_member(item, "centroid");
                const auto cx =
                    centroid != nullptr ? num_at(*centroid, 0) : std::nullopt;
                const auto cy =
                    centroid != nullptr ? num_at(*centroid, 1) : std::nullopt;
                if (cx.has_value() && cy.has_value()) {
                    bbox = std::array<double, 4>{
                        *cx - 1.0, *cy - 1.0, *cx + 1.0, *cy + 1.0};
                }
            }
            if (bbox.has_value()) {
                item["bbox"] = std::vector<double>(bbox->begin(), bbox->end());
            }
        }
        if (!item.contains("layer_id")) {
            item["layer_id"] = str_field(item, "ref").empty()
                                   ? str_field(item, "layer")
                                   : str_field(item, "ref");
        }
        adapted.push_back(std::move(item));
    }
    return adapted;
}

}  // namespace pwb::cartography
