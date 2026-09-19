// map_qa_rules.cpp — C++ port of paleo_workbench/workflow/map_qa_rules.py
// (CONV-33, route A1). Line anchors refer to the frozen Python source:
//   _layer_crs_issues        L56   CRS discipline (D5)
//   _renderer_class_issues   L95   categorized styles must cover the values
//                                  present; missing list renders with the
//                                  Python list repr (['a', 'b'])
//   _extent_issues           L164  explicit map_extent or view_state.extent;
//                                  absent -> check skipped, not guessed
//   _feature_field / _flatten_coords L237/L244
//   _data_health_issues      L258  empty well tables / stale factor tasks /
//                                  broken interpretation refs
//   _confidence_issues       L310  fusion confidence below threshold
//   _export_issues           L338  export honesty (D2 fallback renderer)
//   collect_extended_qc_issues L355
//   extended_rule_coverage   L376  V8 M11 honest skip reasons (verbatim)
//   composition_qa_issues    L416  three required furniture types
//   cartographic_issues      L446  thin delegate (D7 — no rule duplication)
#include "pwb/workflow_runtime/map_qa_rules.hpp"

#include "python_compat.hpp"

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_runtime {
namespace {

using domain::Json;

// ------------------------------------------------------- json micro-helpers
// (mirrors the qc.cpp set; kept file-local on purpose — both TUs compile
// standalone and the helpers are tuned to each module's access patterns)

const Json* member(const Json& obj, const char* key) {
    if (!obj.is_object()) {
        return nullptr;
    }
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null()) {
        return nullptr;
    }
    return &*it;
}

const Json* array_member(const Json& obj, const char* key) {
    const Json* value = member(obj, key);
    if (value == nullptr || !value->is_array()) {
        return nullptr;
    }
    return value;
}

std::string truthy_str(const Json& obj, const char* key,
                       const std::string& fallback = {}) {
    const Json* value = member(obj, key);
    if (value != nullptr && pycompat::truthy(*value)) {
        return pycompat::str_scalar(*value);
    }
    return fallback;
}

std::string str_field(const Json& obj, const char* key) {
    const Json* value = member(obj, key);
    if (value != nullptr && value->is_string()) {
        return value->get<std::string>();
    }
    return {};
}

bool parse_float_like(const Json& value, double& out) {
    if (value.is_number()) {
        out = value.get<double>();
        return true;
    }
    if (value.is_boolean()) {
        out = value.get<bool>() ? 1.0 : 0.0;
        return true;
    }
    if (value.is_string()) {
        const std::string& text = value.get_ref<const std::string&>();
        char* end = nullptr;
        const double parsed = std::strtod(text.c_str(), &end);
        if (end != nullptr && end != text.c_str() && *end == '\0' &&
            text.find_first_of(" \t\n\r\f\v") == std::string::npos) {
            out = parsed;
            return true;
        }
        return false;
    }
    return false;
}

std::string fmt2(double value) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.2f", value);
    return std::string(buf);
}

// Python repr() of a list[str] — the `{missing}` slot of the
// class_renderer_mismatch message renders "['三角洲', '河流']" verbatim.
std::string repr_string_list(const std::vector<std::string>& values) {
    std::string out = "[";
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i != 0) {
            out += ", ";
        }
        out += pycompat::repr_str(values[i]);
    }
    out += "]";
    return out;
}

// ------------------------------------------------------ _layer_crs (L56) --

