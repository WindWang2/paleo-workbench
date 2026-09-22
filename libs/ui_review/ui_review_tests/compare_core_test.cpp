// M5 — 解释 vs 预测对比 core battery (ui_review.compare_core).

#include <pwb/ui_review/compare_core.hpp>

#include "ui_review_test.hpp"

using pwb::domain::Json;
using pwb::ui_review::bands_from_interpretation;
using pwb::ui_review::bands_from_prediction;
using pwb::ui_review::pair_bands;
using pwb::ui_review::summarize_pairs;

PWB_TEST(mode_vocabulary) {
    using pwb::ui_review::compare_mode_from_string;
    CHECK(compare_mode_from_string("side_by_side") ==
          pwb::ui_review::CompareMode::SideBySide);
    CHECK(compare_mode_from_string("overlay") ==
          pwb::ui_review::CompareMode::Overlay);
    CHECK(compare_mode_from_string("difference") ==
          pwb::ui_review::CompareMode::Difference);
    CHECK(!compare_mode_from_string("blend").has_value());
}

PWB_TEST(prediction_bands_from_real_payload) {
    const Json task = Json{
        {"id", "pred1"},
        {"name", "A12 相预测"},
        {"result_summary",
         Json{{"predicted_regions",
               Json::array({
                   Json{{"well_id", "w1"},
                        {"well_name", "A12"},
                        {"stratigraphic_unit", "长71"},
                        {"top", 2100.0},
                        {"bottom", 2140.0},
                        {"facies", "水下分流河道"},
                        {"probability", 0.83}},
                   Json{{"well_id", "w1"},
                        {"well_name", "A12"},
                        {"stratigraphic_unit", "长72"},
                        {"top", 2140.0},
                        {"bottom", 2180.0},
                        {"facies", "河口坝"},
                        {"probability", 0.71}},
               })}}}};
    const auto bands = bands_from_prediction(task);
    CHECK(bands.size() == 2);
    CHECK(bands.front().unit == "长71");
    CHECK(bands.front().klass == "水下分流河道");
    CHECK(bands.front().taxonomy == "facies");  // 沉积相体系
    CHECK(bands.front().confidence == 0.83);
    CHECK(bands.front().top == 2100.0);
}

PWB_TEST(interpretation_tops_form_bands_without_inventing_classes) {
    const Json ref = Json{{"id", "corr1"}, {"name", "连井对比"},
                          {"depth_domain", "MD"}};
    const Json scientific = Json{
        {"tops",
         Json::array({
             Json{{"well_id", "w1"}, {"well_name", "A12"},
                  {"marker", "长71顶"}, {"depth", 2100.0},
                  {"status", "active"}},
             Json{{"well_id", "w1"}, {"well_name", "A12"},
                  {"marker", "长72顶"}, {"depth", 2140.0},
                  {"status", "active"}},
             Json{{"well_id", "w1"}, {"well_name", "A12"},
                  {"marker", "长73顶"}, {"depth", 2180.0},
                  {"status", "rejected"}},  // dropped
             Json{{"well_id", "w1"}, {"well_name", "A12"},
                  {"marker", "长74顶"}, {"depth", 2210.0},
                  {"status", "active"}},
         })}};
    const auto bands = bands_from_interpretation(ref, scientific);
    // Active tops: 2100/2140/2210 → two bands; no class invented.
    CHECK(bands.size() == 2);
    CHECK(bands.front().top == 2100.0);
    CHECK(bands.front().bottom == 2140.0);
    CHECK(bands.front().klass.empty());  // 解释未标注 — 诚实空
    CHECK(bands.back().bottom == 2210.0);
}

PWB_TEST(pairing_counts_presence_and_class_mismatch) {
    const Json ref = Json{{"id", "corr1"}, {"name", "连井"}};
    const Json scientific = Json{
        {"tops",
         Json::array({
             Json{{"well_id", "w1"}, {"marker", "长71"}, {"depth", 0.0},
                  {"status", "active"}},
             Json{{"well_id", "w1"}, {"marker", "长71底"}, {"depth", 40.0},
                  {"status", "active"}},
             Json{{"well_id", "w1"}, {"marker", "长72"}, {"depth", 40.0},
                  {"status", "active"}},
             Json{{"well_id", "w1"}, {"marker", "长72底"}, {"depth", 80.0},
                  {"status", "active"}},
             // 长73: interpretation only
             Json{{"well_id", "w1"}, {"marker", "长73"}, {"depth", 80.0},
                  {"status", "active"}},
             Json{{"well_id", "w1"}, {"marker", "长73底"}, {"depth", 120.0},
                  {"status", "active"}},
         })}};
    const auto interp = bands_from_interpretation(ref, scientific);
    CHECK(interp.size() == 3);

    const Json task = Json{
        {"id", "pred1"},
        {"result_summary",
         Json{{"predicted_regions",
               Json::array({
                   // 长71: same unit — but interpretation has no class →
                   // incomparable (never a fake match verdict).
                   Json{{"well_id", "w1"}, {"stratigraphic_unit", "长71"},
                        {"top", 0.0}, {"bottom", 40.0},
                        {"facies", "水下分流河道"}},
                   // 长9: prediction only.
                   Json{{"well_id", "w1"}, {"stratigraphic_unit", "长9"},
                        {"top", 200.0}, {"bottom", 230.0},
                        {"facies", "河口坝"}},
               })}}}};
    const auto pred = bands_from_prediction(task);
    const auto pairs = pair_bands(interp, pred);
    const auto summary = summarize_pairs(pairs);
    CHECK(summary.incomparable == 1);           // 长71 present both, no class
    CHECK(summary.interpretation_only == 2);    // 长72/长73
    CHECK(summary.prediction_only == 1);        // 长9
    CHECK(summary.matched == 0);
    CHECK(summary.mismatched == 0);
}

PWB_TEST(class_match_verdict_when_both_sides_annotated) {
    // Interpretation carrying an explicit class label (future payloads)
    // pairs into a real match/mismatch verdict.
    pwb::ui_review::CompareBand interp;
    interp.well_id = "w1";
    interp.unit = "长71";
    interp.klass = "水下分流河道";
    pwb::ui_review::CompareBand same = interp;
    pwb::ui_review::CompareBand other = interp;
    other.klass = "河口坝";

    const auto matching = pair_bands({interp}, {same});
    CHECK(matching.size() == 1);
    CHECK(matching.front().comparable);
    CHECK(matching.front().match);

    const auto differing = pair_bands({interp}, {other});
    CHECK(differing.size() == 1);
    CHECK(differing.front().comparable);
    CHECK(!differing.front().match);
    CHECK(summarize_pairs(differing).mismatched == 1);
}

int main() {
    return ::pwb_test::run_all();
}
