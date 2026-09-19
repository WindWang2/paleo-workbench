// Oracle replay test for the ui_pages_preview Qt-free cores (UI-07).
// Fixture: fixtures/ui_pages_preview_oracle.json — frozen from the real
// Python modules by tools/oracle/generate_ui_preview_fixtures.py.
//
// Seam notes carried over from the generator:
//  - fast_slice_to_indexed8 / global_stretch_range are numpy-bound kernels
//    — frozen as a deterministic sentinel; the real kernel is
//    libs/visualization's own oracle contract.
//  - Widget-observable sections (pdf.view_path/fallback structure, media
//    widget states, summary heights, settings_panel indexes, misc widget
//    states) are consumed by ui_pages_preview.qt_widgets_smoke; here only
//    the Qt-free semantics they reduce to are replayed.
//  - Cell-role probes (font/fg/bg/align) are frozen as role-presence +
//    alignment; the concrete palette colors are a Qt-side concern
//    (themed brushes), so the replay asserts the kind→role mapping.

#include <cstdio>
#include <fstream>
#include <map>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_pages_preview/image_zoom.hpp>
#include <pwb/ui_pages_preview/json_tree_spec.hpp>
#include <pwb/ui_pages_preview/lazy_tabs_state.hpp>
#include <pwb/ui_pages_preview/media_time.hpp>
#include <pwb/ui_pages_preview/pdf_zoom.hpp>
#include <pwb/ui_pages_preview/preview_settings.hpp>
#include <pwb/ui_pages_preview/preview_table.hpp>
#include <pwb/ui_pages_preview/seismic_slice_spec.hpp>
#include <pwb/ui_pages_preview/summary_chips.hpp>
#include <pwb/ui_pages_preview/url_filter.hpp>

#include "ui_pages_preview_test.hpp"

using pwb::domain::Json;
using pwb::domain::json_semantically_equal;
using namespace pwb::ui_pages_preview;

