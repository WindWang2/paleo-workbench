// map_compile.cpp — see include/pwb/closure_workflow/map_compile.hpp.

#include <pwb/closure_workflow/map_compile.hpp>

#include <pwb/closure_workflow/python_json.hpp>
#include <pwb/factor_host/canonical_json.hpp>  // python_repr_double / python_str_scalar / python_float_from_string
#include <pwb/prediction/spatial_result.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/run_orchestration.hpp>

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <set>
#include <utility>
#include <vector>

namespace pwb::closure_workflow {

namespace {

constexpr int kCols = 2;
constexpr double kSide = 0.04;
constexpr double kCell = 0.05;
constexpr double kBaseY = 22.5;

bool truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number()) return v.get<double>() != 0.0;
    if (v.is_string()) return !v.get<std::string>().empty();
    return !v.empty();  // array / object
}

const Json* member(const Json& obj, std::string_view key) {
    if (!obj.is_object()) return nullptr;
    const auto it = obj.find(key);
    return it == obj.end() ? nullptr : &*it;
}

Json get_or(const Json& obj, std::string_view key, Json fallback = Json()) {
    const Json* v = member(obj, key);
    return (v != nullptr && truthy(*v)) ? *v : std::move(fallback);
}

// Python str(x): scalars via the canonical helper; null only reachable
// through unguarded paths (the source always `or`-guards) → "".
std::string py_str(const Json& v) {
    if (v.is_null()) return "";
    return factor_host::python_str_scalar(v);
}

// str(x or default-or-chain) — every Python `a or b or c` over JSON.
std::string py_str_or(const Json& v, const char* fallback) {
    return truthy(v) ? py_str(v) : fallback;
}

std::string py_str_or(const Json& a, const Json& b, const char* fallback) {
    if (truthy(a)) return py_str(a);
    if (truthy(b)) return py_str(b);
    return fallback;
}

// float(x) with the Python acceptance surface (number / bool / numeric
// string); TypeError/ValueError → nullopt.
std::optional<double> py_float(const Json& v) {
    if (v.is_boolean()) return v.get<bool>() ? 1.0 : 0.0;
    if (v.is_number()) return v.get<double>();
    if (v.is_string()) {
        return factor_host::python_float_from_string(v.get<std::string>());
    }
    return std::nullopt;
}

// round(x, 6) — correctly-rounded decimal, half-even (%.6f + strtod).
double py_round6(double x) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.6f", x);
    return std::strtod(buf, nullptr);
}

// Path(name).stem on the POSIX separator only (Python Path semantics on
// Linux hosts; backslash is a literal char there).
std::string path_stem(const std::string& name) {
    const std::size_t slash = name.find_last_of('/');
    const std::string base =
        slash == std::string::npos ? name : name.substr(slash + 1);
    // pathlib: stem of a dotfile like ".las" is ".las" (no split when the
    // dot is at index 0); trailing dot keeps stem "x" for "x.".
    const std::size_t dot = base.find_last_of('.');
    if (dot == std::string::npos || dot == 0) return base;
    return base.substr(0, dot);
}

Json* array_member(Json& obj, std::string_view key) {
    Json* v = nullptr;
    const auto it = obj.find(key);
    if (it != obj.end() && it->is_array()) v = &*it;
    return v;
}

const Json* array_member(const Json& obj, std::string_view key) {
    const auto it = obj.find(key);
    return (it != obj.end() && it->is_array()) ? &*it : nullptr;
}

// ----------------------------- shared resolution ----------------------------

const Json* last_of(const Json* arr) {
    return (arr != nullptr && !arr->empty()) ? &arr->back() : nullptr;
}

// compile_map._resolve_horizon / compile_map_production._resolve_horizon
// differ ONLY in the terminal fallback (未指定层位 vs "").
std::string resolve_horizon(const Json& root,
                            const std::optional<std::string>& target,
                            const char* fallback) {
    if (target.has_value() && !target->empty()) return *target;
    if (const Json* runs = array_member(root, "compilation_runs")) {
        if (const Json* last = last_of(runs)) {
            if (const Json* th = member(*last, "target_horizon");
                th != nullptr && truthy(*th)) {
                return py_str(*th);
            }
        }
    }
    if (const Json* strat = member(root, "stratigraphy")) {
        if (const Json* th = member(*strat, "target_horizon");
            th != nullptr && truthy(*th)) {
            return py_str(*th);
        }
    }
    return fallback;
}

