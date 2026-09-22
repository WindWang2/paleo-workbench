#include <pwb/mapping_document/composer_templates.hpp>

#include <array>
#include <map>
#include <stdexcept>
#include <utility>

namespace pwb::mapping_document {

namespace {

// ---------------------------------------------------------------------------
// Small local helpers (templates.py _def / _build_templates)
// ---------------------------------------------------------------------------

TemplateElementDefinition def(const std::string& element_type, double x, double y,
                             double w, double h, long long z, Json properties) {
    TemplateElementDefinition out;
    out.element_type = element_type;
    out.x_mm = x;
    out.y_mm = y;
    out.width_mm = w;
    out.height_mm = h;
    out.z_index = z;
    out.properties = std::move(properties);
    if (!out.properties.is_object()) out.properties = Json::object();
    return out;
}

Json data_binding(const std::string& key) {
    Json out = Json::object();
    out["key"] = key;
    return out;
}

Json fields_of(std::vector<std::pair<std::string, std::string>> fields) {
    Json out = Json::array();
    for (auto& [key, value] : fields) {
        Json row = Json::array();
        row.push_back(key);
        row.push_back(value);
        out.push_back(std::move(row));
    }
    return out;
}

Json stops_of(std::vector<std::pair<double, std::string>> stops) {
    Json out = Json::array();
    for (auto& [pos, color] : stops) {
        Json row = Json::array();
        row.push_back(pos);
        row.push_back(color);
        out.push_back(std::move(row));
    }
    return out;
}

Json items_of(std::vector<std::pair<std::string, std::string>> items) {
    Json out = Json::array();
    for (auto& [label, pattern] : items) {
        Json entry = Json::object();
        entry["label"] = label;
        entry["pattern"] = pattern;
        out.push_back(std::move(entry));
    }
    return out;
}

Json series_of(std::vector<std::tuple<std::string, double, double>> entries) {
    Json out = Json::array();
    for (const auto& [label, angle, value] : entries) {
        Json entry = Json::object();
        entry["label"] = label;
        entry["angle_deg"] = angle;
        entry["value"] = value;
        out.push_back(std::move(entry));
    }
    return out;
}

Json common_style(const std::vector<std::pair<std::string, std::string>>& extra) {
    Json style = Json::object();
    style["colormap"] = "viridis";
    style["contour.line_color"] = "#37474f";
    style["well_symbol"] = "circle";
    for (const auto& [key, value] : extra) style[key] = value;
    return style;
}

// templates.py _factor_map_components — the shared factor-map component
// stack used by single_factor / contour / heatmap / isopach.
std::vector<TemplateElementDefinition> factor_map_components(
    const std::string& colorbar_title, const std::string& title,
    double right_column_x, const std::array<double, 4>& map_box) {
    const double mx = map_box[0];
    const double my = map_box[1];
    const double mw = map_box[2];
    const double mh = map_box[3];
    std::vector<TemplateElementDefinition> out;

    Json title_props = Json::object();
    title_props["text"] = title;
    title_props["font_size"] = 9;
    title_props["align"] = "center";
    out.push_back(def("title", mx, 6.0, mw, 12.0, 40, std::move(title_props)));

    out.push_back(def("main_map", mx, my, mw, mh, 10, Json::object()));

    Json north_props = Json::object();
    north_props["label"] = "N";
    out.push_back(def("north_arrow", right_column_x + 62.0, 10.0, 12.0, 16.0, 30,
                      std::move(north_props)));

    Json scale_props = Json::object();
    scale_props["length_km"] = 10;
    scale_props["units"] = "km";
    out.push_back(def("scale_bar", mx + 4.0, my + mh + 4.0, 46.0, 7.0, 30,
                      std::move(scale_props)));

    out.push_back(def("legend", right_column_x, my + 44.0, 78.0, 56.0, 30,
                      Json::object()));

    Json colorbar_props = Json::object();
    colorbar_props["title"] = colorbar_title;
    colorbar_props["min"] = 0.0;
    colorbar_props["max"] = 1.0;
    colorbar_props["discrete"] = false;
    colorbar_props["data_binding"] = data_binding("factor.colorbar");
    out.push_back(def("colorbar", right_column_x + 30.0, my + 2.0, 12.0, 36.0, 30,
                      std::move(colorbar_props)));

    Json metadata_props = Json::object();
    metadata_props["fields"] =
        fields_of({{"编制", ""}, {"日期", ""}, {"比例尺", ""}, {"数据来源", ""}});
    out.push_back(def("metadata", mx, my + mh + 12.0, std::min(160.0, mw), 14.0,
                      30, std::move(metadata_props)));
    return out;
}

std::vector<CompositionTemplate> build_library() {
    std::vector<CompositionTemplate> templates;

    // Shared A4 landscape geometry.
    const auto map_box = template_base_map_frames(297.0, 210.0);
    const double right_x = map_box[0] + map_box[2] + 6.0;

    {
        CompositionTemplate t;
        t.template_id = "single_factor";
        t.category = "single_factor";
        t.label = "单因素图";
        t.description = "一个地质因素网格 + 色标 + 图例 + 图廓整饰";
        t.element_definitions = factor_map_components("因素值", "单因素分析图", right_x, map_box);
        t.style_bindings = common_style({{"renderer", "graduated"}});
        Json bindings = Json::object();
        bindings["factor.colorbar"] = "factor grid colormap + range";
        t.data_bindings = std::move(bindings);
        templates.push_back(std::move(t));
    }
    {
        CompositionTemplate t;
        t.template_id = "contour";
        t.category = "contour";
        t.label = "等值线图";
        t.description = "等值线主图 + 计曲线标注 + 井位";
        t.element_definitions =
            factor_map_components("等值线值", "等值线图", right_x, map_box);
        t.style_bindings = common_style({{"renderer", "contour"}, {"contour.label", "true"}});
        Json bindings = Json::object();
        bindings["factor.colorbar"] = "contour level range";
        t.data_bindings = std::move(bindings);
        templates.push_back(std::move(t));
    }
    {
        CompositionTemplate t;
        t.template_id = "heatmap";
        t.category = "heatmap";
        t.label = "热力图";
        t.description = "连续栅格热力显示 + 连续色标";
        t.element_definitions = factor_map_components("强度", "参数热力图", right_x, map_box);
        t.style_bindings =
            common_style({{"renderer", "grid"}, {"grid.interpolation", "bilinear"}});
        Json bindings = Json::object();
        bindings["factor.colorbar"] = "grid value range";
        t.data_bindings = std::move(bindings);
        templates.push_back(std::move(t));
    }
    {
        CompositionTemplate t;
        t.template_id = "well_location";
        t.category = "well_location";
        t.label = "井位图";
        t.description = "井位分布 + 井名标注 + 工区边界";
        {
            Json title_props = Json::object();
            title_props["text"] = "井位图";
            title_props["font_size"] = 9;
            title_props["align"] = "center";
            t.element_definitions.push_back(
                def("title", map_box[0], 6.0, map_box[2], 12.0, 40, std::move(title_props)));
        }
        t.element_definitions.push_back(
            def("main_map", map_box[0], map_box[1], map_box[2], map_box[3], 10, Json::object()));
        t.element_definitions.push_back(
            def("north_arrow", right_x + 62.0, 10.0, 12.0, 16.0, 30, Json::object()));
        {
            Json scale_props = Json::object();
            scale_props["length_km"] = 5;
            scale_props["units"] = "km";
            t.element_definitions.push_back(def("scale_bar", map_box[0] + 4.0,
                                                map_box[1] + map_box[3] + 4.0, 46.0, 7.0, 30,
                                                std::move(scale_props)));
        }
        t.element_definitions.push_back(def("legend", right_x, map_box[1] + 2.0, 78.0, 46.0,
                                            30, Json::object()));
        {
            Json inset_props = Json::object();
            inset_props["locator_scale"] = 6.0;
            t.element_definitions.push_back(def("inset_map", right_x, map_box[1] + 52.0, 60.0,
                                                44.0, 30, std::move(inset_props)));
        }
        {
            Json metadata_props = Json::object();
            metadata_props["fields"] =
                fields_of({{"井数", ""}, {"工区", ""}, {"日期", ""}});
            t.element_definitions.push_back(
                def("metadata", map_box[0], map_box[1] + map_box[3] + 12.0, 160.0, 14.0, 30,
                    std::move(metadata_props)));
        }
        t.style_bindings = common_style({{"well.label", "true"}});
        t.data_bindings = Json::object();
        templates.push_back(std::move(t));
    }
    {
        CompositionTemplate t;
        t.template_id = "seismic_interpretation";
        t.category = "seismic_interpretation";
        t.label = "地震解释图";
        t.description = "层位/断层解释成果 + 测线位置 + 层位图例";
        {
            Json title_props = Json::object();
            title_props["text"] = "地震解释成果图";
            title_props["font_size"] = 9;
            title_props["align"] = "center";
            t.element_definitions.push_back(
                def("title", map_box[0], 6.0, map_box[2], 12.0, 40, std::move(title_props)));
        }
        t.element_definitions.push_back(
            def("main_map", map_box[0], map_box[1], map_box[2], map_box[3], 10, Json::object()));
        t.element_definitions.push_back(
            def("north_arrow", right_x + 62.0, 10.0, 12.0, 16.0, 30, Json::object()));
        {
            Json scale_props = Json::object();
            scale_props["length_km"] = 10;
            scale_props["units"] = "km";
            t.element_definitions.push_back(def("scale_bar", map_box[0] + 4.0,
                                                map_box[1] + map_box[3] + 4.0, 46.0, 7.0, 30,
                                                std::move(scale_props)));
        }
        t.element_definitions.push_back(def("legend", right_x, map_box[1] + 2.0, 78.0, 60.0,
                                            30, Json::object()));
        {
            Json chart_props = Json::object();
            chart_props["chart_type"] = "bar";
            chart_props["title"] = "层位闭合差 (ms)";
            chart_props["data_binding"] = data_binding("interpretation.misfits");
            t.element_definitions.push_back(def("stat_chart", right_x, map_box[1] + 66.0, 78.0,
                                                48.0, 30, std::move(chart_props)));
        }
        {
            Json fault_props = Json::object();
            fault_props["title"] = "断层符号";
            fault_props["items"] = items_of({{"正向断层", "solid"},
                                             {"逆向断层", "dash"},
                                             {"走滑断层", "dashdot"}});
            t.element_definitions.push_back(def("fault_symbols", right_x, map_box[1] + 118.0,
                                                78.0, 26.0, 30, std::move(fault_props)));
        }
        {
            Json metadata_props = Json::object();
            metadata_props["fields"] = fields_of({{"解释层位", ""}, {"数据体", ""}, {"解释人", ""}});
            t.element_definitions.push_back(
                def("metadata", map_box[0], map_box[1] + map_box[3] + 12.0, 160.0, 14.0, 30,
                    std::move(metadata_props)));
        }
        t.style_bindings = common_style({{"horizon.line_color", "#d84315"},
                                         {"fault.line_color", "#37474f"},
                                         {"fault.dash", "4,2"}});
        Json bindings = Json::object();
        bindings["interpretation.misfits"] = "per-horizon misfit series";
        t.data_bindings = std::move(bindings);
        templates.push_back(std::move(t));
    }
    {
        CompositionTemplate t;
        t.template_id = "isopach";
        t.category = "isopach";
        t.label = "地层厚度图";
        t.description = "厚度等值线 + 厚度色填充 + 钻井厚度校核";
        t.element_definitions =
            factor_map_components("厚度 (m)", "地层厚度图（等厚图）", right_x, map_box);
        {
            Json chart_props = Json::object();
            chart_props["chart_type"] = "bar";
            chart_props["title"] = "井点厚度 (m)";
            chart_props["data_binding"] = data_binding("factor.well_values");
            t.element_definitions.push_back(def("stat_chart", right_x, map_box[1] + 104.0, 78.0,
                                                42.0, 30, std::move(chart_props)));
        }
        t.style_bindings = common_style({{"renderer", "graduated+contour"}});
        Json bindings = Json::object();
        bindings["factor.colorbar"] = "thickness range";
        bindings["factor.well_values"] = "per-well thickness series";
        t.data_bindings = std::move(bindings);
        templates.push_back(std::move(t));
    }
    {
        CompositionTemplate t;
        t.template_id = "lithofacies";
        t.category = "lithofacies";
        t.label = "岩相图";
        t.description = "岩相分区 + 离散岩相图例 + 井点岩性";
        {
            Json title_props = Json::object();
            title_props["text"] = "岩相古地理图";
            title_props["font_size"] = 9;
            title_props["align"] = "center";
            t.element_definitions.push_back(
                def("title", map_box[0], 6.0, map_box[2], 12.0, 40, std::move(title_props)));
        }
        t.element_definitions.push_back(
            def("main_map", map_box[0], map_box[1], map_box[2], map_box[3], 10, Json::object()));
        t.element_definitions.push_back(
            def("north_arrow", right_x + 62.0, 10.0, 12.0, 16.0, 30, Json::object()));
        {
            Json scale_props = Json::object();
            scale_props["length_km"] = 10;
            scale_props["units"] = "km";
            t.element_definitions.push_back(def("scale_bar", map_box[0] + 4.0,
                                                map_box[1] + map_box[3] + 4.0, 46.0, 7.0, 30,
                                                std::move(scale_props)));
        }
        t.element_definitions.push_back(def("legend", right_x, map_box[1] + 2.0, 78.0, 66.0,
                                            30, Json::object()));
        {
            Json metadata_props = Json::object();
            metadata_props["fields"] = fields_of({{"相模式", ""}, {"编图单元", ""}, {"日期", ""}});
            t.element_definitions.push_back(
                def("metadata", map_box[0], map_box[1] + map_box[3] + 12.0, 160.0, 14.0, 30,
                    std::move(metadata_props)));
        }
        t.style_bindings = common_style({{"renderer", "categorized"},
                                         {"facies.palette", "lithofacies-v1"}});
        t.data_bindings = Json::object();
        templates.push_back(std::move(t));
    }
    {
        CompositionTemplate t;
        t.template_id = "paleogeographic";
        t.category = "paleogeographic";
        t.label = "古地理图";
        t.description = "多因素古地理综合成果：岩相单元 + 等厚线 + 物源方向 + 水深";
        {
            Json title_props = Json::object();
            title_props["text"] = "古地理图";
            title_props["font_size"] = 10;
            title_props["align"] = "center";
            t.element_definitions.push_back(
                def("title", map_box[0], 6.0, map_box[2], 12.0, 40, std::move(title_props)));
        }
        t.element_definitions.push_back(
            def("main_map", map_box[0], map_box[1], map_box[2], map_box[3], 10, Json::object()));
        {
            Json grid_props = Json::object();
            grid_props["spacing_mm"] = 30.0;
            t.element_definitions.push_back(
                def("grid", map_box[0], map_box[1], map_box[2], map_box[3], 20, std::move(grid_props)));
        }
        t.element_definitions.push_back(
            def("north_arrow", right_x + 62.0, 10.0, 12.0, 16.0, 30, Json::object()));
        {
            Json scale_props = Json::object();
            scale_props["length_km"] = 25;
            scale_props["units"] = "km";
            t.element_definitions.push_back(def("scale_bar", map_box[0] + 4.0,
                                                map_box[1] + map_box[3] + 4.0, 46.0, 7.0, 30,
                                                std::move(scale_props)));
        }
        t.element_definitions.push_back(def("legend", right_x, map_box[1] + 2.0, 78.0, 72.0,
                                            30, Json::object()));
        {
            Json colorbar_props = Json::object();
            colorbar_props["title"] = "水深 (m)";
            colorbar_props["min"] = 0.0;
            colorbar_props["max"] = 50.0;
            colorbar_props["stops"] = stops_of({{0.0, "#b35806"},
                                                {0.5, "#fdbc8b"},
                                                {1.0, "#2c7bb6"}});
            colorbar_props["data_binding"] = data_binding("paleo.water_depth");
            t.element_definitions.push_back(def("colorbar", right_x + 30.0, map_box[1] + 78.0,
                                                12.0, 34.0, 30, std::move(colorbar_props)));
        }
        {
            Json annotation_props = Json::object();
            annotation_props["text"] = "物源方向 →";
            annotation_props["leader"] = false;
            t.element_definitions.push_back(
                def("annotation", map_box[0] + 18.0, map_box[1] + 16.0, 42.0, 8.0, 35,
                    std::move(annotation_props)));
        }
        {
            Json chart_props = Json::object();
            chart_props["chart_type"] = "rose";
            chart_props["title"] = "物源方向玫瑰图";
            chart_props["series"] = series_of({{"北东", 45.0, 8.0},
                                               {"南东", 135.0, 5.0},
                                               {"南西", 225.0, 6.5},
                                               {"北西", 315.0, 3.0}});
            t.element_definitions.push_back(def("stat_chart", right_x, map_box[1] + 116.0, 78.0,
                                                34.0, 30, std::move(chart_props)));
        }
        {
            Json metadata_props = Json::object();
            metadata_props["fields"] = fields_of({{"编图单元", ""},
                                                 {"资料截止", ""},
                                                 {"审校", ""},
                                                 {"图件版本", ""}});
            t.element_definitions.push_back(
                def("metadata", map_box[0], map_box[1] + map_box[3] + 12.0, 170.0, 14.0, 30,
                    std::move(metadata_props)));
        }
        t.style_bindings = common_style({{"renderer", "categorized+contour"},
                                         {"paleo.palette", "paleogeographic-v1"}});
        Json bindings = Json::object();
        bindings["paleo.water_depth"] = "water-depth factor colormap + range";
        bindings["paleo.paleocurrent"] = "物源方向玫瑰序列（angle_deg/value）";
        t.data_bindings = std::move(bindings);
        templates.push_back(std::move(t));
    }
    {
        CompositionTemplate t;
        t.template_id = "comprehensive";
        t.category = "comprehensive";
        t.label = "综合地质图";
        t.description = "多图面综合：主图 + 附图 + 统计 + 图例 + 完整元数据";
        {
            Json title_props = Json::object();
            title_props["text"] = "综合地质图";
            title_props["font_size"] = 10;
            title_props["align"] = "center";
            t.element_definitions.push_back(
                def("title", map_box[0], 6.0, map_box[2], 12.0, 40, std::move(title_props)));
        }
        t.element_definitions.push_back(
            def("main_map", map_box[0], map_box[1], map_box[2] * 0.62, map_box[3], 10,
                Json::object()));
        {
            Json inset_props = Json::object();
            inset_props["locator_scale"] = 5.0;
            t.element_definitions.push_back(
                def("inset_map", map_box[0] + map_box[2] * 0.65, map_box[1],
                    map_box[2] * 0.34, map_box[3] * 0.45, 10, std::move(inset_props)));
        }
        {
            Json chart_props = Json::object();
            chart_props["chart_type"] = "bar";
            chart_props["title"] = "单因素统计";
            chart_props["data_binding"] = data_binding("factor.well_values");
            t.element_definitions.push_back(
                def("stat_chart", map_box[0] + map_box[2] * 0.65,
                    map_box[1] + map_box[3] * 0.5, map_box[2] * 0.34,
                    map_box[3] * 0.46, 10, std::move(chart_props)));
        }
        t.element_definitions.push_back(
            def("north_arrow", right_x + 62.0, 10.0, 12.0, 16.0, 30, Json::object()));
        t.element_definitions.push_back(def("legend", right_x, map_box[1] + 2.0, 78.0, 84.0,
                                            30, Json::object()));
        {
            Json datasource_props = Json::object();
            datasource_props["title"] = "数据来源";
            datasource_props["text"] = "数据来源：\n井位/测线：\n解释成果：";
            t.element_definitions.push_back(
                def("datasource", right_x, map_box[1] + 90.0, 78.0, 26.0, 30,
                    std::move(datasource_props)));
        }
        {
            Json credits_props = Json::object();
            credits_props["text"] = "制图时间：\n编制：\n审核：";
            t.element_definitions.push_back(
                def("time_credits", right_x, map_box[1] + 120.0, 78.0, 18.0, 30,
                    std::move(credits_props)));
        }
        {
            Json metadata_props = Json::object();
            metadata_props["fields"] = fields_of({{"图名", ""},
                                                 {"编图单元", ""},
                                                 {"资料来源", ""},
                                                 {"编制", ""},
                                                 {"审核", ""},
                                                 {"日期", ""},
                                                 {"比例尺", ""}});
            t.element_definitions.push_back(
                def("metadata", map_box[0], map_box[1] + map_box[3] + 12.0, 190.0, 16.0, 30,
                    std::move(metadata_props)));
        }
        t.style_bindings = common_style({});
        Json bindings = Json::object();
        bindings["factor.well_values"] = "per-well factor series";
        t.data_bindings = std::move(bindings);
        templates.push_back(std::move(t));
    }
    {
        CompositionTemplate t;
        t.template_id = "professional_geographic";
        t.category = "paleogeographic";
        t.label = "专业地理图（经纬网）";
        t.description = "真实坐标变换、度分秒方位标注、黑白分度图框与实地比例尺";
        t.element_definitions = {
            def("main_map", 24, 28, 249, 144, 10, Json::object()),
            def("grid", 24, 28, 249, 144, 20,
                Json{{"geographic", true}, {"interval_degrees", 0.0},
                     {"color", "#606060"}, {"line_width_mm", 0.15}}),
            def("title", 24, 6, 249, 12, 30,
                Json{{"text", "专业地理图"}, {"font_size", 14}, {"align", "center"}}),
            def("scale_bar", 24, 184, 80, 8, 30,
                Json{{"calibrated", true}, {"numeric_scale", true},
                     {"length_km", 10.0}, {"units", "km"}}),
            def("north_arrow", 257, 35, 10, 14, 30, Json::object())};
        t.style_bindings = common_style({});
        t.data_bindings = Json::object();
        templates.push_back(std::move(t));
    }
    return templates;
}

}  // namespace

std::array<double, 4> template_base_map_frames(double paper_w_mm, double paper_h_mm) {
    const double margin = std::min(12.0, paper_w_mm * 0.05);
    const double top = 24.0;
    const double bottom = 34.0;
    return {margin, top, paper_w_mm - 2.0 * margin - 88.0, paper_h_mm - top - bottom};
}

const std::vector<CompositionTemplate>& composer_template_library() {
    static const std::vector<CompositionTemplate> kLibrary = build_library();
    return kLibrary;
}

const CompositionTemplate* find_composer_template(const std::string& template_id) {
    for (const auto& t : composer_template_library()) {
        if (t.template_id == template_id) return &t;
    }
    return nullptr;
}

Composition instantiate_composer_template(
    const CompositionFactory& factory, const std::string& template_id,
    const std::optional<std::string>& title, const std::optional<std::string>& paper_size,
    const std::optional<std::string>& orientation, const std::optional<double>& dpi) {
    const CompositionTemplate* tpl = find_composer_template(template_id);
    if (tpl == nullptr) {
        throw std::invalid_argument("unknown composition template '" + template_id + "'");
    }
    // Python `title or template.label` / `paper_size or template.paper_size` /
    // `dpi or 300.0` — falsy arguments fall back to the template values.
    const std::string doc_title = (title && !title->empty()) ? *title : tpl->label;
    const std::string doc_paper =
        (paper_size && !paper_size->empty()) ? *paper_size : tpl->paper_size;
    const std::string doc_orientation = (orientation && !orientation->empty())
                                            ? *orientation
                                            : tpl->orientation;
    const double doc_dpi = (dpi && *dpi != 0.0) ? *dpi : 300.0;

    Composition doc = factory.create_document(doc_title, doc_paper, doc_orientation, doc_dpi);
    if (!doc.metadata.is_object()) doc.metadata = Json::object();
    doc.metadata["template_id"] = tpl->template_id;
    doc.metadata["template_category"] = tpl->category;

    // Materialise definitions in z_index-sorted order (Python
    // sorted(..., key=lambda d: d.z_index)); add_element re-sorts stably,
    // matching Python's add_element.
    std::vector<const TemplateElementDefinition*> defs;
    defs.reserve(tpl->element_definitions.size());
    for (const auto& d : tpl->element_definitions) defs.push_back(&d);
    std::stable_sort(defs.begin(), defs.end(),
                     [](const TemplateElementDefinition* a, const TemplateElementDefinition* b) {
                         return a->z_index < b->z_index;
                     });
    for (const auto* d : defs) {
        ComposerElement element;
        element.id = factory.new_element_id();
        element.element_type = d->element_type;
        element.x_mm = d->x_mm;
        element.y_mm = d->y_mm;
        element.width_mm = d->width_mm;
        element.height_mm = d->height_mm;
        element.z_index = d->z_index;
        element.properties = d->properties.is_object() ? d->properties : Json::object();
        add_element(doc, std::move(element));
    }

    // An explicit title overwrites the first TITLE element's text
    // (Python truthiness check on the original argument).
    if (title && !title->empty()) {
        for (auto& element : doc.elements) {
            if (element.element_type == "title") {
                element.properties["text"] = *title;
                break;
            }
        }
    }
    return doc;
}

}  // namespace pwb::mapping_document
