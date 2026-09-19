// viz_d.preview — frozen-Python replay for the xy_scatter well-head core
// against tools/oracle/generate_viz_d_wellhead_fixtures.py (real
// geoviz.previews.dat runs), plus the formation-tops honest preview.

#include "viz_d_test.hpp"

#include <cmath>
#include <string>
#include <vector>

#include <pwb/ingest/well_parsers.hpp>
#include <pwb/ui_pages_preview/formation_tops_preview.hpp>
#include <pwb/ui_pages_preview/well_head_scatter_core.hpp>

using pwb::ui_pages_preview::formation_tops::build_formation_tops_summary;
using pwb::ui_pages_preview::formation_tops::make_formation_tops_preview_text;
using pwb::ui_pages_preview::xy_scatter::build_well_head_scatter;
using pwb::ui_pages_preview::xy_scatter::make_scatter_view_spec;
using pwb::ui_pages_preview::xy_scatter::WellHeadScatterOptions;
using viz_d_test::close_or_both_nan;
using viz_d_test::num_from;

namespace {

const nlohmann::json& payload_of(const nlohmann::json& entry) {
    return entry.at("payload");
}

} // namespace

TEST(well_head_scatter_replay_matches_python_payloads) {
    const auto fixture = viz_d_test::load_fixture("viz_d_wellhead_oracle.json");
    for (const auto& [name, entry] : fixture.at("cases").items()) {
        WellHeadScatterOptions options;
        if (entry.at("kwargs").contains("source_crs")) {
            options.source_crs = entry.at("kwargs").at("source_crs").get<std::string>();
        }
        if (entry.at("kwargs").contains("coordinate_units")) {
            options.coordinate_units =
                entry.at("kwargs").at("coordinate_units").get<std::string>();
        }
        if (entry.at("kwargs").contains("comparison_crs")) {
            options.comparison_crs =
                entry.at("kwargs").at("comparison_crs").get<std::string>();
        }
        const auto result =
            build_well_head_scatter(entry.at("text").get<std::string>(), options);
        if (!entry.at("ok").get<bool>()) {
            PWB_CHECK_MSG(!result.ok, (name + ": expected failure").c_str());
            const std::string expected_error = entry.at("error").get<std::string>();
            // The Python exception text (after ": ") must survive verbatim.
            const std::size_t colon = expected_error.find(": ");
            const std::string reason =
                colon == std::string::npos ? expected_error
                                           : expected_error.substr(colon + 2);
            PWB_CHECK_MSG(result.detail.find(reason) != std::string::npos ||
                              result.error.find(reason) != std::string::npos,
                          (name + ": error text diverged: " + result.error + " / " +
                           result.detail + " vs " + reason)
                              .c_str());
            continue;
        }
        PWB_CHECK_MSG(result.ok,
                      (name + ": unexpected failure: " + result.error + " / " +
                       result.detail)
                          .c_str());
        const auto& expected = payload_of(entry);
        const auto& payload = result.payload;
        const auto x = expected.at("x");
        PWB_CHECK(payload.x.size() == x.size());
        for (std::size_t i = 0; i < std::min(payload.x.size(), x.size()); ++i) {
            PWB_CHECK_MSG(close_or_both_nan(payload.x[i], num_from(x.at(i)), 0.0),
                          (name + ": x coordinate").c_str());
        }
        const auto y = expected.at("y");
        for (std::size_t i = 0; i < std::min(payload.y.size(), y.size()); ++i) {
            PWB_CHECK(close_or_both_nan(payload.y[i], num_from(y.at(i)), 0.0));
        }
        const auto names = expected.at("names");
        PWB_CHECK(payload.names.size() == names.size());
        for (std::size_t i = 0; i < std::min(payload.names.size(), names.size()); ++i) {
            PWB_CHECK(payload.names[i] == names.at(i).get<std::string>());
        }
        const auto uwis = expected.at("uwis");
        PWB_CHECK(payload.uwis.size() == uwis.size());
        const auto record_ids = expected.at("record_ids");
        PWB_CHECK(payload.record_ids.size() == record_ids.size());
        const auto source_rows = expected.at("source_rows");
        PWB_CHECK(payload.source_rows.size() == source_rows.size());
        for (std::size_t i = 0;
             i < std::min(payload.source_rows.size(), source_rows.size()); ++i) {
            PWB_CHECK(payload.source_rows[i] == source_rows.at(i).get<std::int64_t>());
        }
        PWB_CHECK(payload.source_crs == expected.at("source_crs").get<std::string>());
        PWB_CHECK(payload.coordinate_units ==
                  expected.at("coordinate_units").get<std::string>());
        const auto& status = expected.at("coordinate_status");
        PWB_CHECK(payload.source_crs_provenance ==
                  status.at("source_crs_provenance").get<std::string>());
        PWB_CHECK(payload.coordinate_units_provenance ==
                  status.at("coordinate_units_provenance").get<std::string>());
        PWB_CHECK(payload.comparison_crs ==
                  status.at("comparison_crs").get<std::string>());
        if (status.at("comparison_matches_source").is_null()) {
            PWB_CHECK(!payload.comparison_matches_source.has_value());
        } else {
            PWB_CHECK(payload.comparison_matches_source.has_value() &&
                      *payload.comparison_matches_source ==
                          status.at("comparison_matches_source").get<bool>());
        }
        const auto& diag = expected.at("diagnostics");
        PWB_CHECK(payload.total_records == diag.at("total_records").get<std::int64_t>());
        PWB_CHECK(payload.valid_records == diag.at("valid_records").get<std::int64_t>());
        PWB_CHECK(payload.omitted_issue_count ==
                  diag.at("omitted_issue_count").get<std::int64_t>());
        const auto& issues = diag.at("issues");
        PWB_CHECK(payload.issues.size() == issues.size());
        for (std::size_t i = 0; i < std::min(payload.issues.size(), issues.size());
             ++i) {
            PWB_CHECK(payload.issues[i].source_row ==
                      issues.at(i).at("source_row").get<std::int64_t>());
            PWB_CHECK(payload.issues[i].reason ==
                      issues.at(i).at("reason").get<std::string>());
        }
        // XYScatterBackend.prepare warning list parity.
        const auto spec = make_scatter_view_spec(payload, "title");
        const auto& expected_warnings = entry.at("warnings");
        PWB_CHECK(spec.warnings.size() == expected_warnings.size());
        for (std::size_t i = 0;
             i < std::min(spec.warnings.size(), expected_warnings.size()); ++i) {
            PWB_CHECK(spec.warnings[i] ==
                      expected_warnings.at(i).get<std::string>());
        }
    }
}