Json layer_crs_issues(const Json& project, const Json& document) {
    Json issues = Json::array();
    const std::string document_id = str_field(document, "id");
    const std::string map_crs = truthy_str(document, "map_crs");
    if (map_crs.empty()) {
        QcIssueFields fields;
        fields.ref = document_id;
        issues.push_back(
            make_issue("crs_undeclared", "warning",
                       "图面未声明 CRS——按契约这是合法但需显式确认的状态",
                       fields));
    }
    const Json* layers = array_member(project, "user_vector_layers");
    if (layers == nullptr) {
        return issues;
    }
    for (const Json& layer : *layers) {
        if (!layer.is_object()) {
            continue;
        }
        const std::string layer_crs = truthy_str(layer, "crs");
        const std::string layer_name = str_field(layer, "name");
        const std::string layer_id = str_field(layer, "id");
        if (layer_crs.empty()) {
            QcIssueFields fields;
            fields.feature_kind = "layer";
            fields.ref = layer_id;
            issues.push_back(make_issue(
                "crs_undeclared", "warning",
                "图层 " + layer_name + " 未声明 CRS", fields));
        } else if (!map_crs.empty() && layer_crs != map_crs) {
            QcIssueFields fields;
            fields.feature_kind = "layer";
            fields.ref = layer_id;
            issues.push_back(make_issue(
                "crs_mismatch", "error",
                "图层 " + layer_name + " CRS " + layer_crs + " 与图面 CRS " +
                    map_crs + " 不一致",
                fields));
        }
    }
    return issues;
}

// ---------------------------------------------- _renderer_class (L95) -----

void check_categorized_style(const Json& style, const Json& features,
                             const std::string& field,
                             const std::string& label, const std::string& ref,
                             const std::string& kind, Json& issues) {
    if (!style.is_object()) {
        return;
    }
    const auto renderer = style.find("renderer");
    if (renderer == style.end() || !renderer->is_string() ||
        renderer->get<std::string>() != "categorized") {
        return;
    }
    // field_name = str(style.get("field") or field)
    std::string field_name = field;
    const auto field_json = style.find("field");
    if (field_json != style.end() && pycompat::truthy(*field_json)) {
        field_name = pycompat::str_scalar(*field_json);
    }
    if (field_name.empty()) {
        return;
    }
    std::set<std::string> categories;
    const auto categories_json = style.find("categories");
    if (categories_json != style.end() &&
        pycompat::truthy(*categories_json)) {
        if (categories_json->is_object()) {
            for (auto it = categories_json->begin();
                 it != categories_json->end(); ++it) {
                categories.insert(it.key());
            }
        } else if (categories_json->is_array()) {
            for (const Json& category : *categories_json) {
                if (!pycompat::truthy(category)) {
                    continue;
                }
                if (category.is_array() && !category.empty()) {
                    categories.insert(
                        pycompat::str_scalar(category.front()));
                } else if (category.is_string()) {
                    const std::string& text =
                        category.get_ref<const std::string&>();
                    if (!text.empty()) {
                        categories.insert(text.substr(0, 1));
                    }
                }
                // Other truthy scalars: Python c[0] raises TypeError — this
                // port skips them instead (documented divergence, host data
                // never shapes categories as bare numbers).
            }
        }
    }
    std::set<std::string> present;
    if (features.is_array()) {
        for (const Json& feature : features) {
            if (!feature.is_object()) {
                continue;
            }
            const Json* props = member(feature, "properties");
            if (props == nullptr || !props->is_object()) {
                continue;  // `props.get(...) if isinstance(props, Mapping)`
            }
            const auto value = props->find(field_name);
            if (value == props->end() || value->is_null()) {
                continue;  // `value is not None`
            }
            present.insert(pycompat::str_scalar(*value));
        }
    }
    std::vector<std::string> missing;
    for (const std::string& value : present) {
        if (categories.count(value) == 0) {
            missing.push_back(value);
        }
    }
    if (missing.empty()) {
        return;
    }
    Json extra = Json::object();
    extra["missing_classes"] = missing;
    extra["field"] = field_name;
    QcIssueFields fields;
    fields.feature_kind = kind;
    fields.ref = ref;
    fields.extra = std::move(extra);
    issues.push_back(make_issue(
        "class_renderer_mismatch", "warning",
        label + "分类样式缺少字段 " + field_name + " 的值 " +
            repr_string_list(missing) + "（" +
            std::to_string(missing.size()) + " 项无法按样式呈现）",
        fields));
}