const Json* resolve_prediction_task(
    const Json& root, const std::optional<std::string>& task_id) {
    const Json* tasks = array_member(root, "prediction_tasks");
    if (task_id.has_value() && !task_id->empty()) {
        if (tasks != nullptr) {
            for (const Json& task : *tasks) {
                if (const Json* id = member(task, "id");
                    id != nullptr && id->is_string() &&
                    id->get<std::string>() == *task_id) {
                    return &task;
                }
            }
        }
        return nullptr;
    }
    return last_of(tasks);
}

void set_active_document(Json& root, const std::string& doc_id) {
    Json* runs = array_member(root, "compilation_runs");
    if (runs == nullptr || runs->empty()) return;
    runs->back()["active_paleomap_document_id"] = doc_id;
}

// --------------------------------- draft ------------------------------------

// _is_demo_draft_doc
bool is_demo_draft_doc(const Json& doc) {
    const Json* vs = member(doc, "view_state");
    if (vs == nullptr) return false;
    const Json* demo = member(*vs, "is_demo_draft");
    const Json* gen = member(*vs, "generator");
    return demo != nullptr && truthy(*demo) && gen != nullptr &&
           gen->is_string() &&
           gen->get<std::string>() == kDemoMapGenerator;
}

// _square_feature — properties/feature/geometry key order verbatim.
Json square_feature(const std::string& facies, double x0, double y0,
                    double side, const Json& probability,
                    const Json& region_id) {
    Json ring = Json::array();
    ring.push_back(Json::array({x0, y0}));
    ring.push_back(Json::array({x0 + side, y0}));
    ring.push_back(Json::array({x0 + side, y0 + side}));
    ring.push_back(Json::array({x0, y0 + side}));
    ring.push_back(Json::array({x0, y0}));

    Json props = Json::object();
    props["name"] = facies;
    props["facies"] = facies;
    props["probability"] = probability;
    props["region_id"] = region_id;

    Json geometry = Json::object();
    geometry["type"] = "Polygon";
    geometry["coordinates"] = Json::array({std::move(ring)});

    Json feature = Json::object();
    feature["type"] = "Feature";
    feature["name"] = facies;
    feature["facies"] = facies;
    feature["properties"] = std::move(props);
    feature["geometry"] = std::move(geometry);
    return feature;
}

// _well_record — dual keys (lng/lat preview + x/y map_edit).
Json well_record(const std::string& name, double lng, double lat) {
    Json w = Json::object();
    w["name"] = name;
    w["lng"] = lng;
    w["lat"] = lat;
    w["x"] = lng;
    w["y"] = lat;
    return w;
}

// _wells_from_factor_tasks / _wells_real_only — identical bodies; the
// only difference is that the draft compiler falls back to synthetic
// placement when this returns empty.
Json wells_from_factor_tasks(const Json& root) {
    Json wells = Json::array();
    std::set<std::string> seen;
    const Json* tasks = array_member(root, "factor_map_tasks");
    if (tasks == nullptr) return wells;
    for (const Json& task : *tasks) {
        const Json* params = member(task, "parameters");
        const Json* points =
            params != nullptr ? member(*params, "sample_points") : nullptr;
        if (points == nullptr || !points->is_array()) continue;
        for (const Json& pt : *points) {
            if (!pt.is_object()) continue;
            const Json* w = member(pt, "well");
            if (w == nullptr || !truthy(*w)) w = member(pt, "name");
            if (w == nullptr || !truthy(*w)) w = member(pt, "well_name");
            const std::string name =
                (w != nullptr && truthy(*w)) ? py_str(*w) : "";
            const Json* jx = member(pt, "x");
            const Json* jy = member(pt, "y");
            std::optional<double> lng;
            std::optional<double> lat;
            if (jx != nullptr && jy != nullptr) {
                lng = py_float(*jx);
                lat = py_float(*jy);
            } else {
                const Json* jl = member(pt, "lng");
                const Json* ja = member(pt, "lat");
                if (jl != nullptr && ja != nullptr) {
                    lng = py_float(*jl);
                    lat = py_float(*ja);
                }
            }
            // One malformed axis poisons the pair in Python too (the try
            // wraps both float() calls).
            if (!lng.has_value() || !lat.has_value()) continue;
            const std::string key = name + ":" +
                                    factor_host::python_repr_double(*lng) +
                                    ":" +
                                    factor_host::python_repr_double(*lat);
            if (!seen.insert(key).second) continue;
            wells.push_back(well_record(name, *lng, *lat));
        }
    }
    return wells;
}