namespace {

Json load_oracle() {
    std::ifstream in(PWB_UI_PAGES_PREVIEW_ORACLE);
    if (!in) {
        std::fprintf(stderr, "cannot open oracle: %s\n",
                     PWB_UI_PAGES_PREVIEW_ORACLE);
        std::exit(2);
    }
    std::stringstream buffer;
    buffer << in.rdbuf();
    return Json::parse(buffer.str());
}

// C++ int fields serialize number_integer (signed); the Python fixture's
// positive ints re-parse as number_unsigned — and json_semantic_diff is
// type-strict. Round-tripping produced JSON through dump+parse normalizes
// the same way Python's json.dumps→file→json.load pipeline does.
Json normalized(const Json& produced) {
    return Json::parse(produced.dump());
}

// ---------------------------------------------------------------------------
// settings
// ---------------------------------------------------------------------------

Json settings_input_for(const std::string& label) {
    if (label == "empty") return Json::object();
    if (label == "subset_valid") {
        return Json{{"font_size", 20},
                    {"wrap_text", true},
                    {"pdf_fit_mode", "page"}};
    }
    if (label == "unknown_ignored") {
        return Json{{"no_such_key", 1}, {"font_size", 10}};
    }
    if (label == "bool_not_bool") return Json{{"wrap_text", 1}};
    if (label == "int_not_int") return Json{{"font_size", "12"}};
    if (label == "int_bool") return Json{{"font_size", true}};
    if (label == "below_min") return Json{{"font_size", 4}};
    if (label == "above_max") return Json{{"table_max_rows", 5000}};
    if (label == "bad_fit_mode") return Json{{"pdf_fit_mode", "stretch"}};
    if (label == "bad_density") return Json{{"density", "spacious"}};
    if (label == "bad_theme") return Json{{"theme_mode", "dark"}};
    return Json::object();
}

// Classify the C++ validation failure into the Python exception kind:
// type mismatches ("must be a …") → TypeError; range/enum → ValueError.
std::string error_kind(const std::string& message) {
    if (message.find("must be an integer") != std::string::npos ||
        message.find("must be a boolean") != std::string::npos ||
        message.find("must be a string") != std::string::npos) {
        return "TypeError";
    }
    return "ValueError";
}

// ---------------------------------------------------------------------------
// json tree — compare a JsonNode against the frozen spec
// ---------------------------------------------------------------------------

int node_mismatches(const JsonNode& node, const Json& spec,
                    const std::string& path) {
    int fails = 0;
    auto fail = [&](const char* field) {
        ++fails;
        std::fprintf(stderr, "json node mismatch at %s.%s\n", path.c_str(),
                     field);
    };
    if (node.key != spec.at("key").get<std::string>()) fail("key");
    if (node.label != spec.at("label").get<std::string>()) fail("label");
    const bool frozen_container = spec.at("has_container").get<bool>();
    if ((node.kind == JsonNodeKind::container_lazy) != frozen_container) {
        fail("has_container");
    }
    const bool frozen_more = spec.at("has_more").get<bool>();
    if ((node.kind == JsonNodeKind::sentinel) != frozen_more) {
        fail("has_more");
    }
    const Json& kids = spec.at("children");
    if (node.children.size() != kids.size()) {
        fail("children.size");
        return fails;
    }
    for (std::size_t i = 0; i < kids.size(); ++i) {
        fails += node_mismatches(node.children[i], kids[i],
                                 path + "/" + node.key);
    }
    return fails;
}

Json json_input_for_row_case(const std::string& label) {
    if (label == "scalar_str") return Json("hello");
    if (label == "scalar_int") return Json(42);
    if (label == "scalar_float") return Json(3.5);
    if (label == "scalar_true") return Json(true);
    if (label == "scalar_false") return Json(false);
    if (label == "scalar_none") return Json(nullptr);
    if (label == "small_dict") return Json{{"a", 1}, {"b", "x"}};
    if (label == "small_list") return Json{1, "a", nullptr};
    if (label == "lazy_dict") {
        Json d = Json::object();
        for (int i = 0; i < 5; ++i) d["k" + std::to_string(i)] = i;
        return d;
    }
    if (label == "lazy_list") return Json{0, 1, 2, 3, 4};
    if (label == "nested") {
        return Json{{"inner", Json{1, Json{{"deep", true}}}}};
    }
    return Json(nullptr);
}

Json json_input_for_tree_case(const std::string& label) {
    if (label == "dict_small") return Json{{"a", 1}, {"b", Json{1, 2}}};
    if (label == "dict_lazy_root") {
        Json d = Json::object();
        for (int i = 0; i < 5; ++i) d["k" + std::to_string(i)] = i;
        return d;
    }
    if (label == "list_root") return Json{1, 2};
    if (label == "scalar_root") return Json("just-a-string");
    return Json(nullptr);
}

// ---------------------------------------------------------------------------
// table cell probes — frozen role answers vs CellKind
// ---------------------------------------------------------------------------

struct RoleExpect {
    const char* font;  // "mono_bold" | "mono" | nullptr
    bool fg;
    bool bg;
    int align;  // -1 = null
};

RoleExpect role_expect(CellKind kind) {
    switch (kind) {
        case CellKind::depth:     return {"mono_bold", true, true, 130};
        case CellKind::curve_tag: return {"mono_bold", true, true, 132};
        case CellKind::curve_unit:return {"mono", true, false, 132};
        case CellKind::nan_number:return {"mono", true, false, 130};
        case CellKind::number:    return {"mono", false, false, 130};
        case CellKind::plain:     return {nullptr, false, false, -1};
    }
    return {nullptr, false, false, -1};
}

void check_cell_probes(const Json& cells,
                       const std::vector<std::string>& headers) {
    const int depth_col = depth_column(headers);
    const bool curve_def = is_curve_definition(headers);
    // frozen cells are row-major; headers.size() columns per row.
    const std::size_t ncols = headers.size();
    for (std::size_t i = 0; i < cells.size(); ++i) {
        const Json& cell = cells[i];
        const int col = static_cast<int>(i % ncols);
        const std::string display =
            cell.at("display").is_null()
                ? std::string()
                : cell.at("display").get<std::string>();
        const CellKind kind = cell_kind(display, col, depth_col, curve_def);
        const RoleExpect expect = role_expect(kind);

        const Json& font = cell.at("font");
        const std::string font_s =
            font.is_null() ? std::string() : font.get<std::string>();
        CHECK_EQ(font_s, expect.font ? std::string(expect.font)
                                     : std::string());
        CHECK_EQ(cell.at("fg").is_null() ? "" : "set",
                 expect.fg ? "set" : "");
        CHECK_EQ(cell.at("bg").is_null() ? "" : "set",
                 expect.bg ? "set" : "");
        const Json& align = cell.at("align");
        const int align_v = align.is_null() ? -1 : align.get<int>();
        CHECK_LL(align_v, expect.align);
    }
}

// ---------------------------------------------------------------------------
// lazy tabs — scenario op replay
// ---------------------------------------------------------------------------

std::string visual_name(VisualPage page) {
    switch (page) {
        case VisualPage::prompt:  return "prompt";
        case VisualPage::loading: return "loading";
        case VisualPage::message: return "message";
        case VisualPage::host:    return "host";
    }
    return "?";
}

void apply_lazy_op(LazyTabsState& state, const std::string& op) {
    if (op == "load_table" || op == "load_text" || op == "load_well_log") {
        state.load_summary();
    } else if (op == "click_tab1") {
        state.tab_changed(1);
    } else if (op == "loading" || op == "loading_bg") {
        state.show_loading();
    } else if (op == "preview") {
        state.show_preview(true);
    } else if (op == "preview_noactivate" || op == "preview_was_visual") {
        state.show_preview(false);
    } else if (op == "error_retry") {
        state.show_error(true, true);
    } else if (op == "error_fatal") {
        state.show_error(false, false);
    } else if (op == "retry") {
        state.request_retry();
    } else if (op == "reset") {
        state.reset();
    }
}

}  // namespace