Json renderer_class_issues(const Json& project, const Json& document) {
    Json issues = Json::array();
    const std::string document_id = str_field(document, "id");

    const Json* layers = array_member(project, "user_vector_layers");
    if (layers != nullptr) {
        for (const Json& layer : *layers) {
            if (!layer.is_object()) {
                continue;
            }
            const Json* style = member(layer, "style");
            Json features = Json::array();
            if (const Json* feat = array_member(layer, "features")) {
                features = *feat;
            }
            check_categorized_style(
                style != nullptr ? *style : Json(nullptr), features, "",
                "图层 " + str_field(layer, "name") + " ",
                str_field(layer, "id"), "layer", issues);
        }
    }

    Json facies_features = Json::array();
    if (const Json* facies = array_member(document, "facies_polygons")) {
        for (const Json& poly : *facies) {
            if (!poly.is_object()) {
                continue;  // isinstance(p, Mapping)
            }
            Json properties;
            const auto props = poly.find("properties");
            if (props != poly.end() && pycompat::truthy(*props)) {
                properties = *props;
            } else {
                Json fallback = Json::object();
                const auto facies_name = poly.find("facies_name");
                fallback["facies_name"] =
                    facies_name != poly.end() ? *facies_name : Json(nullptr);
                properties = std::move(fallback);
            }
            facies_features.push_back(Json{{"properties", properties}});
        }
    }
    const Json* facies_style = member(document, "facies_style");
    check_categorized_style(
        facies_style != nullptr ? *facies_style : Json(nullptr),
        facies_features, "facies_name", "相带面 ", document_id, "facies",
        issues);
    return issues;
}

// --------------------------------------------------- _extent_issues (L164)

// _flatten_coords (L244): an all-number array of length >= 2 is one point
// (its first two values); anything else recurses into the children.
void flatten_coords(const Json& coords,
                    std::vector<std::pair<double, double>>& out) {
    if (!coords.is_array()) {
        return;
    }
    bool all_numbers = coords.size() >= 2;
    if (all_numbers) {
        for (const Json& value : coords) {
            if (!value.is_number() && !value.is_boolean()) {
                all_numbers = false;
                break;
            }
        }
    }
    if (all_numbers) {
        const Json& first = coords[0];
        const Json& second = coords[1];
        out.emplace_back(first.is_boolean()
                             ? (first.get<bool>() ? 1.0 : 0.0)
                             : first.get<double>(),
                         second.is_boolean()
                             ? (second.get<bool>() ? 1.0 : 0.0)
                             : second.get<double>());
        return;
    }
    for (const Json& item : coords) {
        flatten_coords(item, out);
    }
}