// Draft-only fallback: applicable_wells order, else sorted unique
// well_log resource stems; synthetic 114/22.6 placement. Well names keep
// their raw JSON value (Python never str()s them into the record).
Json wells_fallback(const Json& root) {
    std::vector<Json> names;
    if (const Json* strat = member(root, "stratigraphy")) {
        if (const Json* wells = array_member(*strat, "applicable_wells")) {
            for (const Json& w : *wells) names.push_back(w);
        }
    }
    if (names.empty()) {
        std::set<std::string> stems;
        if (const Json* resources = array_member(root, "resources")) {
            for (const Json& r : *resources) {
                const Json* type = member(r, "type");
                const Json* name = member(r, "name");
                if (type != nullptr && type->is_string() &&
                    type->get<std::string>() == "well_log" &&
                    name != nullptr && truthy(*name)) {
                    stems.insert(path_stem(py_str(*name)));
                }
            }
        }
        for (const std::string& stem : stems) names.push_back(stem);
    }
    Json wells = Json::array();
    int i = 0;
    for (const Json& name : names) {
        Json w = well_record("", py_round6(114.0 + i * 0.02),
                             py_round6(22.6 + (i % 3) * 0.01));
        w["name"] = name;
        wells.push_back(std::move(w));
        ++i;
    }
    return wells;
}

// _unique_facies — first-seen order, properties.facies || properties.name.
Json unique_facies(const Json& features) {
    Json ordered = Json::array();
    std::set<std::string> seen;
    for (const Json& feat : features) {
        const Json* props = member(feat, "properties");
        const Json* f =
            props != nullptr ? member(*props, "facies") : nullptr;
        const Json* n =
            props != nullptr ? member(*props, "name") : nullptr;
        const std::string facies = py_str_or(
            f != nullptr ? *f : Json(), n != nullptr ? *n : Json(), "");
        if (!facies.empty() && seen.insert(facies).second) {
            ordered.push_back(facies);
        }
    }
    return ordered;
}

// PaleoMapDocument dict in models.py declaration order (17 fields).
Json new_paleomap_document(const project::IdFactory& make_id,
                           const std::optional<std::string>& keep_id) {
    Json doc = Json::object();
    doc["id"] = keep_id.has_value() ? *keep_id : make_id("map");
    doc["name"] = nullptr;
    doc["linked_target_horizon"] = nullptr;
    doc["linked_prediction_task_id"] = nullptr;
    doc["linked_contour_draft_id"] = nullptr;
    doc["linked_factor_task_id"] = nullptr;
    doc["facies_polygons"] = Json::array();
    doc["facies_style"] = Json::object();
    doc["well_overlays"] = Json::array();
    doc["line_features"] = Json::array();
    doc["label_features"] = Json::array();
    doc["reference_layers"] = Json::array();
    doc["map_chrome"] = Json::object();
    doc["map_crs"] = nullptr;
    doc["layer_state"] = Json::object();
    doc["view_state"] = Json::object();
    doc["edit_history"] = Json::array();
    return doc;
}

// ------------------------------ production ----------------------------------

// _payload_from_task — minimal payload view over the domain task.
// `dict(task.result_summary or {})`: falsy summaries normalise to {}.
Json payload_from_task(const Json& task) {
    const Json* raw_summary = member(task, "result_summary");
    const Json summary =
        (raw_summary != nullptr && truthy(*raw_summary))
            ? *raw_summary
            : Json::object();
    const Json* model = member(task, "model_metadata");
    const Json* spatial = member(summary, "spatial");
    Json payload = Json::object();
    payload["result_summary"] = summary;
    payload["spatial"] = spatial != nullptr ? *spatial : Json();
    const Json* demo = member(summary, "demo");
    payload["demo"] = demo != nullptr && truthy(*demo);
    payload["model"] = model != nullptr ? *model : Json::object();
    return payload;
}

