// CONV-27 — implementation of the componentized map template library.
// The factor-map factory mirrors templates.py geometry exactly; the other
// four factories compose the same components (D-4).
#include <pwb/cartography/templates.hpp>

#include <cmath>
#include <cstdio>
#include <stdexcept>

namespace pwb::cartography {

namespace {

ComposerElement make_element(const char* id, const char* element_type,
                             double x_mm, double y_mm, double width_mm,
                             double height_mm, long long z_index,
                             Json properties) {
    ComposerElement element;
    element.id = id;
    element.element_type = element_type;
    element.x_mm = x_mm;
    element.y_mm = y_mm;
    element.width_mm = width_mm;
    element.height_mm = height_mm;
    element.z_index = z_index;
    element.properties = std::move(properties);
    return element;
}

}  // namespace

TemplatePage TemplatePage::a4(const std::string& paper_size,
                              const std::string& orientation) {
    // templates.py: is_landscape = orientation.lower() == "landscape";
    // landscape 297x210, otherwise 210x297. The VERBATIM string persists
    // (templates.py:53 orientation=orientation) — only the branch tests
    // the lowercased form.
    TemplatePage page;
    page.paper_size = paper_size;
    page.orientation = orientation;
    std::string lowered = orientation;
    for (char& c : lowered) {
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + 32);
    }
    if (lowered == "landscape") {
        page.width_mm = 297.0;
        page.height_mm = 210.0;
    } else {
        page.width_mm = 210.0;
        page.height_mm = 297.0;
    }
    return page;
}

std::array<double, 4> TemplatePage::main_map_rect() const {
    // map_w = width - margin_x*2 - 50; map_h = height - margin_y*2 - title_h.
    const double map_w = width_mm - margin_x_mm * 2 - 50.0;
    const double map_h = height_mm - margin_y_mm * 2 - title_height_mm;
    return {margin_x_mm, margin_y_mm + title_height_mm, map_w, map_h};
}

std::array<double, 4> TemplatePage::legend_rect() const {
    const auto map_rect = main_map_rect();
    const double legend_x = map_rect[0] + map_rect[2] + 5.0;
    const double legend_y = map_rect[1];
    const double legend_h = std::min(map_rect[3], legend_max_height_mm);
    return {legend_x, legend_y, legend_width_mm, legend_h};
}

void add_title_block(Composition& doc, const TemplatePage& page,
                     const std::string& text) {
    Json properties = Json::object();
    properties["text"] = text;
    add_element(doc, make_element("elem_title", "title", page.margin_x_mm,
                                 page.margin_y_mm,
                                 page.width_mm - page.margin_x_mm * 2,
                                 page.title_height_mm, 10,
                                 std::move(properties)));
}

void add_subtitle(Composition& doc, const TemplatePage& page,
                  const std::string& text) {
    Json properties = Json::object();
    properties["text"] = text;
    properties["font_size"] = 11.0;
    properties["align"] = "center";
    add_element(doc, make_element("elem_subtitle", "subtitle", page.margin_x_mm,
                                 page.margin_y_mm + page.title_height_mm,
                                 page.width_mm - page.margin_x_mm * 2, 8.0, 9,
                                 std::move(properties)));
}

void add_main_map(Composition& doc, const TemplatePage& page,
                  const std::string& map_document_id, long long map_layer_count,
                  const std::array<double, 4>& extent) {
    // properties["map_document"] serializes as the composer stub
    // {"__ref__", "id", "layer_count"} (_serialize_property_value); the
    // extent rides as a plain list.
    Json properties = Json::object();
    Json stub = Json::object();
    stub["__ref__"] = "map_document";
    stub["id"] = map_document_id;
    stub["layer_count"] = map_layer_count;
    properties["map_document"] = std::move(stub);
    Json extent_json = Json::array();
    for (double v : extent) extent_json.push_back(v);
    properties["extent"] = std::move(extent_json);
    const auto rect = page.main_map_rect();
    add_element(doc, make_element("elem_main_map", "main_map", rect[0], rect[1],
                                 rect[2], rect[3], 1, std::move(properties)));
}

void add_north_arrow(Composition& doc, const TemplatePage& page) {
    const auto rect = page.main_map_rect();
    add_element(doc, make_element("elem_north_arrow", "north_arrow",
                                 rect[0] + 5.0, rect[1] + 5.0, 10.0, 14.0, 15,
                                 Json::object()));
}

