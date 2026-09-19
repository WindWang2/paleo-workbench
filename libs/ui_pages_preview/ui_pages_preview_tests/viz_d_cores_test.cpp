// VIZ-D — Qt-free 核心的 oracle 校验（井位散点 + 井分层预览）。
// 井位侧断言 geoviz/previews/dat.py `_well_head_payload` /
// `XYScatterBackend.prepare` 的冻结语义（错误文案、issue 上限、
// 元数据合并/来源、警告拼接、汇总行）；井分层侧断言
// parse_well_tops_text 真实结果的分组/统计/文本表。headless、无 Qt。

#include <optional>
#include <string>
#include <vector>

#include <pwb/ingest/well_parsers.hpp>
#include <pwb/ui_pages_preview/formation_tops_preview.hpp>
#include <pwb/ui_pages_preview/well_head_scatter_core.hpp>

#include "ui_pages_preview_test.hpp"

using namespace pwb::ui_pages_preview;
using pwb::ui_pages_preview::xy_scatter::WellHeadScatterOptions;

namespace {

// 覆盖：标记、列声明（含 UWI）、CRS/单位声明、带引号井名、坏行四种。
const char* kGoodWellHead =
    "# WellHead File From SMI\n"
    "# Name X Y UWI\n"
    "# Source CRS: EPSG:4326\n"
    "# X .m\n"
    "# Y .m\n"
    "\n"
    "W-1 100.5 200.25 11001\n"
    "\"W ell 2\" -1e2 3.5 11002\n"
    "Bad notnum 1.0 11003\n"
    "W-3 1 2 3 4\n"
    "W-4 nan 5.5 11004\n"
    "W-5 7.5 inf 11005\n";

}  // namespace

PWB_TEST(well_head_scatter_parses_rows_and_metadata) {
    const auto result = xy_scatter::build_well_head_scatter(kGoodWellHead);
    CHECK(result.ok);
    CHECK_EQ(result.error, "");
    CHECK_EQ(result.detail, "");
    CHECK(!result.resource_limit);

    const auto& payload = result.payload;
    CHECK_LL(static_cast<long long>(payload.names.size()), 2);
    CHECK_EQ(payload.names[0], "W-1");
    CHECK_EQ(payload.names[1], "W ell 2");  // shlex 去引号
    CHECK_NEAR(payload.x[0], 100.5, 1e-12);
    CHECK_NEAR(payload.x[1], -100.0, 1e-12);
    CHECK_NEAR(payload.y[0], 200.25, 1e-12);
    CHECK_NEAR(payload.y[1], 3.5, 1e-12);
    CHECK_EQ(payload.uwis[0], "11001");
    CHECK_EQ(payload.uwis[1], "11002");
    CHECK_LL(payload.record_ids[0], 0);
    CHECK_LL(payload.record_ids[1], 1);
    CHECK_LL(payload.source_rows[0], 7);  // 1 基物理行号（含表头/空行）
    CHECK_LL(payload.source_rows[1], 8);

    CHECK_LL(payload.total_records, 6);
    CHECK_LL(payload.valid_records, 2);
    CHECK_LL(payload.skipped_count(), 4);
    CHECK_LL(static_cast<long long>(payload.issues.size()), 4);
    CHECK_LL(payload.omitted_issue_count, 0);
    CHECK_EQ(payload.issues[0].reason, "X 坐标不是有限数值");
    CHECK_LL(payload.issues[0].source_row, 9);
    CHECK_EQ(payload.issues[1].reason, "列数与声明不一致");
    CHECK_EQ(payload.issues[2].reason, "X 坐标不是有限数值");  // nan
    CHECK_EQ(payload.issues[3].reason, "Y 坐标不是有限数值");  // inf

    CHECK_EQ(payload.source_crs, "EPSG:4326");
    CHECK_EQ(payload.coordinate_units, "m");
    CHECK_EQ(payload.source_crs_provenance, "file");
    CHECK_EQ(payload.coordinate_units_provenance, "file");
    CHECK(!payload.comparison_matches_source.has_value());
}

PWB_TEST(well_head_scatter_view_spec_matches_backend_prepare) {
    const auto result = xy_scatter::build_well_head_scatter(kGoodWellHead);
    const auto spec = xy_scatter::make_scatter_view_spec(result.payload, "井位");
    CHECK_EQ(spec.title, "井位");
    CHECK_EQ(spec.x_axis_label, "X (m)");
    CHECK_EQ(spec.y_axis_label, "Y (m)");
    CHECK_LL(static_cast<long long>(spec.warnings.size()), 1);
    CHECK_EQ(spec.warnings[0], "4 行已跳过；有效 2/6");
    CHECK_EQ(spec.warning, "4 行已跳过；有效 2/6");
    CHECK_LL(static_cast<long long>(spec.summary_rows.size()), 2);
    CHECK_EQ(spec.summary_rows[0].first, "有效井数");
    CHECK_EQ(spec.summary_rows[0].second, "2");
    CHECK_EQ(spec.summary_rows[1].first, "源记录");
    CHECK_EQ(spec.summary_rows[1].second, "6");
}