Json extent_issues(const Json& project, const Json& document,
                   const MapQcInputs& inputs) {
    Json issues = Json::array();
    std::optional<std::array<double, 4>> extent;
    if (inputs.map_extent.has_value()) {
        extent = inputs.map_extent;
    } else {
        const auto view_state = document.find("view_state");
        if (view_state != document.end() && view_state->is_object()) {
            const auto extent_json = view_state->find("extent");
            if (extent_json != view_state->end() &&
                extent_json->is_array() && extent_json->size() == 4) {
                std::array<double, 4> bounds{};
                bool ok = true;
                for (std::size_t i = 0; i < 4; ++i) {
                    if (!parse_float_like((*extent_json)[i], bounds[i])) {
                        ok = false;
                        break;
                    }
                }
                if (!ok) {
                    // Python float(v) raises here and the whole QC run
                    // fails; the port raises too instead of guessing.
                    throw std::invalid_argument(
                        "could not convert extent value to float");
                }
                extent = bounds;
            }
        }
    }
    if (!extent.has_value()) {
        return issues;
    }
    const double xmin = (*extent)[0];
    const double ymin = (*extent)[1];
    const double xmax = (*extent)[2];
    const double ymax = (*extent)[3];

    auto out_of_bounds = [xmin, ymin, xmax, ymax](double x, double y) {
        return x < xmin || x > xmax || y < ymin || y > ymax;
    };

    const Json* layers = array_member(project, "user_vector_layers");
    if (layers != nullptr) {
        for (const Json& layer : *layers) {
            if (!layer.is_object()) {
                continue;
            }
            const Json* features = array_member(layer, "features");
            if (features == nullptr) {
                continue;
            }
            const std::string layer_id = str_field(layer, "id");
            for (const Json& feature : *features) {
                if (!feature.is_object()) {
                    continue;
                }
                Json geometry = Json::object();  // `_feature_field(...) or {}`
                if (const Json* geom = member(feature, "geometry");
                    geom != nullptr && geom->is_object()) {
                    geometry = *geom;
                }
                std::vector<std::pair<double, double>> flat;
                if (const Json* coords = member(geometry, "coordinates");
                    coords != nullptr) {
                    flatten_coords(*coords, flat);
                }
                for (const auto& [x, y] : flat) {
                    if (out_of_bounds(x, y)) {
                        QcIssueFields fields;
                        fields.feature_id = truthy_str(feature, "id");
                        fields.feature_kind = "layer";
                        fields.ref = layer_id;
                        fields.geometry = geometry;
                        issues.push_back(make_issue(
                            "out_of_bound_feature", "warning",
                            "要素坐标 (" + fmt2(x) + ", " + fmt2(y) +
                                ") 超出图面范围",
                            fields));
                        break;  // one issue per feature is enough
                    }
                }
            }
        }
    }

    struct Payload {
        const char* kind;
        const char* key;
    };
    for (const Payload& payload :
         {Payload{"facies", "facies_polygons"},
          Payload{"line", "line_features"}}) {
        const Json* items = array_member(document, payload.key);
        if (items == nullptr) {
            continue;
        }
        const std::string document_id = str_field(document, "id");
        for (std::size_t index = 0; index < items->size(); ++index) {
            const Json& feature = (*items)[index];
            Json geometry = Json::object();  // `(feature or {}).get(...) or {}`
            if (feature.is_object()) {
                if (const Json* geom = member(feature, "geometry");
                    geom != nullptr && geom->is_object()) {
                    geometry = *geom;
                }
            }
            const Json* coordinates = member(geometry, "coordinates");
            if (coordinates == nullptr || !pycompat::truthy(*coordinates)) {
                continue;  // `if not coordinates: continue`
            }
            std::vector<std::pair<double, double>> flat;
            flatten_coords(*coordinates, flat);
            for (const auto& [x, y] : flat) {
                if (out_of_bounds(x, y)) {
                    std::string feature_id =
                        truthy_str(feature, "feature_id",
                                   truthy_str(feature, "id",
                                              std::string(payload.kind) +
                                                  "_" +
                                                  std::to_string(index)));
                    QcIssueFields fields;
                    fields.feature_id = feature_id;
                    fields.feature_kind = payload.kind;
                    fields.ref = document_id;
                    fields.geometry = geometry;
                    issues.push_back(make_issue(
                        "out_of_bound_feature", "warning",
                        "要素坐标 (" + fmt2(x) + ", " + fmt2(y) +
                            ") 超出图面范围",
                        fields));
                    break;
                }
            }
        }
    }
    return issues;
}

// ---------------------------------------------- _data_health_issues (L258)

