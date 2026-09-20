// ui_pages_data.smoke — post-mortem completion of the UI-06 slice: the
// agent was terminated before writing tests, so this covers the ported
// cores' headline semantics (tag parsing, pdf zoom, filter chips +
// saved-filter payloads, activity fallback) against the Python contracts
// named in each header.

#include <pwb/ui_pages_data/activity.hpp>
#include <pwb/ui_pages_data/chips.hpp>
#include <pwb/ui_pages_data/pdf_zoom.hpp>
#include <pwb/ui_pages_data/tag_text.hpp>

#include <cstdio>
#include <string>
#include <vector>

using namespace pwb::ui_pages_data;
namespace domain = pwb::domain;

static int checks = 0;
static int failures = 0;

#define CHECK(cond)                                                        \
    do {                                                                   \
        ++checks;                                                          \
        if (!(cond)) {                                                     \
            ++failures;                                                    \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);    \
        }                                                                  \
    } while (0)

int main() {
    // --- parse_multi_tag_input (tag_widgets.parse_multi_tag_input) ------
    {
        // Separators [,，;；\s]+: ASCII + U+FF0C/U+FF1B + whitespace.
        const auto tags = parse_multi_tag_input(
            "  #砂岩 ,泥岩； 砂岩，砂岩 碳酸盐\n  #砂岩  ");
        CHECK(tags.size() == 3);
        CHECK(tags[0] == "砂岩" && tags[1] == "泥岩" && tags[2] == "碳酸盐");
        // First-occurrence order wins on duplicates.
        const auto dup = parse_multi_tag_input("b, a, b");
        CHECK(dup.size() == 2 && dup[0] == "b" && dup[1] == "a");
        // [:128] truncates in CHARACTERS, not bytes.
        const auto long_tag = parse_multi_tag_input(std::string(200, 'x'));
        CHECK(long_tag.size() == 1 && long_tag[0].size() == 128);
        CHECK(parse_multi_tag_input("  ， ； ").empty());
        // '、' is NOT a separator and not stripped (not whitespace/#).
        const auto ideo = parse_multi_tag_input("a、b");
        CHECK(ideo.size() == 1 && ideo[0] == "a、b");
    }

    // --- PdfZoomModel (data_detail_panel.PdfPreviewPanel) ---------------
    {
        PdfZoomModel zoom;
        CHECK(zoom.factor() == 1.0);
        CHECK(zoom.render_width() == 420 && zoom.render_height() == 560);
        CHECK(zoom.zoom_in() && zoom.factor() == 1.25);
        // Clamp at 8.00: repeated zoom-in saturates; an unchanged clamped
        // value returns false (label-only refresh in Python).
        while (zoom.factor() < 8.0) CHECK(zoom.zoom_in());
        CHECK(!zoom.zoom_in());
        CHECK(zoom.factor() == 8.0 && zoom.render_width() == 3360);
        // Floor clamp 0.10.
        PdfZoomModel lo;
        while (lo.factor() > 0.10) CHECK(lo.zoom_out());
        CHECK(!lo.zoom_out());
        CHECK(lo.factor() == 0.10 && lo.render_height() == 56);
        // Page guards: page_index_ < page_count - 1 / page_index_ > 0.
        PdfZoomModel nav;
        CHECK(nav.zoom_label() == "100%");
        CHECK(!nav.previous_page());
        CHECK(nav.next_page(3) && nav.page_index() == 1);
        CHECK(!nav.next_page(2));  // 1 < 2-1 is false → boundary, no move
        CHECK(nav.next_page(3) && nav.page_index() == 2);
        CHECK(!nav.next_page(3));
        // "{page_index + 1} / {page_count}" — "3 / 0" when doc is null.
        CHECK(nav.page_label(0) == "3 / 0");
        // Ctrl+wheel: delta < 0 zooms out; delta 0 falls into zoom_out.
        CHECK(nav.wheel(-120) && nav.wheel(0));
    }

    // --- filter chips (filter_chips_bar._dimensions) --------------------
    {
        FilterQuery q;
        CHECK(filter_dimensions(q).empty());  // node_type "all" → no chip
        q.node_type = "trash";
        q.search_text = "砂";
        q.stage = std::string("raw");
        q.data_type = std::string("seismic");
        q.tags = {"a", "b"};
        q.tag_operator = "or";
        q.asset_id = std::string("0123456789abcdefGHIJ");
        const auto dims = filter_dimensions(q);
        CHECK(dims.size() == 8);
        CHECK(dims[0].first == "view" && dims[0].second == "视图: 回收站");
        CHECK(dims[1].first == "text" && dims[1].second == "搜索: 砂");
        CHECK(dims[2].first == "stage" && dims[2].second == "阶段: raw");
        CHECK(dims[3].first == "type" && dims[3].second == "类型: seismic");
        CHECK(dims[4].first == "tag:a" && dims[4].second == "标签: a");
        CHECK(dims[5].first == "tag:b");
        // multi-tag → operator chip; "or" → "任一满足".
        CHECK(dims[6].first == "tag_operator" &&
              dims[6].second == "任一满足");
        // asset chip is a SECOND "view" dim, label truncated to 16 chars + …
        CHECK(dims[7].first == "view" &&
              dims[7].second == "资产: 0123456789abcdef…");
        // tag_operator chip only shows for multi-tag queries.
        FilterQuery single;
        single.tags = {"a"};
        for (const auto& d : filter_dimensions(single))
            CHECK(d.first != "tag_operator");

        // remove_filter_dimension — "view" clears node + asset together.
        const auto cleared = remove_filter_dimension(q, "view");
        CHECK(cleared && cleared->node_type == "all" &&
              !cleared->asset_id && cleared->stage);
        const auto no_text = remove_filter_dimension(q, "text");
        CHECK(no_text && no_text->search_text.empty());
        const auto no_tag = remove_filter_dimension(q, "tag:a");
        CHECK(no_tag && no_tag->tags.size() == 1 && no_tag->tags[0] == "b");
        const auto no_op = remove_filter_dimension(q, "tag_operator");
        CHECK(no_op && no_op->tag_operator == "and");
        CHECK(!remove_filter_dimension(q, "bogus"));
    }

    // --- saved filters payload (QSettings JSON) -------------------------
    {
        FilterQuery q;
        q.node_type = "integrity";
        q.stage = std::string("derived");
        q.tags = {"x"};
        const auto dict = filter_query_to_dict(q);
        const auto rt = filter_query_from_dict(dict);
        CHECK(rt && rt->node_type == "integrity" && rt->stage &&
              *rt->stage == "derived" && rt->tags.size() == 1);
        // #1391: malformed saved queries fail instead of silently resetting
        // to the "all" view (Python _apply_saved warns via except).
        CHECK(!filter_query_from_dict(domain::Json(42)).has_value());
        CHECK(!filter_query_from_dict(domain::Json::array()).has_value());
        {
            domain::Json bad = filter_query_to_dict(FilterQuery{});
            bad["tags"] = 7;  // list(<scalar>) raises in Python
            CHECK(!filter_query_from_dict(bad).has_value());
            domain::Json bad2 = filter_query_to_dict(FilterQuery{});
            bad2["node_type"] = 5;
            CHECK(!filter_query_from_dict(bad2).has_value());
        }
        CHECK(!dict.contains("asset_id"));  // only the 7 saved fields
        // Malformed payload → empty (Python returns {} on json failure).
        CHECK(saved_filters_load("not-json").empty());
        CHECK(saved_filters_load("{}").empty());  // non-list → empty
        // First-occurrence position kept; later duplicates overwrite value.
        const auto loaded = saved_filters_load(
            "[{\"name\":\"b\",\"query\":{}},{\"name\":\"a\",\"query\":{}},"
            "{\"name\":\"b\",\"query\":{\"stage\":\"raw\"}}]");
        CHECK(loaded.size() == 2);
        CHECK(loaded[0].first == "b" && loaded[1].first == "a");
        CHECK(loaded[0].second.at("stage") == "raw");
        const auto names = saved_filter_names_sorted(loaded);
        CHECK(names.size() == 2 && names[0] == "a" && names[1] == "b");
        // #1391: saved_filter_names_sorted is sorted(key=str.casefold) —
        // exercise non-ASCII folds so an ASCII-only fold regression fails.
        // Folded keys: "sigma-σ", "zulu", "ära" → 's'<'z'<'ä'(U+00E4);
        // an ASCII-only fold would leave "Ära" sorted first.
        const auto uni = saved_filter_names_sorted(
            {{"zulu", {}}, {"Ära", {}}, {"sigma-Σ", {}}});
        CHECK(uni.size() == 3 && uni[0] == "sigma-Σ" && uni[1] == "zulu" &&
              uni[2] == "Ära");
        // Empty-object query is a falsy stored payload — Python treats it
        // as a silent no-op, so from_dict must NOT turn it into an "all"
        // reset candidate at the widget layer (guarded in apply_saved).
        // from_dict({}) itself returns a valid all-default query (same
        // field defaults as FilterQuery()), which apply_saved now skips.
        CHECK(filter_query_from_dict(domain::Json::object()).has_value());
    }

    // --- activity entries (activity_card.update_state) -------------------
    {
        domain::Json state = domain::Json::object();
        // Non-pending steps produce "刚刚" entries; pending is filtered.
        const auto entries = compute_activity_entries(
            state, {ActivityStep{"well_log", "complete"},
                    ActivityStep{"pending", "pending"}});
        CHECK(entries.size() == 1 && entries[0].when == "刚刚");
        // Empty steps → evidence fallback scans counters in fixed order.
        state["resource_counts"] = {{"a", 2}, {"b", 3}};
        state["qc_issue_count"] = 7;
        const auto fb = compute_activity_entries(state, {});
        CHECK(fb.size() == 2);
        CHECK(fb[0].when == "工程" && fb[0].description == "数据资源: 5 项");
        CHECK(compute_activity_entries(domain::Json::object(), {}).empty());
    }

    std::printf("%s: %d checks, %d failures\n",
                failures == 0 ? "PASSED" : "FAILED", checks, failures);
    return failures == 0 ? 0 : 1;
}