PWB_TEST(well_head_scatter_comparison_mismatch_warning) {
    WellHeadScatterOptions options;
    options.comparison_crs = "EPSG:32650";
    const auto result = xy_scatter::build_well_head_scatter(kGoodWellHead, options);
    CHECK(result.ok);
    CHECK(result.payload.comparison_matches_source.has_value());
    CHECK(*result.payload.comparison_matches_source == false);
    const auto spec =
        xy_scatter::make_scatter_view_spec(result.payload, "井位");
    CHECK_LL(static_cast<long long>(spec.warnings.size()), 2);
    CHECK_EQ(spec.warnings[0], "4 行已跳过；有效 2/6");
    CHECK_EQ(spec.warnings[1],
             "SourceCRS EPSG:4326 与参考 CRS EPSG:32650 不同（未转换）");
    CHECK_EQ(spec.warning,
             "4 行已跳过；有效 2/6 · SourceCRS EPSG:4326 与参考 CRS "
             "EPSG:32650 不同（未转换）");
}

PWB_TEST(well_head_scatter_undeclared_metadata_warnings) {
    const char* bare =
        "# WellHead File From SMI\n"
        "# Well X Y\n"
        "A1 1 2\n";
    const auto result = xy_scatter::build_well_head_scatter(bare);
    CHECK(result.ok);
    CHECK_EQ(result.payload.source_crs, "");
    CHECK_EQ(result.payload.coordinate_units, "");
    CHECK_EQ(result.payload.source_crs_provenance, "undeclared");
    CHECK_EQ(result.payload.coordinate_units_provenance, "unknown");
    const auto spec = xy_scatter::make_scatter_view_spec(result.payload, "t");
    CHECK_EQ(spec.x_axis_label, "X");
    CHECK_EQ(spec.y_axis_label, "Y");
    CHECK_LL(static_cast<long long>(spec.warnings.size()), 2);
    CHECK_EQ(spec.warnings[0], "SourceCRS 未声明");
    CHECK_EQ(spec.warnings[1], "坐标单位未知");
    CHECK_EQ(spec.warning, "SourceCRS 未声明 · 坐标单位未知");
}

PWB_TEST(well_head_scatter_fail_closed_errors) {
    CHECK_EQ(xy_scatter::build_well_head_scatter("# nothing\nA 1 2\n").detail,
             "missing well-head marker");
    CHECK_EQ(xy_scatter::build_well_head_scatter("").error,
             "DAT 数据结构与资源类型不匹配");
    CHECK_EQ(
        xy_scatter::build_well_head_scatter(
            "# WellHead File From SMI\n# Name X Y\n").detail,
        "no data rows");
    CHECK_EQ(xy_scatter::build_well_head_scatter(
                 "# WellHead File From SMI\n# A B C\n1 2 3\n").detail,
             "missing required Name/X/Y columns");
    CHECK_EQ(xy_scatter::build_well_head_scatter(
                 "# WellHead File From SMI\n"
                 "# Name X Y\n# Name X Y TD\n1 2 3\n").detail,
             "ambiguous well-head column width");
    CHECK_EQ(xy_scatter::build_well_head_scatter(
                 "# WellHead File From SMI\n# Name X Y\nA x 1\n").detail,
             "no renderable well locations; source row 3: X 坐标不是有限数值");
    CHECK_EQ(xy_scatter::build_well_head_scatter(
                 "# WellHead File From SMI\n# Well X Y\n\"\" 1 2\n").detail,
             "no renderable well locations; source row 3: 井名为空");
}

PWB_TEST(well_head_scatter_resource_limit_message) {
    const char* three_rows =
        "# WellHead File From SMI\n# Name X Y\nA 1 2\nB 3 4\nC 5 6\n";
    WellHeadScatterOptions two;
    two.max_points = 2;
    const auto result = xy_scatter::build_well_head_scatter(three_rows, two);
    CHECK(!result.ok);
    CHECK(result.resource_limit);
    CHECK_EQ(result.error, "井位数据超过 2 个有效记录的显示上限");

    WellHeadScatterOptions python_default;
    python_default.max_points = 50'000;
    CHECK(xy_scatter::build_well_head_scatter(three_rows).ok);  // 默认不触发
    const char* many = "# WellHead File From SMI\n# Name X Y\n";
    std::string text = many;
    for (int i = 0; i < 50'001; ++i) {
        text += "W" + std::to_string(i) + " " + std::to_string(i) + " 0\n";
    }
    const auto limited = xy_scatter::build_well_head_scatter(text, python_default);
    CHECK(!limited.ok);
    CHECK(limited.resource_limit);
    CHECK_EQ(limited.error, "井位数据超过 50,000 个有效记录的显示上限");
}