// ===========================================================================

PWB_TEST(settings_defaults_and_fingerprint) {
    const Json oracle = load_oracle();
    const PreviewSettings s = PreviewSettings::defaults();
    CHECK(json_semantically_equal(normalized(s.to_mapping()),
                                  oracle.at("settings").at("defaults")));
    CHECK_EQ(s.fingerprint(),
             oracle.at("settings").at("fingerprint").get<std::string>());
}

PWB_TEST(settings_from_mapping_cases) {
    const Json oracle = load_oracle();
    for (const Json& c : oracle.at("settings").at("from_mapping_cases")) {
        const std::string label = c.at("label").get<std::string>();
        const Json input = settings_input_for(label);
        try {
            const PreviewSettings s = PreviewSettings::from_mapping(input);
            CHECK(c.at("ok").get<bool>());
            if (c.at("ok").get<bool>()) {
                CHECK(json_semantically_equal(normalized(s.to_mapping()),
                                              c.at("settings")));
            }
        } catch (const std::invalid_argument& e) {
            CHECK(!c.at("ok").get<bool>());
            CHECK_EQ(error_kind(e.what()),
                     c.at("kind").get<std::string>());
        }
    }
}

PWB_TEST(settings_mode_category) {
    const Json oracle = load_oracle();
    for (const auto& [mode, cat] :
         oracle.at("settings").at("mode_category").items()) {
        CHECK_EQ(mode_category(mode), cat.get<std::string>());
    }
}

PWB_TEST(table_is_number) {
    const Json oracle = load_oracle();
    for (const auto& [value, expected] :
         oracle.at("table").at("is_number").items()) {
        CHECK_EQ(is_number(value) ? "true" : "false",
                 expected.get<bool>() ? "true" : "false");
    }
}

PWB_TEST(table_depth_and_curve_detection) {
    const Json oracle = load_oracle();
    for (const Json& c : oracle.at("table").at("depth_cases")) {
        const std::vector<std::string> headers =
            c.at("headers").get<std::vector<std::string>>();
        CHECK_LL(depth_column(headers), c.at("depth_col").get<int>());
        CHECK_EQ(is_curve_definition(headers) ? "t" : "f",
                 c.at("curve_def").get<bool>() ? "t" : "f");
    }
    for (const Json& c : oracle.at("table").at("curve_cases")) {
        const std::vector<std::string> headers =
            c.at("headers").get<std::vector<std::string>>();
        CHECK_EQ(is_curve_definition(headers) ? "t" : "f",
                 c.at("curve_def").get<bool>() ? "t" : "f");
        CHECK_LL(depth_column(headers), c.at("depth_col").get<int>());
    }
}

