// ui_data_core.smoke — post-mortem completion of the UI-03 slice: the
// agent was terminated before writing tests, so this covers the ported
// kernels' headline semantics (geometry/snap/commands/filter vocab/item
// models) against the Python contracts named in each header.

#include <pwb/ui_data_core/filter_index.hpp>
#include <pwb/ui_data_core/map_edit_commands.hpp>
#include <pwb/ui_data_core/map_edit_geometry.hpp>
#include <pwb/ui_data_core/map_edit_items.hpp>
#include <pwb/ui_data_core/map_edit_snap.hpp>

#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

using namespace pwb::ui_data_core;
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
    // --- snap_point (geoviz api.py _snap_point_python) --------------------
    {
        const std::vector<MapPoint> cands{{0.0, 0.0}, {10.0, 0.0}};
        MapPoint p = snap_point(cands, 9.5, 0.4, 1.0);
        CHECK(p[0] == 10.0 && p[1] == 0.0);
        // No candidate within tol → input point passthrough.
        MapPoint q = snap_point(cands, 5.0, 5.0, 1.0);
        CHECK(q[0] == 5.0 && q[1] == 5.0);
    }

    // --- segments_properly_intersect --------------------------------------
    CHECK(segments_properly_intersect({0, 0}, {2, 2}, {0, 2}, {2, 0}));
    CHECK(!segments_properly_intersect({0, 0}, {1, 0}, {0, 1}, {1, 1}));

    // --- ring coercion ------------------------------------------------------
    {
        domain::Json ring = domain::Json::array(
            {domain::Json::array({0.0, 0.0}), domain::Json::array({1.0, 0.0}),
             domain::Json::array({1.0, 1.0})});
        MapRing open = coerce_ring(ring);
        CHECK(open.size() == 4);  // open ring closed by appending first point
        CHECK(open.front() == open.back());
        // Strict: a non-point entry empties the ring.
        domain::Json bad = domain::Json::array(
            {domain::Json::array({0.0, 0.0}), domain::Json("x")});
        CHECK(coerce_ring(bad).empty());
        // Best-effort: malformed points skipped.
        MapRing best = ring_to_pts(bad);
        CHECK(best.size() == 1);
    }

    // --- validate_ring ------------------------------------------------------
    {
        // Bowtie ring self-intersects.
        MapRing bowtie{{0, 0}, {2, 2}, {2, 0}, {0, 2}, {0, 0}};
        domain::Json issues = validate_ring(bowtie);
        CHECK(issues.is_array() && !issues.empty());
        MapRing square{{0, 0}, {1, 0}, {1, 1}, {0, 1}, {0, 0}};
        CHECK(validate_ring(square).empty());
    }

    // --- MapSnapManager ------------------------------------------------------
    {
        MapSnapManager mgr;
        CHECK(!mgr.enabled());
        mgr.set_enabled(true);
        mgr.set_tolerance(-3.0);
        CHECK(mgr.tolerance() == 0.0);  // negative clamps to 0
        mgr.set_tolerance(8.0);
        mgr.set_reference_points({{5.0, 5.0}});
        CHECK(mgr.reference_points().size() == 1);
        std::vector<SnapItem> items;
        auto visible = [](std::string_view) { return true; };
        // Reference points ride every snap; far candidates snap to ref point.
        MapPoint p = mgr.snap_xy(5.2, 5.1, items, visible);
        CHECK(std::fabs(p[0] - 5.0) < 1e-9 && std::fabs(p[1] - 5.0) < 1e-9);
        // Disabled → passthrough.
        mgr.set_enabled(false);
        MapPoint q = mgr.snap_xy(5.2, 5.1, items, visible);
        CHECK(q[0] == 5.2 && q[1] == 5.1);
    }

    // --- EditCommandStack ----------------------------------------------------
    {
        int applied = 0;
        struct Inc final : EditCommand {
            int* n;
            explicit Inc(int* n) : n(n) {}
            void apply() override { ++*n; }
            void revert() override { --*n; }
        };
        EditCommandStack stack(/*max_depth=*/2);
        CHECK(!stack.can_undo() && !stack.can_redo());
        stack.push(std::make_shared<Inc>(&applied));
        stack.push(std::make_shared<Inc>(&applied));
        CHECK(applied == 2 && stack.can_undo());
        CHECK(stack.undo() && applied == 1);
        CHECK(stack.redo() && applied == 2);
        // Third push at max_depth evicts the oldest → truncation flag.
        stack.push(std::make_shared<Inc>(&applied));
        CHECK(stack.overflowed());
        CHECK(stack.undo() && stack.undo());
        CHECK(!stack.can_undo());  // oldest was evicted
    }

    // --- FilterIndex vocabulary ----------------------------------------------
    CHECK(!categories().empty());
    CHECK(!status_labels().empty());
    CHECK(issue_statuses().count("missing") == 1);
    CHECK(reference_types().count("document") == 1);

    // --- FaciesPolygonModel --------------------------------------------------
    {
        domain::Json coords = domain::Json::array({domain::Json::array(
            {domain::Json::array({0.0, 0.0}), domain::Json::array({1.0, 0.0}),
             domain::Json::array({1.0, 1.0}), domain::Json::array({0.0, 0.0})})});
        FaciesPolygonModel poly("f1", coords, "砂体");
        CHECK(poly.feature_id == "f1");
        CHECK(poly.topology_status == kTopologyOk);
        poly.set_topology_status(std::string_view("warning"));
        CHECK(poly.topology_status == "warning");
        poly.set_topology_status(domain::Json(nullptr));
        CHECK(poly.topology_status == kTopologyOk);  // None → "ok"
        domain::Json rec = poly.to_record();
        CHECK(rec["id"] == "f1");
    }

    std::printf("%s: %d checks, %d failures\n",
                failures ? "FAILED" : "PASSED", checks, failures);
    return failures ? 1 : 0;
}