PWB_TEST(well_head_scatter_utf8_bom_and_uwi_vote_conflict) {
    const std::string with_bom =
        std::string("\xEF\xBB\xBF") +
        "# WellHead File From SMI\n# Name X Y UWI\nA 1 2 U1\n";
    const auto result = xy_scatter::build_well_head_scatter(with_bom);
    CHECK(result.ok);
    CHECK_EQ(result.payload.names[0], "A");
    CHECK_EQ(result.payload.uwis[0], "U1");

    // 两条同映射声明行把 UWI 投到不同列 ⇒ 冲突票 ⇒ 无 UWI（映射本身
    // 不受影响，载荷仍成功）。
    const char* conflict =
        "# WellHead File From SMI\n"
        "# Name X Y UWI TD\n"
        "# Name X Y TD UWI\n"
        "A 1 2 x y\n";
    const auto no_uwi = xy_scatter::build_well_head_scatter(conflict);
    CHECK(no_uwi.ok);
    CHECK_LL(static_cast<long long>(no_uwi.payload.uwis.size()), 0);
    CHECK_LL(static_cast<long long>(no_uwi.payload.names.size()), 1);
}

PWB_TEST(well_head_scatter_issue_cap_at_twenty) {
    std::string text = "# WellHead File From SMI\n# Name X Y\n";
    for (int i = 0; i < 25; ++i) {
        text += "W" + std::to_string(i) + " bad 1\n";
    }
    const auto result = xy_scatter::build_well_head_scatter(text);
    CHECK(!result.ok);
    CHECK_LL(static_cast<long long>(result.payload.issues.size()), 20);
    CHECK_LL(result.payload.omitted_issue_count, 5);
    const std::string& detail = result.detail;
    CHECK(detail.rfind("no renderable well locations; source row 3: ", 0) == 0);
    CHECK_EQ(detail.substr(detail.size() - 27),
             "; 5 additional rows omitted");
    std::size_t hits = 0;
    for (std::size_t at = detail.find(": X 坐标不是有限数值", 0);
         at != std::string::npos;
         at = detail.find(": X 坐标不是有限数值", at + 1)) {
        ++hits;
    }
    CHECK_LL(static_cast<long long>(hits), 20);  // 20 条截断 + omitted 汇总
}

PWB_TEST(formation_tops_summary_and_text) {
    const char* tops_text =
        "#WellTops File From SMI\n"
        "#WellName Name MD X Y Z TVD Time(ms)\n"
        "A F1 100.5 0 0 0 99.5 0\n"
        "A F2 200 0 0 0 198 0\n"
        "B F1 150 0 0 0 - 0\n"
        "C F9 1 2\n";  // 短行：parser 容错跳过 MD? tokens>=3 合法，md=1
    const std::vector<pwb::ingest::WellTop> tops =
        pwb::ingest::parse_well_tops_text(tops_text);
    CHECK_LL(static_cast<long long>(tops.size()), 4);

    const auto summary = formation_tops::build_formation_tops_summary(tops);
    CHECK_LL(static_cast<long long>(summary.total_wells), 3);
    CHECK_LL(static_cast<long long>(summary.total_tops), 4);
    CHECK_LL(static_cast<long long>(summary.wells.size()), 3);
    CHECK_EQ(summary.wells[0].well, "A");  // 插入序
    CHECK_EQ(summary.wells[1].well, "B");
    CHECK_EQ(summary.wells[2].well, "C");
    CHECK_EQ(summary.wells[0].rows[0].top, "F1");
    CHECK_EQ(summary.wells[0].rows[0].md, "100.50");
    CHECK_EQ(summary.wells[0].rows[0].tvd, "99.50");
    CHECK_EQ(summary.wells[0].rows[1].md, "200.00");
    CHECK_EQ(summary.wells[1].rows[0].md, "150.00");
    CHECK_EQ(summary.wells[1].rows[0].tvd, "");  // "-" ⇒ TVD 缺失
    CHECK_EQ(summary.wells[2].rows[0].md, "1.00");
    CHECK_EQ(summary.wells[2].rows[0].tvd, "");  // 列数不足 ⇒ 无 TVD

    const std::string text =
        formation_tops::make_formation_tops_preview_text(summary);
    const std::string first_line = text.substr(0, text.find('\n'));
    CHECK_EQ(first_line, "井数: 3 · 层位点: 4");
    CHECK(text.find("井名") != std::string::npos);
    CHECK(text.find("F1") != std::string::npos);
    CHECK(text.find("F2") != std::string::npos);
    CHECK(text.find("100.50") != std::string::npos);
    CHECK(text.find("99.50") != std::string::npos);
    CHECK(text.find("200.00") != std::string::npos);
    CHECK(text.find("150.00") != std::string::npos);

    const auto empty =
        formation_tops::build_formation_tops_summary({});
    CHECK_EQ(formation_tops::make_formation_tops_preview_text(empty),
             "井数: 0 · 层位点: 0");
}

PWB_TEST(formation_tops_format_depth) {
    CHECK_EQ(formation_tops::format_depth(1234.5), "1234.50");
    CHECK_EQ(formation_tops::format_depth(0.0), "0.00");
    CHECK_EQ(formation_tops::format_depth(-2.375), "-2.38");  // 四舍五入
}

int main() { return pwb_test::run_all(); }