void add_scale_bar(Composition& doc, const TemplatePage& page,
                   double extent_x_span) {
    // length_km = max(5, int(span / 4.0)) if span > 10 else 10 (int() is a
    // truncation toward zero).
    const double span = std::fabs(extent_x_span);
    const long long length_km =
        span > 10.0 ? std::max(5LL, static_cast<long long>(span / 4.0)) : 10;
    Json properties = Json::object();
    properties["length_km"] = length_km;
    const auto rect = page.main_map_rect();
    add_element(doc, make_element("elem_scale_bar", "scale_bar", rect[0] + 6.0,
                                 rect[1] + rect[3] - 12.0, 30.0, 8.0, 15,
                                 std::move(properties)));
}

void add_legend_rail(Composition& doc, const TemplatePage& page) {
    const auto rect = page.legend_rect();
    add_element(doc, make_element("elem_legend", "legend", rect[0], rect[1],
                                 rect[2], rect[3], 10, Json::object()));
}

void add_colorbar(Composition& doc, const TemplatePage& page,
                  const std::string& title, const std::string& units,
                  double vmin, double vmax) {
    const auto rect = page.legend_rect();
    Json properties = Json::object();
    properties["title"] = title;
    properties["min"] = vmin;
    properties["max"] = vmax;
    if (!units.empty()) properties["units"] = units;
    properties["discrete"] = false;
    add_element(doc, make_element(
        "elem_colorbar", "colorbar", rect[0], rect[1] + rect[3] + 4.0,
        rect[2], 14.0, 11, std::move(properties)));
}

void add_datasource(Composition& doc, const TemplatePage& page,
                    const std::string& text) {
    Json properties = Json::object();
    properties["text"] = text;
    properties["font_size"] = 7.0;
    add_element(doc, make_element(
        "elem_datasource", "datasource", page.margin_x_mm,
        page.height_mm - page.margin_y_mm, page.width_mm - page.margin_x_mm * 2,
        6.0, 12, std::move(properties)));
}

namespace {

// Title fallback shared with the Python factory:
// title or map_doc.title or f"{factor_name} 平面分布图".
std::string resolve_title(const TemplateRequest& request,
                          const char* fallback_format) {
    if (!request.title.empty()) return request.title;
    if (!request.map.map_document_title.empty()) {
        return request.map.map_document_title;
    }
    char buf[512];
    std::snprintf(buf, sizeof(buf), fallback_format,
                  request.factor_name.c_str());
    return buf;
}

Composition begin_composition(const TemplateRequest& request,
                              const TemplatePage& page,
                              const std::string& title) {
    Composition doc;
    doc.id = "comp_" + request.map.map_document_id;
    doc.title = title;
    doc.paper_size = page.paper_size;
    doc.orientation = page.orientation;
    doc.width_mm = page.width_mm;
    doc.height_mm = page.height_mm;
    doc.dpi = page.dpi;
    doc.metadata = Json::object();  // Python dict(self.metadata) == {}
    return doc;
}

}  // namespace

Composition geological_factor_map_template(const TemplateRequest& request) {
    const TemplatePage page = TemplatePage::a4(request.paper_size,
                                               request.orientation);
    const std::string title = resolve_title(request, "%s 平面分布图");
    Composition doc = begin_composition(request, page, title);
    add_title_block(doc, page, title);
    add_main_map(doc, page, request.map.map_document_id,
                 request.map.map_layer_count, request.map.extent);
    add_north_arrow(doc, page);
    add_scale_bar(doc, page, request.map.extent[2] - request.map.extent[0]);
    add_legend_rail(doc, page);
    return doc;
}

Composition facies_map_template(const TemplateRequest& request) {
    const TemplatePage page = TemplatePage::a4(request.paper_size,
                                               request.orientation);
    const std::string title = resolve_title(request, "%s 沉积相分布图");
    Composition doc = begin_composition(request, page, title);
    add_title_block(doc, page, title);
    if (!request.factor_name.empty()) {
        std::string subtitle = "沉积相: " + request.factor_name;
        if (!request.unit.empty()) subtitle += " (" + request.unit + ")";
        add_subtitle(doc, page, subtitle);
    }
    add_main_map(doc, page, request.map.map_document_id,
                 request.map.map_layer_count, request.map.extent);
    add_north_arrow(doc, page);
    add_scale_bar(doc, page, request.map.extent[2] - request.map.extent[0]);
    add_legend_rail(doc, page);
    return doc;
}

