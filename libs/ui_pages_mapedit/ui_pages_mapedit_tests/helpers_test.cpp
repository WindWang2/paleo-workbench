// UI-08 — Qt-free helper parity tests: map_edit_api vertex/edge/hit
// kernels, SnapCandidateIndex, FeatureQueryIndex, document_features.
//
// Semantics mirrored from the Python modules (map_edit/api.py,
// mapping/feature_query_index.py, mapping/document_io.py +
// geometry_schema.py): closed-ring endpoint sync, insert-before-close,
// min-vertex guards, last-candidate snap ties, insertion-order query
// results, visibility filtering at query time, raw-key precedence over
// nested properties.

#include <pwb/ui_pages_mapedit/document_features.hpp>
#include <pwb/ui_pages_mapedit/feature_query_index.hpp>
#include <pwb/ui_pages_mapedit/map_edit_api.hpp>

#include "ui_pages_mapedit_test.hpp"

using pwb::domain::Json;
using pwb::ui_pages_mapedit::MapPoint;
using pwb::ui_pages_mapedit::MapRing;

namespace {

MapRing closed_square() {
    return MapRing{{0.0, 0.0}, {10.0, 0.0}, {10.0, 10.0},
                   {0.0, 10.0}, {0.0, 0.0}};
}

}  // namespace

PWB_TEST(is_closed_ring_variants) {
    PWB_CHECK(pwb::ui_pages_mapedit::is_closed_ring(closed_square()));
    PWB_CHECK(!pwb::ui_pages_mapedit::is_closed_ring(
        MapRing{{0.0, 0.0}, {1.0, 0.0}, {1.0, 1.0}}));
    // Single point never counts (>= 2 points required).
    PWB_CHECK(!pwb::ui_pages_mapedit::is_closed_ring(MapRing{{0.0, 0.0}}));
    // Two identical endpoints with no unique vertex still closed by shape.
    PWB_CHECK(pwb::ui_pages_mapedit::is_closed_ring(
        MapRing{{0.0, 0.0}, {0.0, 0.0}}));
}

PWB_TEST(set_vertex_syncs_closed_endpoints) {
    auto ring = closed_square();
    PWB_CHECK(pwb::ui_pages_mapedit::set_vertex(ring, 0, -1.0, -1.0));
    PWB_CHECK_EQ(ring[0][0], -1.0);
    PWB_CHECK_EQ(ring[0][1], -1.0);
    // Closing duplicate follows vertex 0 on closed rings.
    PWB_CHECK_EQ(ring.back()[0], -1.0);
    PWB_CHECK_EQ(ring.back()[1], -1.0);
    // Out-of-range index → the Python raise branch.
    PWB_CHECK(!pwb::ui_pages_mapedit::set_vertex(ring, 99, 0.0, 0.0));
}

PWB_TEST(set_vertex_open_ring_no_sync) {
    MapRing ring{{0.0, 0.0}, {1.0, 0.0}, {2.0, 0.0}};
    PWB_CHECK(pwb::ui_pages_mapedit::set_vertex(ring, 0, 5.0, 5.0));
    PWB_CHECK_EQ(ring[0][0], 5.0);
    PWB_CHECK_EQ(ring.back()[0], 2.0);  // untouched
}

PWB_TEST(insert_vertex_closed_ring_before_close) {
    auto ring = closed_square();
    // Insert at the closing index lands BEFORE the closing duplicate.
    PWB_CHECK(pwb::ui_pages_mapedit::insert_vertex(ring, 4, 5.0, 5.0));
    PWB_CHECK_EQ(ring.size(), 6);
    PWB_CHECK_EQ(ring[4][0], 5.0);
    PWB_CHECK_EQ(ring[5][0], 0.0);  // closing duplicate stays last
    PWB_CHECK_EQ(ring[5][1], 0.0);
}

