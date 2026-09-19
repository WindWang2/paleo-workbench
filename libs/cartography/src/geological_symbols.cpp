// CONV-27 — implementation of the geological symbol registry V2.
// See geological_symbols.hpp for the ported Python contract.
#include <pwb/cartography/geological_symbols.hpp>

#include <algorithm>
#include <cstdio>
#include <stdexcept>

namespace pwb::cartography {

std::optional<std::string> pattern_id_for_facies(const std::string& name) {
    // FACIES_PATTERN_MAP — exact lookup after str.strip().
    std::size_t start = name.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return std::nullopt;
    std::size_t end = name.find_last_not_of(" \t\r\n");
    const std::string key = name.substr(start, end - start + 1);
    static const std::vector<std::pair<std::string, std::string>> kMap = {
        {"alluvial_fan", "alluvial_fan"},
        {"fluvial", "fluvial"},
        {"lacustrine", "lacustrine"},
        {"delta", "delta"},
        {"shallow_marine", "shallow_marine"},
        {"deep_marine", "deep_marine"},
        {"shoreline", "shoreface"},
        {"扇三角洲", "delta"},
        {"三角洲前缘", "delta"},
        {"滨浅湖", "lacustrine"},
        {"湖相泥", "lacustrine"},
        {"冲积扇", "alluvial_fan"},
        {"河流", "fluvial"},
        {"湖泊", "lacustrine"},
        {"三角洲", "delta"},
        {"岸线带", "shoreface"},
        {"浅海", "shallow_marine"},
        {"深海", "deep_marine"},
        {"深水盆地", "abyssal"},
        {"滨岸", "shoreface"},
        {"潟湖", "lagoon"},
        {"潮坪", "tidal_flat"},
        {"碳酸盐台地", "carbonate_platform"},
        {"陆棚", "shelf"},
    };
    for (const auto& entry : kMap) {
        if (entry.first == key) return entry.second;
    }
    return std::nullopt;
}

namespace {

Json dict(const std::vector<std::pair<std::string, Json>>& pairs) {
    Json out = Json::object();
    for (const auto& pair : pairs) out[pair.first] = pair.second;
    return out;
}

// The LayerRole value vocabulary (mapping_workspace/layer_roles.py). The
// Qt-free kernel carries it as data so validate_binding can reproduce the
// Python LayerRole(role) ValueError path.
const std::vector<std::string>& known_layer_roles() {
    static const std::vector<std::string> roles = {
        "base_reference",
        "initial_facies_source", "initial_facies_draft",
        "well_facies_prediction", "well_facies_confidence",
        "seismic_facies_prediction", "seismic_facies_confidence",
        "interpretation_annotation", "pending_review_area",
        "provenance_direction", "provenance_line", "distribution_line",
        "paleo_shoreline", "facies_boundary", "fault_constraint",
        "interpolation_boundary", "mask_boundary",
        "factor_input", "factor_grid", "factor_contour",
        "factor_classification", "factor_uncertainty", "factor_qc",
        "analysis_aid",
        "integrated_facies", "integrated_boundary",
        "map_annotation", "map_symbol", "map_reference",
        "qc_warning", "qc_conflict",
        "user_general", "legacy_unclassified",
    };
    return roles;
}

}  // namespace

// LayerRole vocabulary membership — declared at pwb::cartography scope in
// the header; we are already inside that namespace here.
bool is_known_layer_role(const std::string& role) {
    const std::vector<std::string>& roles = known_layer_roles();
    return std::find(roles.begin(), roles.end(), role) != roles.end();
}

namespace {

// The domain vocab (geological_symbols.py §6 tables).
struct FaultClass {
    std::string value;
    const char* stroke;
    const char* label;
    double width;
};
const std::vector<FaultClass>& fault_classes() {
    static const std::vector<FaultClass> classes = {
        {"normal", "#c0392b", "正断层", 1.6},
        {"reverse", "#a93226", "逆断层", 1.6},
        {"thrust", "#7b241c", "冲断断层", 2.0},
        {"strike_slip", "#d35400", "走滑断层", 1.4},
        {"unclassified", "#95a5a6", "未分类断层", 1.2},
    };
    return classes;
}

struct FaciesClass {
    std::string value;
    const char* fill;
    const char* label;
};
const std::vector<FaciesClass>& facies_classes() {
    static const std::vector<FaciesClass> classes = {
        {"alluvial_fan", "#c47f4e", "冲积扇"},
        {"fluvial", "#e8c46b", "河流"},
        {"lacustrine", "#8fc7c2", "湖泊"},
        {"delta", "#d9a066", "三角洲"},
        {"shoreline", "#eae2b0", "岸线带"},
        {"shallow_marine", "#6fb3b8", "浅海"},
        {"deep_marine", "#3d6b8e", "深海"},
        {"volcanic", "#9b6b9e", "火山岩"},
        {"other", "#b0bec5", "其他"},
    };
    return classes;
}

Json fault_confidence_levels() {
    return dict({
        {"inferred", dict({
             {"line_pattern", "dash"},
             {"stroke_width", 0.8},
             {"stroke_alpha", 0.55},
         })},
        {"interpreted", dict({
             {"line_pattern", "fault"},
             {"stroke_width", 1.6},
             {"stroke_alpha", 0.85},
         })},
        {"verified", dict({
             {"line_pattern", "fault"},
             {"stroke_width", 2.2},
             {"stroke_alpha", 1.0},
         })},
    });
}

Json fault_rules() {
    // _fault_rules: the per-class stroke color (not a shared base color).
    Json rules = Json::array();
    for (const FaultClass& fc : fault_classes()) {
        rules.push_back(dict({
            {"value", fc.value},
            {"stroke", fc.stroke},
            {"stroke_width", fc.width},
            {"line_pattern", "fault"},
            {"label", fc.label},
        }));
    }
    return rules;
}

Json facies_rules(bool with_patterns) {
    Json rules = Json::array();
    for (const FaciesClass& fc : facies_classes()) {
        Json rule = Json::object();
        rule["value"] = fc.value;
        rule["fill"] = fc.fill;
        rule["label"] = fc.label;
        if (with_patterns) {
            auto pattern = pattern_id_for_facies(fc.value);
            if (pattern.has_value()) rule["pattern"] = *pattern;
        }
        rules.push_back(std::move(rule));
    }
    return rules;
}

std::vector<StyleFillPattern> facies_fill_patterns() {
    std::vector<StyleFillPattern> patterns;
    for (const FaciesClass& fc : facies_classes()) {
        auto pattern = pattern_id_for_facies(fc.value);
        if (pattern.has_value()) {
            patterns.push_back(StyleFillPattern{fc.value, *pattern});
        }
    }
    return patterns;
}

GeologicalSymbolDef make_symbol(
    const char* symbol_id, long long version, const char* title,
    const char* category, std::vector<std::string> roles,
    const char* geometry_kind, const VectorStyle& fallback,
    const char* renderer_kind, const char* field_name, Json rules,
    Json extra_hint = Json(), Json metadata = Json()) {
    GeologicalSymbolDef def;
    def.symbol_id = symbol_id;
    def.version = version;
    def.title = title;
    def.category = category;
    def.applicable_roles = std::move(roles);
    def.geometry_kind = geometry_kind;
    def.legacy_fallback = fallback;
    Json hint = Json::object();
    hint["renderer_kind"] = renderer_kind;
    hint["field"] = field_name != nullptr ? Json(field_name) : Json();
    hint["rules"] = std::move(rules);
    if (extra_hint.is_object()) {
        for (auto it = extra_hint.begin(); it != extra_hint.end(); ++it) {
            hint[it.key()] = it.value();  // update() appends new keys
        }
    }
    def.renderer_hint = std::move(hint);
    def.metadata = std::move(metadata);
    return def;
}

VectorStyle simple_line(const char* stroke, double width,
                        LinePattern pattern = LinePattern::Solid) {
    VectorStyle s;
    s.fill = "transparent";
    s.stroke = stroke;
    s.stroke_width = width;
    s.line_pattern = pattern;
    return s;
}

// Registry construction, in Python definition order.
std::vector<std::pair<std::string, GeologicalSymbolDef>> build_registry() {
    std::vector<std::pair<std::string, GeologicalSymbolDef>> registry;
    auto add = [&](GeologicalSymbolDef def) {
        registry.push_back({def.symbol_id, std::move(def)});
    };
    const std::vector<std::string> line_roles = {"fault_constraint"};
    const std::vector<std::string> facies_roles = {
        "initial_facies_source", "initial_facies_draft",
        "factor_classification", "integrated_facies"};

    // -- FAULT ---------------------------------------------------------------
    {
        VectorStyle fallback = simple_line("#c0392b", 1.6, LinePattern::Fault);
        fallback.renderer = "categorized";
        fallback.field = "fault_type";
        for (const FaultClass& fc : fault_classes()) {
            fallback.categories.push_back({fc.value, fc.stroke, fc.label});
        }
        add(make_symbol(
            "fault_v2", 2, "断层（按性质分类 + 置信度分级）", "fault",
            line_roles, "line", fallback, "categorized", "fault_type",
            fault_rules(),
            dict({
                {"confidence", dict({
                     {"field", "confidence"},
                     {"mechanism", "data_defined"},
                     {"applies_to", Json::array({"stroke_width", "stroke_alpha",
                                                 "line_pattern"})},
                     {"levels", fault_confidence_levels()},
                 })},
            }),
            dict({
                {"legend_label", "断层"},
                {"symbol_layers",
                 "fault_type controls the categorized base symbol "
                 "(hanging-wall decorations realised via renderer XML); "
                 "confidence drives the data-defined gradations in "
                 "renderer_hint.confidence"},
                {"confidence_semantics",
                 dict({
                     {"inferred",
                      "dashed, thinnest, 55% alpha — 仅供推断"},
                     {"interpreted",
                      "fault long-dash, standard weight — 解释成果"},
                     {"verified",
                      "fault long-dash, heaviest, opaque — 已验证"},
                 })},
            })));
        // Per-class singles (the fault_type domain minus "unclassified").
        for (const FaultClass& fc : fault_classes()) {
            if (fc.value == "unclassified") continue;
            add(make_symbol(
                ("fault_" + fc.value + "_v2").c_str(), 2, fc.label, "fault",
                line_roles, "line", simple_line(fc.stroke, fc.width,
                                                LinePattern::Fault),
                "single", nullptr, Json::array(), Json(),
                dict({
                    {"legend_label", fc.label},
                    {"fault_type", fc.value},
                })));
        }
        add(make_symbol(
            "fault_inferred_v2", 2, "推断断层（虚线）", "fault", line_roles,
            "line", simple_line("#d98880", 0.8, LinePattern::Dash), "single",
            nullptr, Json::array(), Json(),
            dict({
                {"legend_label", "推断断层"},
                {"confidence_level", "inferred"},
                {"note",
                 "inferred confidence faults render dashed at reduced "
                 "weight; fault_v2 realises this via "
                 "renderer_hint.confidence"},
            })));
    }

    // -- FACIES ---------------------------------------------------------------
    {
        VectorStyle fallback;
        fallback.fill = "#b0bec5";
        fallback.stroke = "#26364d";
        fallback.stroke_width = 0.6;
        fallback.renderer = "categorized";
        fallback.field = "facies_name";
        for (const FaciesClass& fc : facies_classes()) {
            fallback.categories.push_back({fc.value, fc.fill, fc.label});
        }
        fallback.fill_patterns = facies_fill_patterns();
        Json legend_groups = Json::array();
        legend_groups.push_back(dict({
            {"label", "陆相 (Continental)"},
            {"classes", Json::array({"alluvial_fan", "fluvial", "lacustrine"})},
        }));
        legend_groups.push_back(dict({
            {"label", "过渡相 (Transitional)"},
            {"classes", Json::array({"delta", "shoreline"})},
        }));
        legend_groups.push_back(dict({
            {"label", "海相 (Marine)"},
            {"classes", Json::array({"shallow_marine", "deep_marine"})},
        }));
        legend_groups.push_back(dict({
            {"label", "其他 (Other)"},
            {"classes", Json::array({"volcanic", "other"})},
        }));
        add(make_symbol(
            "facies_v2", 2, "沉积相分类填充（9 类印刷色板）", "facies",
            facies_roles, "polygon", fallback, "categorized", "facies_name",
            facies_rules(true), Json(),
            dict({
                {"legend_label", "沉积相"},
                {"legend_groups", std::move(legend_groups)},
                {"palette",
                 "print-safe geological fills; hierarchy groups drive "
                 "composer legend grouping"},
            })));
        VectorStyle hatch = simple_line("#26364d", 0.3);
        hatch.renderer = "categorized";
        hatch.field = "facies_name";
        for (const FaciesClass& fc : facies_classes()) {
            hatch.categories.push_back({fc.value, "transparent", fc.label});
        }
        Json hatch_angles = dict({
            {"alluvial_fan", 45.0},
            {"fluvial", 90.0},
            {"lacustrine", 0.0},
            {"delta", 30.0},
            {"shoreline", 60.0},
            {"shallow_marine", 135.0},
            {"deep_marine", 160.0},
            {"volcanic", -45.0},
            {"other", 120.0},
        });
        add(make_symbol(
            "facies_hatch_v2", 2, "沉积相纹理（图例 hatching 变体）", "facies",
            facies_roles, "polygon", hatch, "categorized", "facies_name",
            facies_rules(false), Json(),
            dict({
                {"legend_label", "沉积相（纹理）"},
                {"hatch",
                 dict({
                     {"style", "line_pattern_fill"},
                     {"line_color", "#26364d"},
                     {"line_width", 0.3},
                     {"spacing_mm", 1.2},
                     {"background", "transparent"},
                     {"per_class_angle_deg", std::move(hatch_angles)},
                     {"note",
                      "declaration only — realised as QGIS LinePatternFill "
                      "symbol layers via renderer XML; composer legend "
                      "textures read these parameters directly"},
                 })},
            })));
    }

    // -- PROVENANCE ---------------------------------------------------------------
    {
        add(make_symbol(
            "provenance_line_v1", 1, "物源线（箭头装饰）", "provenance",
            {"provenance_line"}, "line", simple_line("#2f6fab", 1.6), "single",
            nullptr, Json::array(), Json(),
            dict({
                {"legend_label", "物源线"},
                {"decorations",
                 Json::array({dict({
                     {"kind", "arrow"},
                     {"placement", "line_end"},
                     {"size", 6.0},
                     {"color", "#2f6fab"},
                 })})},
                {"note",
                 "arrow decorations realised as QGIS line-decoration "
                 "symbol layers via renderer XML"},
            })));
        VectorStyle direction = simple_line("#2b6777", 1.2, LinePattern::Dash);
        TextStyle azimuth_labels;
        azimuth_labels.field = "azimuth_deg";
        azimuth_labels.size = 8.0;
        direction.labels = azimuth_labels;
        add(make_symbol(
            "provenance_direction_v1", 1, "物源方向（中点方向箭头 + 方位角标注）",
            "provenance", {"provenance_direction"}, "line", direction,
            "single", nullptr, Json::array(), Json(),
            dict({
                {"legend_label", "物源方向"},
                {"decorations",
                 Json::array({dict({
                     {"kind", "direction_arrow"},
                     {"placement", "line_midpoint"},
                     {"rotation_field", "azimuth_deg"},
                     {"size", 8.0},
                     {"color", "#2b6777"},
                 })})},
                {"labels",
                 dict({
                     {"field", "azimuth_deg"},
                     {"format", "{:.0f}°"},
                 })},
            })));
        add(make_symbol(
            "distribution_line_v1", 1, "沉积体系展布线", "provenance",
            {"distribution_line"}, "line",
            simple_line("#8a7136", 1.8, LinePattern::Dash), "single", nullptr,
            Json::array(), Json(),
            dict({
                {"legend_label", "展布线"},
            })));
    }

    // -- BOUNDARY -------------------------------------------------------------------
    {
        add(make_symbol(
            "shoreline_v2", 2, "古岸线", "boundary", {"paleo_shoreline"},
            "line", simple_line("#1f78b4", 1.8), "single", nullptr,
            Json::array(), Json(),
            dict({
                {"legend_label", "古岸线"},
            })));
        add(make_symbol(
            "facies_boundary_v2", 2, "相带边界", "boundary",
            {"facies_boundary", "integrated_boundary"}, "line",
            simple_line("#333f48", 1.4), "single", nullptr, Json::array(),
            Json(),
            dict({
                {"legend_label", "相带边界"},
            })));
        add(make_symbol(
            "interpolation_boundary_v2", 2, "插值限制边界（成图范围）",
            "boundary", {"interpolation_boundary"}, "polygon",
            simple_line("#7f8c8d", 1.2, LinePattern::Dash), "single", nullptr,
            Json::array(), Json(),
            dict({
                {"legend_label", "插值限制边界"},
            })));
        add(make_symbol(
            "map_extent", 2, "成图范围/图框边界", "boundary",
            {"interpolation_boundary", "map_reference", "base_reference"},
            "polygon", simple_line("#1c2833", 2.4), "single", nullptr,
            Json::array(), Json(),
            dict({
                {"legend_label", "成图范围"},
            })));
    }
    return registry;
}

}  // namespace

void GeologicalSymbolDef::validate() const {
    const bool known_category =
        std::any_of(std::begin(kSymbolCategories), std::end(kSymbolCategories),
                    [this](const char* c) { return category == c; });
    if (!known_category) {
        throw std::invalid_argument(
            "symbol '" + symbol_id + "': unknown category '" + category +
            "'; expected one of ('fault', 'facies', 'provenance', 'boundary')");
    }
    if (geometry_kind != "point" && geometry_kind != "line" &&
        geometry_kind != "polygon") {
        throw std::invalid_argument(
            "symbol '" + symbol_id + "': unknown geometry_kind '" +
            geometry_kind + "'; expected one of ['line', 'point', 'polygon']");
    }
    std::string kind = "single";
    if (renderer_hint.is_object()) {
        auto it = renderer_hint.find("renderer_kind");
        if (it != renderer_hint.end() && it->is_string()) {
            kind = it->get<std::string>();
        }
    }
    if (kind != "single" && kind != "categorized" && kind != "graduated") {
        throw std::invalid_argument(
            "symbol '" + symbol_id + "': unknown renderer_kind '" + kind +
            "'; expected one of ['categorized', 'graduated', 'single']");
    }
    if (version < 1) {
        throw std::invalid_argument("symbol '" + symbol_id +
                                    "': version must be >= 1");
    }
}

Json GeologicalSymbolDef::to_dict() const {
    Json data = Json::object();
    data["symbol_id"] = symbol_id;
    data["version"] = version;
    data["title"] = title;
    data["category"] = category;
    Json roles = Json::array();
    std::vector<std::string> sorted_roles = applicable_roles;
    std::sort(sorted_roles.begin(), sorted_roles.end());
    for (const std::string& role : sorted_roles) roles.push_back(role);
    data["applicable_roles"] = std::move(roles);
    data["geometry_kind"] = geometry_kind;
    data["legacy_fallback"] = legacy_fallback.to_dict();
    data["renderer_hint"] = renderer_hint;
    data["metadata"] = metadata;
    return data;
}

GeologicalSymbolDef GeologicalSymbolDef::from_dict(const Json& data) {
    if (!data.is_object()) {
        throw std::invalid_argument("symbol payload must be an object");
    }
    GeologicalSymbolDef def;
    def.symbol_id = data.at("symbol_id").get<std::string>();
    def.version = data.at("version").get<long long>();
    def.title = data.at("title").get<std::string>();
    def.category = data.at("category").get<std::string>();
    auto roles_it = data.find("applicable_roles");
    if (roles_it != data.end() && roles_it->is_array()) {
        for (const Json& role : *roles_it) {
            def.applicable_roles.push_back(role.get<std::string>());
        }
    }
    def.geometry_kind = data.at("geometry_kind").get<std::string>();
    auto fallback_it = data.find("legacy_fallback");
    def.legacy_fallback =
        VectorStyle::from_dict(fallback_it != data.end() ? *fallback_it : Json());
    auto hint_it = data.find("renderer_hint");
    if (hint_it != data.end() && hint_it->is_object()) {
        def.renderer_hint = *hint_it;
    } else {
        def.renderer_hint = Json::object();
    }
    auto metadata_it = data.find("metadata");
    if (metadata_it != data.end() && metadata_it->is_object()) {
        def.metadata = *metadata_it;
    } else {
        def.metadata = Json::object();
    }
    def.validate();
    return def;
}

StyleEntry GeologicalSymbolDef::style_entry() const {
    // _LEGACY_CATEGORY: fault/facies/boundary keep their V1 category names.
    static const std::vector<std::pair<std::string, std::string>> kLegacy = {
        {"fault", "fault"},
        {"facies", "facies_fills"},
        {"boundary", "boundary"},
        {"provenance", "provenance"},
    };
    std::string legacy_category = category;
    for (const auto& pair : kLegacy) {
        if (pair.first == category) legacy_category = pair.second;
    }
    std::string legend = title;
    if (metadata.is_object()) {
        auto it = metadata.find("legend_label");
        if (it != metadata.end() && it->is_string() &&
            !it->get<std::string>().empty()) {
            legend = it->get<std::string>();
        }
    }
    std::optional<double> opacity_hint;
    if (metadata.is_object()) {
        auto it = metadata.find("opacity_hint");
        if (it != metadata.end() && it->is_number()) {
            opacity_hint = it->get<double>();
        }
    }
    return StyleEntry{symbol_id, legacy_category, title, legacy_fallback,
                      binding_record(symbol_id), legend, opacity_hint};
}

const std::vector<std::pair<std::string, GeologicalSymbolDef>>&
geological_symbols() {
    static const std::vector<std::pair<std::string, GeologicalSymbolDef>>
        registry = build_registry();
    return registry;
}

std::string canonical_symbol_id(const std::string& symbol_id) {
    static const std::vector<std::pair<std::string, std::string>> kAliases = {
        {"facies_v1", "facies_v2"},
        {"shoreline_v1", "shoreline_v2"},
        {"facies_boundary_v1", "facies_boundary_v2"},
        {"interpolation_boundary_v1", "interpolation_boundary_v2"},
    };
    for (const auto& alias : kAliases) {
        if (alias.first == symbol_id) return alias.second;
    }
    return symbol_id;
}

const GeologicalSymbolDef& symbol_by_id(const std::string& symbol_id) {
    const std::string canonical = canonical_symbol_id(symbol_id);
    for (const auto& entry : geological_symbols()) {
        if (entry.first == canonical) return entry.second;
    }
    std::vector<std::string> available;
    for (const auto& entry : geological_symbols()) {
        available.push_back(entry.first);
    }
    std::sort(available.begin(), available.end());
    std::string listing = "[";
    for (std::size_t i = 0; i < available.size(); ++i) {
        if (i > 0) listing += ", ";
        listing += "'" + available[i] + "'";
    }
    listing += "]";
    throw std::out_of_range("unknown geological symbol '" + symbol_id +
                            "'; available: " + listing);
}

std::vector<const GeologicalSymbolDef*> symbols_for_role(
    const std::string& role) {
    // Python LayerRole(role) raises ValueError for unknown strings.
    if (!is_known_layer_role(role)) {
        throw std::invalid_argument("'" + role + "' is not a LayerRole");
    }
    std::vector<const GeologicalSymbolDef*> matches;
    for (const auto& entry : geological_symbols()) {
        const auto& roles = entry.second.applicable_roles;
        if (std::find(roles.begin(), roles.end(), role) != roles.end()) {
            matches.push_back(&entry.second);
        }
    }
    return matches;
}

namespace {
const char* kCompatibleGeometryPoint[] = {"point", "vector"};
const char* kCompatibleGeometryLine[] = {"line", "vector", "polyline",
                                         "multiline"};
const char* kCompatibleGeometryPolygon[] = {"polygon", "vector",
                                            "multipolygon"};

bool compatible_geometry(const std::string& symbol_geometry,
                         const std::string& geometry_kind) {
    const char* const* list = nullptr;
    std::size_t count = 0;
    if (symbol_geometry == "point") {
        list = kCompatibleGeometryPoint;
        count = 2;
    } else if (symbol_geometry == "line") {
        list = kCompatibleGeometryLine;
        count = 4;
    } else if (symbol_geometry == "polygon") {
        list = kCompatibleGeometryPolygon;
        count = 3;
    }
    for (std::size_t i = 0; i < count; ++i) {
        if (geometry_kind == list[i]) return true;
    }
    return false;
}
}  // namespace

std::pair<bool, std::string> validate_binding(const std::string& symbol_id,
                                              const std::string& role,
                                              const std::string& geometry_kind) {
    const GeologicalSymbolDef* symbol = nullptr;
    try {
        symbol = &symbol_by_id(symbol_id);
    } catch (const std::out_of_range&) {
        return {false, "unknown symbol '" + symbol_id + "'"};
    }
    // Python raises LayerRole(role) ValueError for unknown role strings.
    if (!is_known_layer_role(role)) {
        return {false, "unknown role '" + role + "'"};
    }
    if (std::find(symbol->applicable_roles.begin(),
                  symbol->applicable_roles.end(),
                  role) == symbol->applicable_roles.end()) {
        return {false,
                "symbol '" + symbol->symbol_id + "' (category '" +
                    symbol->category + "') does not apply to role '" + role +
                    "'"};
    }
    if (!compatible_geometry(symbol->geometry_kind, geometry_kind)) {
        return {false,
                "symbol '" + symbol->symbol_id + "' expects '" +
                    symbol->geometry_kind + "' geometry; got '" +
                    geometry_kind + "'"};
    }
    return {true, "ok"};
}

long long library_version() { return kSymbolLibrarySchemaVersion; }

Json legacy_style_for_symbol(const std::string& symbol_id,
                             const Json& overrides) {
    const GeologicalSymbolDef& symbol = symbol_by_id(symbol_id);
    VectorStyle style = symbol.legacy_fallback;
    if (overrides.is_object()) {
        for (auto it = overrides.begin(); it != overrides.end(); ++it) {
            const std::string& key = it.key();
            const Json& value = it.value();
            if (key == "fill") style.fill = value.get<std::string>();
            else if (key == "stroke") style.stroke = value.get<std::string>();
            else if (key == "stroke_width") style.stroke_width = value.get<double>();
            else if (key == "marker_size") style.marker_size = value.get<double>();
            else if (key == "renderer") style.renderer = value.get<std::string>();
            else if (key == "field") style.field = value.get<std::string>();
            else if (key == "line_pattern") {
                auto parsed = line_pattern_from_value(value.get<std::string>());
                if (!parsed.has_value()) {
                    throw std::invalid_argument(
                        "'" + value.get<std::string>() +
                        "' is not a valid LinePattern");
                }
                style.line_pattern = *parsed;
            } else if (key == "marker") {
                auto parsed = marker_symbol_from_value(value.get<std::string>());
                if (!parsed.has_value()) {
                    throw std::invalid_argument(
                        "'" + value.get<std::string>() +
                        "' is not a valid MarkerSymbol");
                }
                style.marker = *parsed;
            } else if (key == "labels") {
                // Dataclasses.replace accepts every field; labels rebuilds
                // through the tolerant TextStyle parser.
                style.labels = TextStyle::from_dict(value);
            } else {
                throw std::invalid_argument(
                    "legacy_style_for_symbol() got an unexpected keyword "
                    "argument '" +
                    key + "'");
            }
        }
    }
    return style.to_dict();
}

Json binding_record(const std::string& symbol_id, const Json& field_values) {
    const GeologicalSymbolDef& symbol = symbol_by_id(symbol_id);
    Json record = Json::object();
    record["symbol_id"] = symbol.symbol_id;
    record["symbol_version"] = symbol.version;
    record["category"] = symbol.category;
    Json field_value = nullptr;
    if (symbol.renderer_hint.is_object()) {
        auto it = symbol.renderer_hint.find("field");
        if (it != symbol.renderer_hint.end()) field_value = *it;
    }
    record["field"] = std::move(field_value);
    Json classes = Json::array();
    if (symbol.renderer_hint.is_object()) {
        auto rules_it = symbol.renderer_hint.find("rules");
        if (rules_it != symbol.renderer_hint.end() && rules_it->is_array()) {
            for (const Json& rule : *rules_it) {
                auto value_it = rule.find("value");
                if (value_it != rule.end()) classes.push_back(*value_it);
            }
        }
    }
    record["classes"] = std::move(classes);
    record["source"] = "geological-symbols-v" +
                       std::to_string(kSymbolLibrarySchemaVersion) + "/" +
                       symbol.symbol_id;
    if (symbol.renderer_hint.is_object()) {
        auto confidence_it = symbol.renderer_hint.find("confidence");
        if (confidence_it != symbol.renderer_hint.end() &&
            confidence_it->is_object()) {
            auto field_it = confidence_it->find("field");
            if (field_it != confidence_it->end()) {
                record["confidence_field"] = *field_it;
            }
        }
    }
    if (field_values.is_object() && !field_values.empty()) {
        record["field_values"] = field_values;
    }
    return record;
}

StyleEntry style_entry_for_symbol(const std::string& symbol_id) {
    return symbol_by_id(symbol_id).style_entry();
}

std::vector<std::string> register_symbols_into_style_library(
    std::vector<std::pair<std::string, StyleEntry>>& library) {
    std::vector<std::string> added;
    for (const auto& entry : geological_symbols()) {
        StyleEntry projected = entry.second.style_entry();
        const std::string key = projected.category + "." + projected.key;
        bool replaced = false;
        for (auto& slot : library) {
            if (slot.first == key) {
                slot.second = projected;  // V1 built-ins are never replaced by
                                          // construction (disjoint key space)
                replaced = true;
                break;
            }
        }
        if (!replaced) library.push_back({key, std::move(projected)});
        added.push_back(key);
    }
    return added;
}

std::vector<std::string> unregister_symbols_from_style_library(
    std::vector<std::pair<std::string, StyleEntry>>& library) {
    static const std::vector<std::pair<std::string, std::string>> kLegacy = {
        {"fault", "fault"},
        {"facies", "facies_fills"},
        {"boundary", "boundary"},
        {"provenance", "provenance"},
    };
    std::vector<std::string> removed;
    for (const auto& entry : geological_symbols()) {
        std::string legacy_category = entry.second.category;
        for (const auto& pair : kLegacy) {
            if (pair.first == entry.second.category) {
                legacy_category = pair.second;
            }
        }
        const std::string key = legacy_category + "." + entry.second.symbol_id;
        for (auto it = library.begin(); it != library.end(); ++it) {
            if (it->first == key) {
                library.erase(it);
                removed.push_back(key);
                break;
            }
        }
    }
    return removed;
}

Json symbol_library_document() {
    Json payload = Json::object();
    payload["schema_version"] = kSymbolLibrarySchemaVersion;
    Json symbols = Json::array();
    for (const auto& entry : geological_symbols()) {
        symbols.push_back(entry.second.to_dict());
    }
    payload["symbols"] = std::move(symbols);
    return payload;
}

std::vector<std::pair<std::string, GeologicalSymbolDef>>
parse_symbol_library_document(const Json& document) {
    if (!document.is_object()) {
        throw std::invalid_argument("symbol library document must be an object");
    }
    long long version = 0;
    auto version_it = document.find("schema_version");
    if (version_it != document.end() && version_it->is_number_integer()) {
        version = version_it->get<long long>();
    }
    if (version != kSymbolLibrarySchemaVersion) {
        throw std::invalid_argument(
            "symbol library schema " + std::to_string(version) +
            " unsupported; expected " +
            std::to_string(kSymbolLibrarySchemaVersion));
    }
    std::vector<std::pair<std::string, GeologicalSymbolDef>> defs;
    auto symbols_it = document.find("symbols");
    if (symbols_it != document.end() && symbols_it->is_array()) {
        for (const Json& raw : *symbols_it) {
            GeologicalSymbolDef def = GeologicalSymbolDef::from_dict(raw);
            defs.push_back({def.symbol_id, std::move(def)});
        }
    }
    return defs;
}

}  // namespace pwb::cartography