PWB_TEST(table_truncation) {
    const Json oracle = load_oracle();
    for (const Json& c : oracle.at("table").at("truncation_cases")) {
        const TableTruncation t = table_truncation(
            c.at("rows").get<std::size_t>(), c.at("cols").get<std::size_t>());
        CHECK_LL(static_cast<long long>(t.keep_rows),
                 c.at("kept").get<long long>());
        CHECK_EQ(t.truncated ? "t" : "f",
                 c.at("truncated").get<bool>() ? "t" : "f");
        CHECK_EQ(t.message, c.at("message").get<std::string>());
    }
}

PWB_TEST(table_tsv_export) {
    const Json oracle = load_oracle();
    // copy_all for headers (a,b,c), rows ("1","2","3") / ("x") / ()
    const std::string tsv = table_to_tsv(
        {"a", "b", "c"}, {{"1", "2", "3"}, {"x"}, {}});
    CHECK_EQ(tsv, oracle.at("table").at("copy_all").get<std::string>());
    CHECK_EQ(table_to_tsv({}, {}),
             oracle.at("table").at("copy_all_empty").get<std::string>());
}

PWB_TEST(table_cell_kinds) {
    const Json oracle = load_oracle();
    check_cell_probes(oracle.at("table").at("depth_table_cells"),
                      {"DEPTH", "GR", "CALI"});
    check_cell_probes(oracle.at("table").at("curve_table_cells"),
                      {"曲线", "单位", "描述", "备注"});
    check_cell_probes(oracle.at("table").at("plain_table_cells"),
                      {"A", "B"});
}

PWB_TEST(table_cell_text_strips) {
    // " 80 " → "80", "  padded  " → "padded" (Python str.strip()).
    CHECK_EQ(table_cell_text(" 80 "), "80");
    CHECK_EQ(table_cell_text("  padded  "), "padded");
    CHECK_EQ(table_cell_text("\t x \n"), "x");
}

PWB_TEST(json_tree_row_cases) {
    const Json oracle = load_oracle();
    int fails = 0;
    for (const Json& c : oracle.at("json_tree").at("row_cases")) {
        const std::string label = c.at("case").get<std::string>();
        const JsonNode node = build_row(
            "k", json_input_for_row_case(label), /*threshold=*/3, /*depth=*/0);
        fails += node_mismatches(node, c.at("spec"), label);
    }
    CHECK(fails == 0);
}

PWB_TEST(json_tree_depth_cap) {
    const Json oracle = load_oracle();
    const JsonNode node = build_row("k", Json{{"a", 1}}, /*threshold=*/3,
                                    /*depth=*/64);
    int fails = node_mismatches(node, oracle.at("json_tree").at("depth_cap"),
                                "depth_cap");
    CHECK(fails == 0);
}

PWB_TEST(json_tree_root_trees) {
    const Json oracle = load_oracle();
    int fails = 0;
    for (const Json& c : oracle.at("json_tree").at("trees")) {
        const std::string label = c.at("case").get<std::string>();
        const std::vector<JsonNode> rows =
            build_tree(json_input_for_tree_case(label), /*threshold=*/3);
        const Json& frozen = c.at("tree");
        if (rows.size() != frozen.size()) {
            ++fails;
            continue;
        }
        for (std::size_t i = 0; i < rows.size(); ++i) {
            fails += node_mismatches(rows[i], frozen[i], label);
        }
    }
    CHECK(fails == 0);
}

PWB_TEST(json_tree_container_items) {
    const Json oracle = load_oracle();
    {
        Json container = Json::array();
        for (int i = 0; i < 7; ++i) container.push_back("item" + std::to_string(i));
        const auto items = container_items(container);
        const Json& frozen =
            oracle.at("json_tree").at("container_items_list");
        CHECK(items.size() == frozen.size());
        const std::size_t n = std::min(items.size(), frozen.size());
        for (std::size_t i = 0; i < n; ++i) {
            CHECK_EQ(items[i].first, frozen[i][0].get<std::string>());
            CHECK_EQ(scalar_label(items[i].second),
                     frozen[i][1].get<std::string>());
        }
    }
    {
        const Json container = Json{{"a", 1}, {"b", 2}};
        const auto items = container_items(container);
        const Json& frozen =
            oracle.at("json_tree").at("container_items_dict");
        CHECK(items.size() == frozen.size());
        const std::size_t n = std::min(items.size(), frozen.size());
        for (std::size_t i = 0; i < n; ++i) {
            CHECK_EQ(items[i].first, frozen[i][0].get<std::string>());
            CHECK_EQ(scalar_label(items[i].second),
                     frozen[i][1].get<std::string>());
        }
    }
}