PWB_TEST(insert_vertex_open_ring_list_insert) {
    MapRing ring{{0.0, 0.0}, {2.0, 0.0}};
    PWB_CHECK(pwb::ui_pages_mapedit::insert_vertex(ring, 1, 1.0, 0.0));
    PWB_CHECK_EQ(ring.size(), 3);
    PWB_CHECK_EQ(ring[1][0], 1.0);
    PWB_CHECK(!pwb::ui_pages_mapedit::insert_vertex(ring, 99, 0.0, 0.0));
}

PWB_TEST(delete_vertex_min_unique_guard) {
    auto ring = closed_square();
    // Closed ring has 4 unique vertices — deleting down to 3 is allowed.
    PWB_CHECK(pwb::ui_pages_mapedit::delete_vertex(ring, 2));
    PWB_CHECK_EQ(ring.size(), 4);
    // Now 3 unique + close — deleting again would leave 2 unique < 3.
    PWB_CHECK(!pwb::ui_pages_mapedit::delete_vertex(ring, 1));
    MapRing open{{0.0, 0.0}, {1.0, 0.0}};
    // Open ring keeps >= 2 points.
    PWB_CHECK(!pwb::ui_pages_mapedit::delete_vertex(open, 0));
}

PWB_TEST(closest_edge_projection) {
    auto ring = closed_square();
    const auto edge =
        pwb::ui_pages_mapedit::closest_edge(ring, 5.0, -3.0);
    PWB_CHECK(edge.has_value());
    PWB_CHECK_EQ(edge->edge_start_index, 0);
    PWB_CHECK_NEAR(edge->proj_x, 5.0, 1e-9);
    PWB_CHECK_NEAR(edge->proj_y, 0.0, 1e-9);
    PWB_CHECK_NEAR(edge->distance2, 9.0, 1e-9);
}

PWB_TEST(hit_test_first_record_order) {
    std::vector<Json> records = {
        {{"id", "f1"}, {"coordinates", Json::array({Json::array({0, 0}),
                                                    Json::array({10, 0}),
                                                    Json::array({10, 10}),
                                                    Json::array({0, 10}),
                                                    Json::array({0, 0})})}},
        {{"id", "f2"}, {"coordinates", Json::array({5.0, 5.0})}},
    };
    // Point inside f1's ring → first record wins (top-most ordering).
    const auto hit = pwb::ui_pages_mapedit::hit_test(records, 5.0, 5.0, 0.0);
    PWB_CHECK(hit.has_value());
    PWB_CHECK_EQ(*hit, "f1");
    // Far away → miss.
    PWB_CHECK(!pwb::ui_pages_mapedit::hit_test(records, 500.0, 500.0, 0.0)
                   .has_value());
}

PWB_TEST(snap_nearest_and_last_tie) {
    using pwb::ui_pages_mapedit::SnapCandidateIndex;
    SnapCandidateIndex index({MapPoint{0.0, 0.0}, MapPoint{10.0, 0.0},
                              MapPoint{20.0, 0.0}});
    // Nearest within tolerance wins.
    const auto snapped = index.snap(9.9, 0.4, 1.0);
    PWB_CHECK_NEAR(snapped[0], 10.0, 1e-9);
    PWB_CHECK_NEAR(snapped[1], 0.0, 1e-9);
    // Equidistant → LAST candidate in input order wins.
    SnapCandidateIndex ties({MapPoint{0.0, 0.0}, MapPoint{2.0, 0.0}});
    const auto tie = ties.snap(1.0, 0.0, 2.0);
    PWB_CHECK_NEAR(tie[0], 2.0, 1e-9);
    // Miss → original point returned unchanged.
    const auto miss = index.snap(100.0, 100.0, 1.0);
    PWB_CHECK_NEAR(miss[0], 100.0, 1e-9);
    PWB_CHECK_NEAR(miss[1], 100.0, 1e-9);
}