// _normalize_feature — props.setdefault preserves existing keys.
Json normalize_feature(const Json& feat) {
    const Json* src_props = member(feat, "properties");
    Json props = (src_props != nullptr && src_props->is_object())
                     ? *src_props
                     : Json::object();
    const Json* pf = member(props, "facies");
    const Json* pn = member(props, "name");
    const Json* ff = member(feat, "facies");
    const Json* fn = member(feat, "name");
    std::string facies;
    for (const Json* v : {pf, pn, ff, fn}) {
        if (v != nullptr && truthy(*v)) {
            facies = py_str(*v);
            break;
        }
    }
    if (facies.empty()) facies = "unspecified";
    if (pf == nullptr) props["facies"] = facies;
    if (pn == nullptr) props["name"] = facies;

    // feat["geometry"] — a missing key raises in Python too (KeyError
    // propagates uncaught, deliberately NOT a ProductionMapError).
    const Json* geometry = member(feat, "geometry");
    if (geometry == nullptr) {
        throw std::out_of_range("'geometry'");
    }
    Json out = Json::object();
    out["type"] = "Feature";
    out["name"] = facies;
    out["facies"] = facies;
    out["properties"] = std::move(props);
    out["geometry"] = *geometry;
    return out;
}

}  // namespace

Json compile_map_draft(Json& project_root,
                       const std::optional<std::string>& target_horizon,
                       const std::optional<std::string>& prediction_task_id,
                       int seed, project::IdFactory make_id) {
    const std::string horizon =
        resolve_horizon(project_root, target_horizon, "未指定层位");
    const Json* task =
        resolve_prediction_task(project_root, prediction_task_id);

    // _extract_regions
    Json regions = Json::array();
    if (task != nullptr) {
        const Json* summary = member(*task, "result_summary");
        const Json* raw =
            summary != nullptr ? member(*summary, "predicted_regions")
                               : nullptr;
        if (raw != nullptr && raw->is_array()) {
            for (const Json& r : *raw) {
                if (r.is_object()) regions.push_back(r);
            }
        }
    }

    // _polygons_from_regions — Python % semantics on negative seeds.
    const int mod = ((seed % 10) + 10) % 10;
    const double base_x = 114.0 + mod * 0.001;
    Json facies_polygons = Json::array();
    if (regions.empty()) {
        facies_polygons.push_back(square_feature("未分类", base_x, kBaseY,
                                                 kSide, Json(), Json()));
    } else {
        int i = 0;
        for (const Json& region : regions) {
            const Json* f = member(region, "facies");
            const std::string facies =
                py_str_or(f != nullptr ? *f : Json(), "未分类");
            // region.get(...) verbatim — falsy values (0 / null) keep
            // their value, no `or` collapse.
            const Json* prob = member(region, "probability");
            const Json* rid = member(region, "region_id");
            facies_polygons.push_back(square_feature(
                facies, base_x + (i % kCols) * kCell,
                kBaseY + (i / kCols) * kCell, kSide,
                prob != nullptr ? *prob : Json(),
                rid != nullptr ? *rid : Json()));
            ++i;
        }
    }

    Json well_overlays = wells_from_factor_tasks(project_root);
    if (well_overlays.empty()) well_overlays = wells_fallback(project_root);
    Json legend_facies = unique_facies(facies_polygons);

    const std::string name = horizon + " 相带草稿";

    // _demo_draft_indices
    Json* docs = array_member(project_root, "paleomap_documents");
    if (docs == nullptr) {
        project_root["paleomap_documents"] = Json::array();
        docs = &project_root["paleomap_documents"];
    }
    std::vector<std::size_t> demo_indices;
    for (std::size_t i = 0; i < docs->size(); ++i) {
        if (is_demo_draft_doc((*docs)[i])) demo_indices.push_back(i);
    }

    std::optional<std::string> keep_id;
    Json keep_layers = Json::array();
    if (!demo_indices.empty()) {
        const Json& first = (*docs)[demo_indices.front()];
        if (const Json* id = member(first, "id");
            id != nullptr && id->is_string()) {
            keep_id = id->get<std::string>();
        }
        if (const Json* layers = member(first, "reference_layers");
            layers != nullptr && layers->is_array()) {
            keep_layers = *layers;
        }
    }

    Json doc = new_paleomap_document(make_id, keep_id);
    doc["name"] = name;
    doc["linked_target_horizon"] = horizon;
    // task.id verbatim (a falsy id stays falsy — Python field copy, no
    // `or` guard).
    const Json* task_id_v =
        task != nullptr ? member(*task, "id") : nullptr;
    doc["linked_prediction_task_id"] =
        task_id_v != nullptr ? *task_id_v : Json();
    doc["facies_polygons"] = std::move(facies_polygons);
    doc["well_overlays"] = std::move(well_overlays);
    doc["map_chrome"] =
        Json::object({{"title", name}, {"legend_facies", legend_facies}});
    doc["view_state"] = Json::object({{"generator", kDemoMapGenerator},
                                      {"is_demo_draft", true},
                                      {"seed", seed}});
    doc["reference_layers"] = std::move(keep_layers);

    if (!demo_indices.empty()) {
        (*docs)[demo_indices.front()] = doc;
        // Drop duplicate demos (legacy appends), highest index first.
        for (std::size_t k = demo_indices.size(); k-- > 1;) {
            docs->erase(docs->begin() +
                        static_cast<std::ptrdiff_t>(demo_indices[k]));
        }
    } else {
        docs->push_back(doc);
    }

    set_active_document(project_root, doc["id"].get<std::string>());
    return doc;
}