PWB_TEST(json_tree_batch_and_sentinel) {
    const Json oracle = load_oracle();
    const Json& trace = oracle.at("json_tree").at("batch_trace");

    Json container = Json::array();
    for (int i = 0; i < 4500; ++i) container.push_back(i);

    std::vector<JsonNode> out;
    const std::size_t off1 =
        append_batch(container, 0, /*threshold=*/3, /*depth=*/0, out);
    CHECK_LL(static_cast<long long>(off1), trace.at("off1").get<long long>());
    const JsonNode s1 = sentinel_node(container, off1);
    CHECK_EQ(s1.key, trace.at("sentinel1")[0].get<std::string>());
    CHECK_EQ(s1.label, std::string());
    CHECK(s1.children.size() == 1);
    if (!s1.children.empty()) {
        CHECK_EQ(s1.children[0].key, "（点击左侧箭头加载）");
    }

    const std::size_t off2 =
        append_batch(container, off1, /*threshold=*/3, /*depth=*/0, out);
    CHECK_LL(static_cast<long long>(off2), trace.at("off2").get<long long>());
    const JsonNode s2 = sentinel_node(container, off2);
    CHECK_EQ(s2.key, trace.at("sentinel2")[0].get<std::string>());

    const std::size_t off3 =
        append_batch(container, off2, /*threshold=*/3, /*depth=*/0, out);
    CHECK_LL(static_cast<long long>(off3), trace.at("off3").get<long long>());
    CHECK(off3 >= container.size());  // exhausted → no sentinel
}

PWB_TEST(pdf_zoom_sequences) {
    const Json oracle = load_oracle();
    int percent = 100;
    for (const Json& step : oracle.at("pdf").at("zoom_sequences")) {
        const std::string op = step.at("op").get<std::string>();
        if (op == "in") {
            percent = pdf_zoom_in(percent).percent;
        } else if (op == "out") {
            percent = pdf_zoom_out(percent).percent;
        } else if (op == "in@790") {
            percent = pdf_zoom_in(790).percent;
        } else if (op == "out@11") {
            percent = pdf_zoom_out(11).percent;
        } else {
            continue;  // fit_page / fit_width are widget-mode ops
        }
        CHECK_LL(percent, step.at("percent").get<int>());
        CHECK_EQ(std::to_string(percent) + "%",
                 step.at("zoom_label").get<std::string>());
    }
}

PWB_TEST(pdf_page_status) {
    const Json oracle = load_oracle();
    const Json& vp = oracle.at("pdf").at("view_path");
    CHECK_EQ(pdf_page_status(0, 3),
             vp.at("page_label_after_load").get<std::string>());
    CHECK_EQ(pdf_prev_enabled(0) ? "t" : "f",
             vp.at("prev_enabled").get<bool>() ? "t" : "f");
    CHECK_EQ(pdf_next_enabled(0, 3) ? "t" : "f",
             vp.at("next_enabled").get<bool>() ? "t" : "f");
    CHECK_EQ(pdf_page_status(1, 3),
             vp.at("after_next").at("page_label").get<std::string>());
    CHECK_EQ(pdf_prev_enabled(1) ? "t" : "f",
             vp.at("after_next").at("prev_enabled").get<bool>() ? "t" : "f");
    CHECK_EQ(pdf_next_enabled(1, 3) ? "t" : "f",
             vp.at("after_next").at("next_enabled").get<bool>() ? "t" : "f");
    CHECK_EQ(pdf_page_status(2, 3),
             vp.at("after_next3").at("page_label").get<std::string>());
    CHECK_EQ(pdf_next_enabled(2, 3) ? "t" : "f",
             vp.at("after_next3").at("next_enabled").get<bool>() ? "t" : "f");
    CHECK_EQ(pdf_page_status(0, 3),
             vp.at("page_sync").at("label").get<std::string>());

    const Json& fb = oracle.at("pdf").at("fallback");
    CHECK_EQ(pdf_page_status(0, 4),
             fb.at("page_label").get<std::string>());
    CHECK_EQ(pdf_page_status(3, 4),
             fb.at("after_next").at("page_label").get<std::string>());
    CHECK_EQ(pdf_page_status(2, 4),
             fb.at("scroll_mid").at("page_label").get<std::string>());

    CHECK_EQ(pdf_page_status(-1, 0), "0 / 0");  // unavailable widget start
}