PWB_TEST(snap_extra_candidates_append) {
    using pwb::ui_pages_mapedit::SnapCandidateIndex;
    SnapCandidateIndex index({MapPoint{0.0, 0.0}});
    // Extras act as if appended after base candidates (win ties).
    const auto snapped = index.snap(5.0, 0.0, 6.0,
                                    {MapPoint{10.0, 0.0}});
    PWB_CHECK_NEAR(snapped[0], 10.0, 1e-9);
}

PWB_TEST(query_index_visibility_and_order) {
    using pwb::ui_pages_mapedit::FeatureQueryIndex;
    using pwb::ui_pages_mapedit::IndexedItem;
    FeatureQueryIndex index;
    const auto rec = [](const char* id, double x) {
        return Json{{"id", id},
                    {"coordinates", Json::array({x, 0.0})}};
    };
    index.rebuild({IndexedItem{"f1", "facies", rec("f1", 0.0)},
                   IndexedItem{"w1", "well", rec("w1", 0.5)},
                   IndexedItem{"f2", "facies", rec("f2", 0.25)}});
    const auto all = [](std::string_view) { return true; };
    auto hits = index.query(0.25, 0.0, 0.5, all);
    // Descending insertion order: f2 (order 2) → w1 → f1.
    PWB_CHECK_EQ(hits.size(), 3);
    PWB_CHECK_EQ(hits[0].at("id").get<std::string>(), "f2");
    PWB_CHECK_EQ(hits[1].at("id").get<std::string>(), "w1");
    PWB_CHECK_EQ(hits[2].at("id").get<std::string>(), "f1");
    // Query-time visibility: wells hidden → no stale geometry exposed.
    const auto no_wells = [](std::string_view kind) {
        return kind != "well";
    };
    hits = index.query(0.25, 0.0, 0.5, no_wells);
    PWB_CHECK_EQ(hits.size(), 2);
    PWB_CHECK_EQ(hits[0].at("id").get<std::string>(), "f2");
    PWB_CHECK_EQ(hits[1].at("id").get<std::string>(), "f1");
    // remove + upsert incremental updates.
    index.remove("f2");
    hits = index.query(0.25, 0.0, 0.5, all);
    PWB_CHECK_EQ(hits.size(), 2);
    index.upsert(IndexedItem{"f3", "facies", rec("f3", 0.0)});
    hits = index.query(0.25, 0.0, 0.5, all);
    PWB_CHECK_EQ(hits.size(), 3);
    PWB_CHECK_EQ(hits[0].at("id").get<std::string>(), "f3");
}

PWB_TEST(query_index_bounds_skip) {
    using pwb::ui_pages_mapedit::FeatureQueryIndex;
    FeatureQueryIndex index;
    index.rebuild({{"f1", "facies",
                    Json{{"id", "f1"},
                         {"coordinates",
                          Json::array({Json::array({1000.0, 1000.0}),
                                       Json::array({1001.0, 1000.0}),
                                       Json::array({1001.0, 1001.0}),
                                       Json::array({1000.0, 1000.0})})}}}});
    const auto all = [](std::string_view) { return true; };
    // Far from the entry bounds → empty without geometry checks.
    PWB_CHECK(index.query(0.0, 0.0, 1.0, all).empty());
    PWB_CHECK_EQ(index.query(1000.5, 1000.5, 2.0, all).size(), 1);
}