Json data_health_issues(const Json& project) {
    Json issues = Json::array();

    std::map<std::string, const Json*> tables;
    if (const Json* well_tables = array_member(project, "well_tables")) {
        for (const Json& table : *well_tables) {
            if (!table.is_object()) {
                continue;
            }
            tables[truthy_str(table, "id")] = &table;
        }
    }

    if (const Json* tasks = array_member(project, "factor_map_tasks")) {
        for (const Json& task : *tasks) {
            if (!task.is_object()) {
                continue;
            }
            const std::string task_id = str_field(task, "id");
            const std::string table_id = truthy_str(task, "well_table_id");
            if (!table_id.empty()) {
                const auto table = tables.find(table_id);
                if (table != tables.end()) {
                    const Json* rows = array_member(*table->second, "rows");
                    if (rows == nullptr || rows->empty()) {
                        QcIssueFields fields;
                        fields.ref = task_id;
                        issues.push_back(make_issue(
                            "well_table_empty", "warning",
                            "因子 " + str_field(task, "factor_type") +
                                " 引用的井表 " + table_id + " 无数据行",
                            fields));
                    }
                }
            }
            const Json* grid = member(task, "grid_artifact_version_id");
            const bool has_grid = grid != nullptr && pycompat::truthy(*grid);
            if (str_field(task, "status") == "complete" && !has_grid) {
                QcIssueFields fields;
                fields.ref = task_id;
                issues.push_back(
                    make_issue("stale_inputs", "warning",
                               "因子任务 " + str_field(task, "name") +
                                   " 已完成但无持久化栅格版本（重算后未保存？）",
                               fields));
            }
        }
    }

    std::set<std::string> known_refs;
    for (const char* kind : {"horizon_interpretations",
                             "correlation_interpretations",
                             "fault_interpretations"}) {
        if (const Json* refs = array_member(project, kind)) {
            for (const Json& ref : *refs) {
                if (!ref.is_object()) {
                    continue;
                }
                known_refs.insert(truthy_str(ref, "id"));
            }
        }
    }

    if (const Json* products = array_member(project, "map_products")) {
        for (const Json& record : *products) {
            if (!record.is_object()) {
                continue;
            }
            const Json* refs = array_member(record, "interpretation_refs");
            if (refs == nullptr) {
                continue;
            }
            const std::string product_name =
                str_field(record, "product_name");
            for (const Json& ref_id : *refs) {
                const std::string ref_text = pycompat::str_scalar(ref_id);
                if (known_refs.count(ref_text) != 0) {
                    continue;
                }
                Json extra = Json::object();
                extra["product"] = product_name;
                QcIssueFields fields;
                fields.feature_kind = "interpretation";
                fields.ref = ref_text;
                fields.extra = std::move(extra);
                issues.push_back(make_issue(
                    "broken_external_reference", "error",
                    "产品 " + product_name + " 引用的解释 " + ref_text +
                        " 不存在",
                    fields));
            }
        }
    }
    return issues;
}

// ---------------------------------------------- _confidence_issues (L310) -

Json confidence_issues(const Json& confidence_stats, double threshold) {
    Json issues = Json::array();
    if (confidence_stats.is_null() || !pycompat::truthy(confidence_stats)) {
        return issues;
    }
    if (!confidence_stats.is_object()) {
        return issues;  // Python .get on a non-mapping raises; host data
                        // shapes confidence as an object
    }
    const Json* minimum = member(confidence_stats, "min");
    if (minimum == nullptr || !(minimum->is_number() ||
                                minimum->is_boolean())) {
        return issues;  // isinstance(minimum, (int, float))
    }
    const double min_value = minimum->is_boolean()
                                 ? (minimum->get<bool>() ? 1.0 : 0.0)
                                 : minimum->get<double>();
    if (!(min_value < threshold)) {
        return issues;
    }
    Json extra = Json::object();
    extra["confidence_min"] = min_value;
    const auto mean = confidence_stats.find("mean");
    extra["confidence_mean"] =
        mean != confidence_stats.end() ? *mean : Json(nullptr);
    extra["threshold"] = threshold;
    QcIssueFields fields;
    fields.extra = std::move(extra);
    issues.push_back(make_issue(
        "low_confidence", "warning",
        "融合最小置信度 " + fmt2(min_value) + " 低于阈值 " + fmt2(threshold),
        fields));
    return issues;
}

// -------------------------------------------------- _export_issues (L338) -

Json export_issues(const Json& export_report) {
    Json issues = Json::array();
    if (export_report.is_null() || !pycompat::truthy(export_report)) {
        return issues;
    }
    const std::string engine = truthy_str(export_report, "engine");
    const Json* degraded = member(export_report, "degraded");
    const bool degraded_flag =
        degraded != nullptr && pycompat::truthy(*degraded);
    if (engine != "fallback" && engine != "composer_fallback" &&
        !degraded_flag) {
        return issues;
    }
    std::string reason =
        truthy_str(export_report, "degraded_reason", "未说明");
    Json extra = Json::object();
    extra["degraded_reason"] = reason;
    QcIssueFields fields;
    fields.extra = std::move(extra);
    issues.push_back(make_issue(
        "export_fallback", "warning",
        "成图导出使用了回退渲染器（" + reason +
            "）——与屏显可能存在符号差异",
        fields));
    return issues;
}

}  // namespace