PWB_TEST(image_zoom_and_pan) {
    const Json oracle = load_oracle();
    CHECK_NEAR(image_zoom_clamp(100.0), 8.0, 1e-9);
    CHECK_NEAR(image_zoom_clamp(0.0001), 0.1, 1e-9);
    const auto vs = image_virtual_size(2000, 1000, 2.0);
    CHECK_LL(vs.first, oracle.at("image").at("virtual_size")[0].get<int>());
    CHECK_LL(vs.second, oracle.at("image").at("virtual_size")[1].get<int>());
    CHECK(image_virtual_size(0, 0, 1.0) == std::make_pair(0, 0));
    for (const Json& c : oracle.at("image").at("pan_cases")) {
        const PanOffset p = image_clamp_pan(
            c.at("in")[0].get<int>(), c.at("in")[1].get<int>(),
            /*pix_w=*/2000, /*pix_h=*/1000, /*zoom=*/2.0,
            /*widget_w=*/800, /*widget_h=*/600);
        CHECK_LL(p.x, c.at("out")[0].get<int>());
        CHECK_LL(p.y, c.at("out")[1].get<int>());
    }
}

PWB_TEST(media_time) {
    const Json oracle = load_oracle();
    for (const auto& [ms_str, expected] :
         oracle.at("media").at("ms").items()) {
        CHECK_EQ(media_ms_to_mmss(std::stoll(ms_str)),
                 expected.get<std::string>());
    }
    CHECK_EQ(media_time_label(61000, 125000), "01:01 / 02:05");
}

PWB_TEST(url_and_resource_filters) {
    const Json oracle = load_oracle();
    for (const auto& [scheme, allowed] :
         oracle.at("web").at("intercept_allowed").items()) {
        CHECK_EQ(local_scheme_allowed(scheme) ? "t" : "f",
                 allowed.get<bool>() ? "t" : "f");
        CHECK_EQ(local_scheme_allowed(scheme) ? "t" : "f",
                 oracle.at("web").at("nav_allowed").at(scheme).get<bool>()
                     ? "t" : "f");
    }
    for (const auto& [scheme, allowed] :
         oracle.at("misc_widgets").at("rich_text").at("resource_allowed")
             .items()) {
        CHECK_EQ(resource_scheme_allowed(scheme) ? "t" : "f",
                 allowed.get<bool>() ? "t" : "f");
    }
}

PWB_TEST(seismic_axes_and_slider) {
    const Json oracle = load_oracle();
    const auto labels = seismic_axis_labels();
    const Json& frozen_labels = oracle.at("seismic").at("combo_items");
    CHECK(labels.size() == frozen_labels.size());
    for (std::size_t i = 0; i < std::min(labels.size(), frozen_labels.size());
         ++i) {
        CHECK_EQ(labels[i], frozen_labels[i].get<std::string>());
    }
    for (const Json& c : oracle.at("seismic").at("slider_ranges")) {
        const auto shape = c.at("shape").get<std::vector<long long>>();
        const int axis = c.at("axis").get<int>();
        const long long axis_size = shape[static_cast<std::size_t>(axis)];
        CHECK_LL(seismic_slider_max(axis_size),
                 c.at("slider_max").get<long long>());
        const long long value = seismic_slider_value(axis_size);
        CHECK_LL(value, c.at("slider_value").get<long long>());
        CHECK_EQ(seismic_index_label(value, seismic_slider_max(axis_size)),
                 c.at("index_label").get<std::string>());
    }
    CHECK_EQ(seismic_index_label(0, 0), "0 / 0");
}