Composition prediction_map_template(const TemplateRequest& request) {
    const TemplatePage page = TemplatePage::a4(request.paper_size,
                                               request.orientation);
    const std::string title = resolve_title(request, "%s 预测分布图");
    Composition doc = begin_composition(request, page, title);
    add_title_block(doc, page, title);
    add_main_map(doc, page, request.map.map_document_id,
                 request.map.map_layer_count, request.map.extent);
    add_north_arrow(doc, page);
    add_scale_bar(doc, page, request.map.extent[2] - request.map.extent[0]);
    add_legend_rail(doc, page);
    add_colorbar(doc, page, request.factor_name, request.unit,
                 request.map.extent[0], request.map.extent[2]);
    return doc;
}

Composition constraint_map_template(const TemplateRequest& request) {
    const TemplatePage page = TemplatePage::a4(request.paper_size,
                                               request.orientation);
    const std::string title = resolve_title(request, "%s 约束条件图");
    Composition doc = begin_composition(request, page, title);
    add_title_block(doc, page, title);
    add_main_map(doc, page, request.map.map_document_id,
                 request.map.map_layer_count, request.map.extent);
    add_north_arrow(doc, page);
    add_scale_bar(doc, page, request.map.extent[2] - request.map.extent[0]);
    add_legend_rail(doc, page);
    add_datasource(doc, page, "约束边界数据以符号库 constraint 词条为准");
    return doc;
}

Composition comprehensive_map_template(const TemplateRequest& request) {
    const TemplatePage page = TemplatePage::a4(request.paper_size,
                                               request.orientation);
    const std::string title = resolve_title(request, "%s 综合古地理图");
    Composition doc = begin_composition(request, page, title);
    add_title_block(doc, page, title);
    add_main_map(doc, page, request.map.map_document_id,
                 request.map.map_layer_count, request.map.extent);
    add_north_arrow(doc, page);
    add_scale_bar(doc, page, request.map.extent[2] - request.map.extent[0]);
    add_legend_rail(doc, page);
    add_datasource(doc, page, "综合图: 相带、边界与参考底图叠加");
    return doc;
}

Json template_catalog() {
    struct Entry {
        const char* name;
        const char* title;
        const char* description;
    };
    static const Entry kCatalog[] = {
        {"factor_map", "地质因子图",
         "title + main map + north arrow + scale bar + legend (Python-parity "
         "factor map)"},
        {"facies_map", "沉积相图",
         "factor components + subtitle; facies class legend rail"},
        {"prediction_map", "预测成果图",
         "factor components + colorbar bound to the prediction ramp"},
        {"constraint_map", "约束条件图",
         "factor components + datasource footnote for constraint symbolry"},
        {"comprehensive_map", "综合古地理图",
         "factor components + datasource footnote; union composition"},
    };
    Json catalog = Json::array();
    for (const Entry& entry : kCatalog) {
        Json row = Json::object();
        row["name"] = entry.name;
        row["title"] = entry.title;
        row["description"] = entry.description;
        catalog.push_back(std::move(row));
    }
    return catalog;
}

Composition instantiate_template(const TemplateRequest& request) {
    if (request.template_name == "factor_map") {
        return geological_factor_map_template(request);
    }
    if (request.template_name == "facies_map") {
        return facies_map_template(request);
    }
    if (request.template_name == "prediction_map") {
        return prediction_map_template(request);
    }
    if (request.template_name == "constraint_map") {
        return constraint_map_template(request);
    }
    if (request.template_name == "comprehensive_map") {
        return comprehensive_map_template(request);
    }
    std::vector<std::string> names;
    for (const Json& row : template_catalog()) {
        names.push_back(row.at("name").get<std::string>());
    }
    std::string listing;
    for (std::size_t i = 0; i < names.size(); ++i) {
        if (i > 0) listing += ", ";
        listing += "'" + names[i] + "'";
    }
    throw std::out_of_range("unknown template '" + request.template_name +
                            "'; available: [" + listing + "]");
}

}  // namespace pwb::cartography
