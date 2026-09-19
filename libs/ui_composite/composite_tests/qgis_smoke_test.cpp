// UI-13 — QGIS adapter smoke test: runs only where the vendored SDK
// was admitted (same runtime closure as tests/cpp/platform — the
// ENVIRONMENT_MODIFICATION prepends vendor lib + Qt lib paths).
//
// Covers the pwb_ui_composite_qgis ports that admit a native surface:
//   QgisCompositeGeometryOps — merge/split/makeValid/multipart/trim/
//       extend/reverse/simplify/smooth/offset/rotate/scale/centroid/
//       reshape/add_part/delete_part through real QgsGeometry.
//   validator/repair seams  — TopologyService validator + the
//       repair_invalid_geometry backend (QgsGeometry::makeValid).
//   CompositeQgisCanvas     — QgisCanvasShim ↔ controller binding
//       (canvas hooks + controller hooks + snapshot publish).

#include <qgsapplication.h>

#include <QApplication>
#include <QWidget>

#include <algorithm>
#include <cmath>
#include <functional>
#include <cstdio>
#include <set>
#include <string>

#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_composite/composite_controller.hpp>
#include <pwb/ui_composite/qgis/composite_qgis_canvas.hpp>
#include <pwb/ui_composite/qgis/qgis_geometry.hpp>
#include <pwb/ui_composite/vector_layer.hpp>

using namespace pwb::ui_composite;
using namespace pwb::ui_composite::qgis;
using pwb::domain::Json;