TEST(formation_tops_preview_presents_real_parsed_data) {
    // Real SMI WellTops content through the ingest parser (the production
    // consumer is the prediction/mapping postprocess pipeline; the preview
    // presents the parsed table — never a placeholder message).
    const std::string text =
        "#WellTops File From SMI\n"
        "#WellName Name MD X Y Z TVD Time(ms)\n"
        "W1 TopA 1000.0 1 2 3 995.0 500\n"
        "W1 TopB 1500.5 1 2 3 1490.25 750\n"
        "W2 TopA 1100.0 4 5 6 1080.0 550\n"
        "garbage line\n";
    const std::vector<pwb::ingest::WellTop> tops = pwb::ingest::parse_well_tops_text(text);
    PWB_CHECK(tops.size() == 3);
    const auto summary = build_formation_tops_summary(tops);
    PWB_CHECK(summary.wells.size() == 2);
    PWB_CHECK(summary.total_tops == 3);
    const auto preview = make_formation_tops_preview_text(summary);
    PWB_CHECK(preview.find("W1") != std::string::npos);
    PWB_CHECK(preview.find("TopA") != std::string::npos);
    PWB_CHECK(preview.find("1500.50") != std::string::npos);
    // Empty input is honestly empty, not faked.
    const auto empty = build_formation_tops_summary({});
    PWB_CHECK(empty.wells.empty() && empty.total_tops == 0);
}

#include "viz_d_test_main.inc"