// ------------------------------------------- collect_extended_qc_issues ----

domain::Json collect_extended_qc_issues(const domain::Json& project,
                                        const domain::Json& document,
                                        const MapQcInputs& inputs) {
    Json issues = Json::array();
    for (const Json& issue : layer_crs_issues(project, document)) {
        issues.push_back(issue);
    }
    for (const Json& issue : renderer_class_issues(project, document)) {
        issues.push_back(issue);
    }
    for (const Json& issue : extent_issues(project, document, inputs)) {
        issues.push_back(issue);
    }
    for (const Json& issue : data_health_issues(project)) {
        issues.push_back(issue);
    }
    for (const Json& issue :
         confidence_issues(inputs.fusion_confidence,
                           inputs.confidence_threshold)) {
        issues.push_back(issue);
    }
    for (const Json& issue : export_issues(inputs.export_report)) {
        issues.push_back(issue);
    }
    return issues;
}

// ------------------------------------------------ extended_rule_coverage --

domain::Json extended_rule_coverage(const MapQcInputs& inputs) {
    Json coverage = Json::object();
    for (const char* rule : {"crs_undeclared", "crs_mismatch",
                             "class_renderer_mismatch", "well_table_empty",
                             "stale_inputs", "broken_external_reference"}) {
        coverage[rule] = Json{{"evaluated", true}, {"reason", ""}};
    }
    coverage["out_of_bound_feature"] =
        inputs.map_extent.has_value()
            ? Json{{"evaluated", true}, {"reason", ""}}
            : Json{{"evaluated", false},
                   {"reason", "未提供图幅范围（map_extent）"}};
    coverage["low_confidence"] =
        !inputs.fusion_confidence.is_null()
            ? Json{{"evaluated", true}, {"reason", ""}}
            : Json{{"evaluated", false},
                   {"reason", "未提供融合置信度数据"}};
    coverage["export_fallback"] =
        !inputs.export_report.is_null()
            ? Json{{"evaluated", true}, {"reason", ""}}
            : Json{{"evaluated", false},
                   {"reason", "尚未执行导出（无导出报告）"}};
    return coverage;
}

// ------------------------------------------------ composition_qa_issues ---

domain::Json composition_qa_issues(const domain::Json& composition) {
    Json issues = Json::array();
    std::vector<std::string> types;
    if (composition.is_object()) {
        if (const Json* elements = array_member(composition, "elements")) {
            for (const Json& element : *elements) {
                if (!element.is_object()) {
                    continue;
                }
                bool visible = true;  // ComposerElement.visible default
                if (const Json* flag = member(element, "visible");
                    flag != nullptr) {
                    visible = pycompat::truthy(*flag);
                }
                if (!visible) {
                    continue;
                }
                if (const Json* type = member(element, "element_type");
                    type != nullptr) {
                    types.push_back(pycompat::str_scalar(*type));
                }
            }
        }
    }
    const std::string ref = composition.is_object()
                                ? truthy_str(composition, "id")
                                : std::string();
    const std::pair<const char*, const char*> required[] = {
        {"main_map", "图面主图"},
        {"legend", "图例"},
        {"scale_bar", "比例尺"},
    };
    for (const auto& [type_value, label] : required) {
        if (std::find(types.begin(), types.end(), std::string(type_value)) ==
            types.end()) {
            QcIssueFields fields;
            fields.ref = ref;
            issues.push_back(make_issue(
                "composition_incomplete", "warning",
                std::string("合成页缺少") + label + "组件", fields));
        }
    }
    return issues;
}

// -------------------------------------------------- cartographic_issues ---
// Thin delegate (D7): the §14 rule set lives behind CartographicQaDelegate;
// this module never restates CARTOGRAPHIC_QA_RULES.

domain::Json cartographic_issues(const domain::Json& project,
                                 const CartographicQaInputs& inputs,
                                 const CartographicQaDelegate& delegate) {
    return delegate(project, inputs);
}

}  // namespace pwb::workflow_runtime