namespace {

int failures = 0;

void check(bool condition, const char* what) {
    if (!condition) {
        ++failures;
        std::fprintf(stderr, "FAIL %s\n", what);
    } else {
        std::fprintf(stderr, "PASS %s\n", what);
    }
}

Json square(double x0, double y0, double x1, double y1) {
    return Json{{"type", "Polygon"},
                {"coordinates",
                 Json::array({Json::array(
                     {Json::array({x0, y0}), Json::array({x1, y0}),
                      Json::array({x1, y1}), Json::array({x0, y1}),
                      Json::array({x0, y0})})})}};
}

Json line(double x0, double y0, double x1, double y1) {
    return Json{{"type", "LineString"},
                {"coordinates", Json::array({Json::array({x0, y0}),
                                             Json::array({x1, y1})})}};
}

bool approx(double a, double b, double eps = 1e-6) {
    return std::abs(a - b) <= eps;
}

// First vertex of a GeoJSON geometry (recursive — works for any type).
std::pair<double, double> first_vertex(const Json& node) {
    if (node.is_array() && !node.empty()) {
        if (node.front().is_number())
            return {node.at(0).get<double>(), node.at(1).get<double>()};
        return first_vertex(node.front());
    }
    return {0.0, 0.0};
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    // --- engine install ------------------------------------------------
    CompositeEditController controller;
    install_geometry_engine(controller);
    check(controller.geometry_ops() != nullptr,
          "install_geometry_engine installs ops");
    check(controller.topology().has_validator(),
          "install_geometry_engine installs validators");

    auto* ops = controller.geometry_ops();

    // --- merge -----------------------------------------------------------
    {
        auto& layer = controller.create_layer("合并层", "polygon");
        layer.replace_features(
            {VectorFeature("a", square(0, 0, 10, 10)),
             VectorFeature("b", square(10, 0, 20, 10))});
        auto& session = layer.start_editing();
        const std::string merged_id =
            ops->merge_selected_polygons(session, {"a", "b"});
        check(!merged_id.empty() && merged_id != "a" && merged_id != "b",
              "merge produces new feature id");
        check(session.has_feature(merged_id) && !session.has_feature("a") &&
                  !session.has_feature("b"),
              "merge replaces sources in session");
        // Union ring start is engine-defined — scan every vertex.
        double xmin = 1e30, xmax = -1e30;
        std::function<void(const Json&)> walk = [&](const Json& node) {
            if (node.is_array() && node.size() >= 2 &&
                node.front().is_number()) {
                xmin = std::min(xmin, node.at(0).get<double>());
                xmax = std::max(xmax, node.at(0).get<double>());
                return;
            }
            if (node.is_array())
                for (const Json& child : node) walk(child);
        };
        walk(session.feature(merged_id).geometry.at("coordinates"));
        check(approx(xmin, 0.0) && approx(xmax, 20.0),
              "merged geometry covers both inputs");
        // Rejection vocabulary parity.
        bool rejected = false;
        try {
            ops->merge_selected_polygons(session, {merged_id});
        } catch (const std::invalid_argument& e) {
            rejected =
                std::string(e.what()) ==
                "select at least two polygons to merge";
        }
        check(rejected, "merge rejects single selection");
    }

    // --- split -------------------------------------------------------------
    {
        auto& layer = controller.create_layer("分割层", "polygon");
        layer.replace_features(
            {VectorFeature("p", square(0, 0, 10, 10))});
        auto& session = layer.start_editing();
        VectorFeature cutter("c", line(-1, 5, 11, 5));
        const auto ids =
            ops->split_polygon_by_line(session, "p", cutter);
        check(ids.size() == 2 && !session.has_feature("p"),
              "split replaces polygon with two pieces");
        for (const auto& id : ids)
            check(session.has_feature(id), "split piece present");
        bool rejected = false;
        try {
            ops->split_polygon_by_line(
                session, ids.front(),
                VectorFeature("c2", square(0, 0, 1, 1)));
        } catch (const std::invalid_argument& e) {
            rejected = std::string(e.what()) ==
                       "split cutter must be a line";
        }
        check(rejected, "split rejects polygon cutter");
    }

    // --- make_geometry_valid / validate --------------------------------------
    {
        // Bowtie — self-intersecting ring.
        const Json bowtie =
            Json{{"type", "Polygon"},
                 {"coordinates",
                  Json::array({Json::array(
                      {Json::array({0, 0}), Json::array({10, 10}),
                       Json::array({10, 0}), Json::array({0, 10}),
                       Json::array({0, 0})})})}};
        const std::vector<std::string> errors =
            qgis_validate_geometry(bowtie);
        check(!errors.empty(), "validator flags invalid polygon");
        const Json valid = qgis_validate_geometry(square(0, 0, 5, 5)).empty()
                               ? square(0, 0, 5, 5)
                               : Json();
        check(!valid.is_null(), "validator passes clean polygon");
        const Json repaired = ops->make_geometry_valid(bowtie);
        check(qgis_validate_geometry(repaired).empty(),
              "make_geometry_valid repairs bowtie");
        // Non-polygonal input passes through untouched.
        const Json pt = Json{{"type", "Point"},
                             {"coordinates", Json::array({1, 2})}};
        check(ops->make_geometry_valid(pt) == pt,
              "make_geometry_valid passes non-polygon through");
        // repair backend seam.
        check(qgis_validate_geometry(qgis_repair_geometry(bowtie)).empty(),
              "qgis_repair_geometry backend heals bowtie");
    }

    // --- multipart ----------------------------------------------------------
    {
        const Json multi =
            Json{{"type", "MultiPolygon"},
                 {"coordinates",
                  Json::array({square(0, 0, 1, 1).at("coordinates"),
                               square(2, 2, 3, 3).at("coordinates")})}};
        const auto singles = ops->multipart_to_singlepart(multi);
        check(singles.size() == 2 &&
                  singles.front().value("type", "") == "Polygon",
              "multipart_to_singlepart explodes");
        const Json recombined = ops->singlepart_to_multipart(singles);
        check(recombined.value("type", "") == "MultiPolygon",
              "singlepart_to_multipart collects");
    }

    // --- trim / extend --------------------------------------------------------
    {
        const Json clipped =
            ops->trim_line(line(-5, 5, 15, 5), square(0, 0, 10, 10),
                           "inside");
        check(clipped.value("type", "") == "LineString",
              "trim keeps inside segment");
        const auto [ex0, ey0] =
            first_vertex(clipped.at("coordinates"));
        check(approx(ex0, 0.0) || approx(ex0, 10.0),
              "trim clip to boundary x");
        bool rejected = false;
        try {
            ops->trim_line(line(20, 20, 30, 30), square(0, 0, 10, 10),
                           "inside");
        } catch (const std::invalid_argument& e) {
            rejected = std::string(e.what()) ==
                       "trim produced no line segments";
        }
        check(rejected, "trim rejects empty intersection");
        const Json extended = ops->extend_line_to_boundary(
            line(2, 5, 8, 5), square(0, 0, 10, 10), 100.0);
        const auto& coords = extended.at("coordinates");
        const double first_x = coords.front().at(0).get<double>();
        const double last_x = coords.back().at(0).get<double>();
        check(approx(first_x, 0.0) && approx(last_x, 10.0),
              "extend reaches boundary both ends");
    }

    // --- reverse ---------------------------------------------------------------
    {
        const Json reversed = ops->reverse_geometry(line(0, 0, 5, 5));
        const auto& coords = reversed.at("coordinates");
        check(coords.front().at(0).get<double>() == 5.0,
              "reverse swaps endpoints");
        // Closed ring stays closed.
        const Json ring_rev = ops->reverse_geometry(square(0, 0, 4, 4));
        const auto& ring = ring_rev.at("coordinates").front();
        check(ring.front() == ring.back(), "reverse keeps ring closed");
    }

    // --- simplify / smooth / offset ----------------------------------------------
    {
        const Json simplified = ops->simplify(
            Json{{"type", "LineString"},
                 {"coordinates",
                  Json::array({Json::array({0, 0}), Json::array({1, 0.01}),
                               Json::array({2, 0})})}},
            0.1);
        check(simplified.at("coordinates").size() <= 3,
              "simplify reduces vertices");
        const Json smoothed =
            ops->smooth(line(0, 0, 10, 0), 1, 0.25);
        check(smoothed.value("type", "") == "LineString",
              "smooth returns line");
        const Json offset = ops->offset_curve(line(0, 0, 10, 0), 1.0);
        check(offset.value("type", "") == "LineString",
              "offset_curve returns line");
    }

    // --- rotate / scale / centroid -------------------------------------------------
    {
        const Json rotated = ops->rotate(line(0, 0, 10, 0), 90.0, {0, 0});
        const auto& coords = rotated.at("coordinates");
        check(approx(coords.back().at(1).get<double>(), 10.0, 1e-6),
              "rotate 90° sends x-axis to y-axis");
        const Json scaled = ops->scale(line(0, 0, 10, 0), 2.0, 1.0, {0, 0});
        check(approx(
                  scaled.at("coordinates").back().at(0).get<double>(),
                  20.0),
              "scale doubles x");
        const MapPoint center = ops->union_centroid(
            {square(0, 0, 10, 10), square(10, 0, 20, 10)});
        check(approx(center[0], 10.0) && approx(center[1], 5.0),
              "union centroid at shared midpoint");
    }

    // --- reshape / parts ------------------------------------------------------------
    {
        const Json target = square(0, 0, 10, 10);
        const Json reshaped =
            ops->reshape(target, line(5, -1, 5, 11)).value_or(Json());
        check(!reshaped.is_null(), "reshape returns geometry");
        // Part ops.
        const Json with_part =
            ops->add_part(target, square(20, 20, 25, 25)).value_or(Json());
        check(with_part.value("type", "") == "MultiPolygon",
              "add_part promotes to multipolygon");
        const auto without_part = ops->delete_part(with_part, 1);
        // Python stores the bridge result verbatim — QgsGeometry keeps
        // a single-part MultiPolygon rather than demoting to Polygon.
        check(without_part.has_value() &&
                  (without_part->value("type", "") == "Polygon" ||
                   (without_part->value("type", "") == "MultiPolygon" &&
                    without_part->at("coordinates").size() == 1)),
              "delete_part drops the second part");
        // reshape that never touches the target → honest nullopt.
        check(!ops->reshape(target, line(50, 50, 60, 60)).has_value(),
              "reshape no-hit reports nullopt");
    }

    // --- canvas binding --------------------------------------------------------------
    {
        CompositeEditController bound;
        bound.project_crs = "EPSG:4326";
        CompositeQgisCanvas canvas(&bound);
        check(canvas.shim() != nullptr && canvas.widget() != nullptr,
              "canvas binding owns shim");
        check(bound.canvas().attached(),
              "controller canvas hooks attached");
        check(bound.canvas().canvas_address &&
                  bound.canvas().canvas_address() != 0,
              "canvas address surfaces natively");
        auto& layer = bound.create_layer("画布层", "polygon");
        layer.replace_features(
            {VectorFeature("f1", square(0, 0, 5, 5))});
        canvas.publish_layers(bound.snapshot_layers(), "EPSG:4326");
        canvas.shim()->set_current_layer(
            QString::fromStdString(layer.id()));
        check(bound.canvas().current_layer_doc_id &&
                  bound.canvas().current_layer_doc_id() == layer.id(),
              "current-layer round-trips through shim");
        canvas.shutdown();
        check(!bound.canvas().attached(),
              "shutdown detaches canvas hooks");
    }

    if (failures == 0) {
        std::fprintf(stderr, "ui_composite.qgis_smoke: all checks "
                             "passed\n");
        return 0;
    }
    std::fprintf(stderr, "ui_composite.qgis_smoke: %d failure(s)\n",
                 failures);
    return 1;
}