Json compile_map_production(Json& project_root,
                            const ProductionMapCompileOptions& options) {
    const Json* task =
        resolve_prediction_task(project_root, options.prediction_task_id);
    Json owned_payload;
    const Json* payload = options.prediction_payload;
    if (payload == nullptr) {
        if (task == nullptr) {
            throw ProductionMapError("无预测任务，无法进行生产编图");
        }
        owned_payload = payload_from_task(*task);
        payload = &owned_payload;
    }

    const Json summary = get_or(*payload, "result_summary", Json::object());
    const Json* model = member(*payload, "model");
    const Json model_obj =
        (model != nullptr && model->is_object()) ? *model : Json::object();

    const bool demo_marked =
        truthy(get_or(summary, "demo")) ||
        truthy(get_or(summary, "is_mock")) ||
        truthy(get_or(*payload, "demo")) ||
        truthy(get_or(model_obj, "demo_only"));
    if (demo_marked && !options.allow_demo_task) {
        throw ProductionMapError(
            "演示/mock 预测结果不能用于生产古地理编图；请使用「生成演示草稿」"
            );
    }
    // `is False` parity — strict boolean false, not falsy.
    const Json* fsp = member(summary, "final_scientific_prediction");
    const bool fsp_false =
        fsp != nullptr && fsp->is_boolean() && !fsp->get<bool>();
    if (fsp_false && !options.allow_demo_task &&
        !truthy(get_or(summary, "allow_map_compile"))) {
        throw ProductionMapError(
            "非科学预测结果（final_scientific_prediction=False）不能用于生产"
            "编图");
    }

    const Json validation_errors = prediction::validate_spatial_result(
        *payload, Json(), !truthy(get_or(summary, "allow_map_compile")));
    if (validation_errors.is_array() && !validation_errors.empty()) {
        std::string msg = "预测几何未通过生产校验: ";
        bool first = true;
        for (const Json& err : validation_errors) {
            if (!first) msg += "; ";
            msg += err.is_string() ? err.get<std::string>() : err.dump();
            first = false;
        }
        throw ProductionMapError(msg);
    }

    // Model trust (D-P2): a declared version must resolve to a promoted
    // production version when a trust catalog is reachable.
    const std::string declared_mv_id = [&] {
        const Json* a = member(model_obj, "model_version_id");
        const Json* b = member(model_obj, "version_id");
        std::string s = py_str_or(a != nullptr ? *a : Json(),
                                  b != nullptr ? *b : Json(), "");
        const auto ws = [](char c) {
            return c == ' ' || c == '\t' || c == '\n' || c == '\r' ||
                   c == '\v' || c == '\f';
        };
        std::size_t lo = 0, hi = s.size();
        while (lo < hi && ws(s[lo])) ++lo;
        while (hi > lo && ws(s[hi - 1])) --hi;
        return s.substr(lo, hi - lo);
    }();
    if (!declared_mv_id.empty() && options.catalog != nullptr) {
        if (!options.model_version_resolver) {
            throw ProductionMapError(
                "声明了模型版本但无法验证其生产状态");
        }
        std::optional<ModelVersionTrust> declared;
        try {
            declared = options.model_version_resolver(declared_mv_id);
        } catch (const std::exception& exc) {
            throw ProductionMapError("声明的模型版本不存在: " +
                                     declared_mv_id + " (" + exc.what() +
                                     ")");
        }
        if (!declared.has_value()) {
            throw ProductionMapError("声明的模型版本不存在: " +
                                     declared_mv_id + " ()");
        }
        if (declared->status != "production" || declared->demo_only) {
            throw ProductionMapError(
                "声明的模型版本未处于生产状态，不能用于生产编图");
        }
    }

    if (prediction::spatial_type_of(*payload) == "WELL_INTERVALS") {
        throw ProductionMapError(
            "井深区间预测（WELL_INTERVALS）不能直接编绘平面古地理图；"
            "需要平面空间几何或分类栅格");
    }
    if (!prediction::is_map_compilable(*payload)) {
        throw ProductionMapError(
            "预测结果缺少可编绘的平面多边形几何（VECTOR_POLYGONS）；"
            "不会生成占位方块或「未分类」假几何");
    }

    Json features = Json::array();
    for (const Json& feat : prediction::extract_polygon_features(*payload)) {
        features.push_back(normalize_feature(feat));
    }
    if (features.empty()) {
        throw ProductionMapError("空间特征列表为空");
    }

    const std::string horizon =
        resolve_horizon(project_root, options.target_horizon, "");
    if (horizon.empty()) {
        throw ProductionMapError("生产编图需要明确的目标层位");
    }

    const Json* spatial = member(summary, "spatial");
    if (spatial == nullptr || !truthy(*spatial)) {
        spatial = member(*payload, "spatial");
    }
    std::string crs;
    if (options.map_crs.has_value() && !options.map_crs->empty()) {
        crs = *options.map_crs;
    } else if (const Json* sc =
                   spatial != nullptr ? member(*spatial, "crs") : nullptr;
               sc != nullptr && truthy(*sc)) {
        crs = py_str(*sc);
    } else if (const Json* coord = member(project_root, "coordinate");
               coord != nullptr) {
        if (const Json* pc = member(*coord, "project_crs");
            pc != nullptr && truthy(*pc)) {
            crs = py_str(*pc);
        }
    }

    const std::string name = horizon + " 相带图";
    Json legend = Json::array();
    {
        std::set<std::string> seen;
        for (const Json& feat : features) {
            const Json* f = member(feat, "facies");
            const std::string s =
                py_str_or(f != nullptr ? *f : Json(), "");
            if (!s.empty() && seen.insert(s).second) legend.push_back(s);
        }
    }

    const Json well_overlays = wells_from_factor_tasks(project_root);

    // linked-task eligibility: `is not None` parity — an explicit (even
    // empty) task id counts; a caller-supplied payload with only default
    // task resolution does NOT link.
    const Json* linked_task =
        (options.prediction_task_id.has_value() ||
         options.prediction_payload == nullptr)
            ? task
            : nullptr;

    Json doc = new_paleomap_document(options.make_id, std::nullopt);
    doc["name"] = name;
    doc["linked_target_horizon"] = horizon;
    const Json* linked_id_v =
        linked_task != nullptr ? member(*linked_task, "id") : nullptr;
    doc["linked_prediction_task_id"] =
        linked_id_v != nullptr ? *linked_id_v : Json();
    doc["facies_polygons"] = features;
    doc["well_overlays"] = well_overlays;
    doc["map_chrome"] =
        Json::object({{"title", name}, {"legend_facies", legend}});
    doc["map_crs"] = crs;
    doc["view_state"] = Json::object(
        {{"generator", kProductionMapGenerator},
         {"is_demo_draft", demo_marked},
         {"spatial_output_type",
          std::string(prediction::kSpatialVectorPolygons)},
         {"production", false}});

    Json* docs = array_member(project_root, "paleomap_documents");
    if (docs == nullptr) {
        project_root["paleomap_documents"] = Json::array();
        docs = &project_root["paleomap_documents"];
    }
    auto commit = [&] {
        docs->push_back(doc);
        set_active_document(project_root, doc["id"].get<std::string>());
    };

    if (demo_marked || options.catalog == nullptr) {
        // Explicit demo path / no-catalog degrade: never pretend
        // provenance is complete (H3) — but the document still appends.
        doc["view_state"]["production"] = false;
        doc["view_state"]["lineage"] = "untracked";
        commit();
        return doc;
    }

    // Freeze the FINAL document state FIRST so the registered payload
    // carries production:true (issue #393 / C30 ordering).
    doc["view_state"]["production"] = true;
    doc["view_state"]["lineage"] = "registered";

    // _register_lineage — path-1 primitives; every CatalogRepository
    // implements register_run/register_result_asset/update_run_status.
    // _register_lineage receives task=linked_task — an explicit payload
    // with only default task resolution resolves NO inputs (verified in
    // the Python source and frozen by the oracle).
    std::vector<std::string> input_ids;
    if (options.prediction_version_id.has_value() &&
        !options.prediction_version_id->empty()) {
        input_ids.push_back(*options.prediction_version_id);
    } else if (linked_task != nullptr) {
        const Json* id = member(*linked_task, "id");
        if (id != nullptr && id->is_string()) {
            // _resolve_map_input_ids wraps resolution in
            // `except Exception: return []` — the helper propagates.
            try {
                input_ids = workflow_runtime::versions_for_domain_tasks(
                    {id->get<std::string>()}, *options.catalog);
            } catch (...) {
                input_ids = {};
            }
        }
    }
    if (input_ids.empty()) {
        throw ProductionMapError(
            "生产编图需要可解析的预测结果版本（未找到 lineage 输入）");
    }

    Json params = Json::object();
    params["generator_version"] = kProductionMapGenerator;
    params["target_horizon"] = horizon;
    params["linked_prediction_task_id"] =
        doc["linked_prediction_task_id"];
    params["_domain_task_id"] = doc["id"];
    // [task.id] where _register_lineage's `task` param IS linked_task.
    const Json* task_id_p =
        linked_task != nullptr ? member(*linked_task, "id") : nullptr;
    params["source_task_ids"] =
        task_id_p != nullptr ? Json::array({*task_id_p}) : Json::array();

    Json payload_record = Json::object();
    payload_record["id"] = doc["id"];
    payload_record["name"] = doc["name"];
    payload_record["linked_target_horizon"] =
        doc["linked_target_horizon"];
    payload_record["linked_prediction_task_id"] =
        doc["linked_prediction_task_id"];
    payload_record["facies_polygons"] = doc["facies_polygons"];
    payload_record["map_crs"] = doc["map_crs"];
    payload_record["view_state"] = doc["view_state"];

    // json.dump(payload, handle, ensure_ascii=False) byte parity — the
    // staged payload file is a catalog artifact; byte-identical output
    // keeps Python-written and C++-written versions indistinguishable.
    const std::string payload_json = python_dumps(payload_record);
    std::string run_id;
    try {
        run_id = options.catalog->register_run(
            "map_compile", input_ids, params,
            std::string(kProductionMapGenerator), "running");
        const auto out = options.catalog->register_result_asset(
            name, "paleomap", "json",
            Json::object({{"kind", "paleomap"}, {"production", true}}),
            payload_json, "derived", run_id,
            Json::object({{"kind", "paleomap"},
                          {"generator", kProductionMapGenerator},
                          {"production", true}}));
        options.catalog->update_run_status(
            run_id, "complete",
            Json::object({{"output_version_id", out.version_id}}));
    } catch (const std::exception& exc) {
        if (!run_id.empty()) {
            try {
                options.catalog->update_run_status(
                    run_id, "failed",
                    Json::object(
                        {{"error", std::string("std::exception: ") +
                                       exc.what()}}));
            } catch (...) {
            }
        }
        throw ProductionMapError(
            std::string("目录 lineage 登记失败（生产编图已中止）: ") +
            exc.what());
    }

    commit();
    return doc;
}

}  // namespace pwb::closure_workflow