PWB_TEST(seismic_ramp_color_table) {
    const Json oracle = load_oracle();
    const std::vector<std::uint32_t> table = seismic_color_table();
    const Json& render = oracle.at("seismic").at("render");
    CHECK_LL(static_cast<long long>(table.size()),
             render.at("color_table_len").get<long long>());
    const std::vector<int> sample_idx = {0, 1, 64, 128, 192, 255};
    const Json& samples = render.at("color_table_samples");
    for (std::size_t i = 0; i < sample_idx.size(); ++i) {
        char buf[16];
        std::snprintf(buf, sizeof(buf), "0x%08x",
                      table[static_cast<std::size_t>(sample_idx[i])]);
        CHECK_EQ(std::string(buf), samples[i].get<std::string>());
    }
}

PWB_TEST(summary_chips_sticky) {
    const Json oracle = load_oracle();
    // Chip defaults before any load.
    std::string well = "—";
    std::string curves = "0 条";
    std::string samples = "0 点";
    for (const Json& c : oracle.at("summary").at("chip_cases")) {
        std::vector<std::pair<std::string, std::string>> rows;
        for (const Json& r : c.at("rows")) {
            rows.emplace_back(r[0].get<std::string>(),
                              r[1].get<std::string>());
        }
        const SummaryChipValues chips = summary_chip_values(rows);
        if (chips.well) well = *chips.well;
        if (chips.curves) curves = *chips.curves;
        if (chips.samples) samples = *chips.samples;
        CHECK_EQ(well, c.at("well").get<std::string>());
        CHECK_EQ(curves, c.at("curves").get<std::string>());
        CHECK_EQ(samples, c.at("samples").get<std::string>());
    }
    CHECK_EQ(thousands_grouped(1234567), "1,234,567");
    CHECK_EQ(thousands_grouped(-42000), "-42,000");
}

PWB_TEST(lazy_tabs_scenarios) {
    const Json oracle = load_oracle();
    for (const Json& scenario : oracle.at("lazy_tabs").at("scenarios")) {
        LazyTabsState state;
        bool saw_host = false;
        for (const Json& step : scenario.at("steps")) {
            apply_lazy_op(state, step.at("op").get<std::string>());
            CHECK_LL(state.current_tab, step.at("tab").get<long long>());
            CHECK_EQ(visual_name(state.visual),
                     step.at("visual").get<std::string>());
            CHECK_EQ(state.requested ? "t" : "f",
                     step.at("requested").get<bool>() ? "t" : "f");
            if (state.visual == VisualPage::host) saw_host = true;
            CHECK_EQ(saw_host ? "t" : "f",
                     step.at("host_created").get<bool>() ? "t" : "f");
        }
        long long emitted = 0;
        for (const Json& e : scenario.at("emitted")) {
            if (e.get<std::string>() == "visualization_requested") ++emitted;
        }
        CHECK_LL(state.visualization_emitted, emitted);
    }
}

// Negative self-check: every section must detect tampering.
PWB_TEST(negative_selfcheck) {
    const Json oracle = load_oracle();
    {
        Json t = oracle;
        t["settings"]["fingerprint"] = "0000000000000000";
        CHECK(t.at("settings").at("fingerprint").get<std::string>() !=
              PreviewSettings::defaults().fingerprint());
    }
    {
        Json t = oracle;
        t["media"]["ms"]["1000"] = "99:99";
        CHECK(media_ms_to_mmss(1000) !=
              t.at("media").at("ms").at("1000").get<std::string>());
    }
    {
        Json t = oracle;
        t["table"]["truncation_cases"][2]["message"] = "tampered";
        const TableTruncation tt = table_truncation(300000, 5);
        CHECK(tt.message != t.at("table").at("truncation_cases")[2]
                                .at("message").get<std::string>());
    }
    {
        Json t = oracle;
        t["json_tree"]["depth_cap"]["label"] = "tampered";
        const JsonNode node = build_row("k", Json{{"a", 1}}, 3, 64);
        CHECK(node.label !=
              t.at("json_tree").at("depth_cap").at("label").get<std::string>());
    }
    {
        Json t = oracle;
        t["lazy_tabs"]["scenarios"][0]["steps"][1]["requested"] = false;
        LazyTabsState state;
        state.tab_changed(1);
        CHECK(state.requested != t.at("lazy_tabs").at("scenarios")[0]
                                     .at("steps")[1].at("requested")
                                     .get<bool>());
    }
}

int main() { return pwb_test::run_all(); }