PWB_TEST(normalize_facies_raw_key_precedence) {
    const Json raw = {
        {"id", "raw-id"},
        {"name", "raw-name"},
        {"facies", "raw-facies"},
        {"probability", 0.9},
        {"coordinates",
         Json::array({Json::array({0, 0}), Json::array({1, 0}),
                      Json::array({1, 1}), Json::array({0, 0})})},
        {"properties",
         Json{{"name", "props-name"},
              {"facies", "props-facies"},
              {"probability", 0.1},
              {"region_id", "r-9"}}},
    };
    const auto out = pwb::ui_pages_mapedit::normalize_facies(raw);
    PWB_CHECK_EQ(out.at("id").get<std::string>(), "raw-id");
    PWB_CHECK_EQ(out.at("kind").get<std::string>(), "facies");
    // Raw keys win over nested properties.
    PWB_CHECK_EQ(out.at("name").get<std::string>(), "raw-name");
    PWB_CHECK_EQ(out.at("facies").get<std::string>(), "raw-facies");
    // Raw probability (typed value, not stringified).
    PWB_CHECK_NEAR(out.at("probability").get<double>(), 0.9, 1e-9);
    // Missing raw key falls back to properties.
    PWB_CHECK_EQ(out.at("region_id").get<std::string>(), "r-9");
    PWB_CHECK_EQ(out.at("geometry_type").get<std::string>(), "Polygon");
    // properties round-trips minus "style".
    PWB_CHECK(out.at("properties").contains("name"));
}

PWB_TEST(normalize_well_coordinate_status) {
    const auto bad = pwb::ui_pages_mapedit::normalize_well(
        Json{{"id", "w-bad"}, {"name", "broken"}});
    PWB_CHECK_EQ(bad.at("coordinate_status").get<std::string>(), "invalid");
    const auto good = pwb::ui_pages_mapedit::normalize_well(
        Json{{"id", "w1"}, {"coordinates", Json::array({3.5, 4.5})}});
    PWB_CHECK_EQ(good.at("coordinate_status").get<std::string>(), "ok");
    PWB_CHECK_NEAR(good.at("coordinates")[0].get<double>(), 3.5, 1e-9);
}

PWB_TEST(normalize_label_malformed_anchor) {
    // Malformed anchor → Python ValueError branch (nullopt).
    PWB_CHECK(!pwb::ui_pages_mapedit::normalize_label(
                      Json{{"anchor", Json::array({1.0})}})
                  .has_value());
    const auto out = pwb::ui_pages_mapedit::normalize_label(
        Json{{"id", "l1"}, {"anchor", Json::array({7.0, 8.0})},
             {"text", "高原"}});
    PWB_CHECK(out.has_value());
    PWB_CHECK_EQ(out->at("kind").get<std::string>(), "label");
    PWB_CHECK_EQ(out->at("text").get<std::string>(), "高原");
    PWB_CHECK_NEAR(out->at("coordinates")[0].get<double>(), 7.0, 1e-9);
}

PWB_TEST(features_from_document_order_and_skip) {
    const Json doc = {
        {"facies_polygons",
         Json::array({Json{{"id", "f1"},
                           {"coordinates",
                            Json::array({Json::array({0, 0}),
                                         Json::array({1, 0}),
                                         Json::array({1, 1}),
                                         Json::array({0, 0})})}}})},
        {"well_overlays",
         Json::array({Json{{"id", "w1"},
                           {"coordinates", Json::array({1.0, 2.0})}}})},
        {"line_features",
         Json::array({Json{{"id", "ln1"},
                           {"coordinates", Json::array()}}})},
        {"label_features",
         Json::array({Json{{"anchor", Json::array({1.0})}},  // malformed → skipped
                      Json{{"id", "lb1"},
                           {"anchor", Json::array({0.0, 0.0})},
                           {"text", "t"}}})},
    };
    const auto features =
        pwb::ui_pages_mapedit::features_from_document(doc);
    PWB_CHECK_EQ(features.size(), 4);
    PWB_CHECK_EQ(features[0].at("kind").get<std::string>(), "facies");
    PWB_CHECK_EQ(features[1].at("kind").get<std::string>(), "well");
    PWB_CHECK_EQ(features[2].at("kind").get<std::string>(), "line");
    PWB_CHECK_EQ(features[3].at("kind").get<std::string>(), "label");
    PWB_CHECK_EQ(features[3].at("id").get<std::string>(), "lb1");
}

PWB_TEST_MAIN()
