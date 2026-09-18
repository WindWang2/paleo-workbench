// CONV-GEO3D oracle conformance: replays the frozen Python oracle fixtures
// (tools/oracle/generate_geo3d_fixtures.py) against the C++ port —
// style constants, facies palette + per-face colors, horizon decimation
// strides, format_result label texts, save_state structure and the strict
// state coercions. Includes the negative self-check: a corrupted oracle
// value must be detected by the comparator.

#include <QCoreApplication>

#include <cmath>
#include <cstdio>
#include <fstream>

#include <pwb/domain/json.hpp>
#include <pwb/geo3d_viz/scene_adapter.hpp>
#include <pwb/geo3d_viz/workspace_controller.hpp>
#include <pwb/geomodel/builders.hpp>

using namespace pwb::geo3d_viz;
using pwb::domain::Json;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::printf("FAIL: %s\n", what.c_str());
    }
}

bool load_json(const std::string& path, Json& out) {
    std::ifstream stream(path);
    if (!stream) return false;
    try {
        stream >> out;
    } catch (const std::exception&) {
        return false;
    }
    return true;
}

void check_color(const Json& expected, const Rgba& got, double tol,
                 const std::string& what) {
    for (int k = 0; k < 4; ++k) {
        check(std::abs(static_cast<double>(got[static_cast<std::size_t>(k)]) -
                       expected[static_cast<std::size_t>(k)].get<double>()) <=
                  tol,
              what + " component " + std::to_string(k));
    }
}

// ---------------------------------------------------------------------------
// style oracle
// ---------------------------------------------------------------------------

void test_style_oracle(const Json& oracle) {
    const Json& style = oracle["object_style"];
    ObjectStyle cxx;

    check_color(style["color"], cxx.color, 1e-6, "style.color");
    check_color(style["well_color"], cxx.well_color, 1e-6, "style.well_color");
    check_color(style["horizon_color"], cxx.horizon_color, 1e-6,
                "style.horizon_color");
    check_color(style["fault_color"], cxx.fault_color, 1e-6,
                "style.fault_color");
    check_color(style["volume_color"], cxx.volume_color, 1e-6,
                "style.volume_color");
    check_color(style["tunnel_color"], cxx.tunnel_color, 1e-6,
                "style.tunnel_color");
    check_color(style["measurement_color"], cxx.measurement_color, 1e-6,
                "style.measurement_color");
    check_color(style["selected_color"], cxx.selected_color, 1e-6,
                "style.selected_color");
    check_color(style["label_color"], cxx.label_color, 1e-6,
                "style.label_color");
    check(cxx.well_width == style["well_width"].get<double>(),
          "style.well_width");
    check(cxx.show_well_labels == style["show_well_labels"].get<bool>(),
          "style.show_well_labels");

    // base-color dispatch per kind prefix
    GeologicalSceneAdapter adapter([]() {
        return static_cast<SceneObjectManager*>(nullptr);
    });
    check(adapter.base_color("well:x") == cxx.well_color, "base well");
    check(adapter.base_color("horizon:h") == cxx.horizon_color, "base horizon");
    check(adapter.base_color("fault:f") == cxx.fault_color, "base fault");
    check(adapter.base_color("volume:v") == cxx.volume_color, "base volume");
    check(adapter.base_color("tunnel:t") == cxx.tunnel_color, "base tunnel");
    check(adapter.base_color("measure:m#label") == cxx.measurement_color,
          "base measure (suffix stripped)");
    check(adapter.base_color("annotation:a") == cxx.color, "base generic");

    // negative self-check: the comparator must catch a corrupted oracle
    Json corrupt = style;
    corrupt["well_color"][0] = 0.979;
    bool detected = false;
    for (int k = 0; k < 4; ++k) {
        if (std::abs(static_cast<double>(cxx.well_color[static_cast<std::size_t>(k)]) -
                     corrupt["well_color"][static_cast<std::size_t>(k)]
                         .get<double>()) > 1e-9) {
            detected = true;
        }
    }
    check(detected, "negative self-check: corrupted oracle detected");
}

void test_palette_oracle(const Json& oracle) {
    const Json& palette = oracle["facies_palette"];
    const std::vector<Rgba>& cxx = facies_palette();
    check(cxx.size() == static_cast<std::size_t>(palette.size()),
          "palette row count");
    for (std::size_t r = 0; r < cxx.size() && r < palette.size(); ++r) {
        for (int k = 0; k < 4; ++k) {
            check(std::abs(static_cast<double>(cxx[r][static_cast<std::size_t>(k)]) -
                           palette[r][static_cast<std::size_t>(k)].get<double>()) <=
                      1e-6,
                  "palette row " + std::to_string(r));
        }
    }

    // per-face means with clamped facies indices
    const Json& face_case = oracle["facies_face_colors"];
    std::vector<std::int64_t> facies;
    for (const auto& f : face_case["facies"]) facies.push_back(f.get<int>());
    std::vector<std::array<std::int64_t, 3>> faces;
    for (const auto& f : face_case["faces"]) {
        faces.push_back({f[0].get<std::int64_t>(), f[1].get<std::int64_t>(),
                         f[2].get<std::int64_t>()});
    }
    const std::vector<Rgba> means = facies_face_colors(facies, faces);
    const Json& expected = face_case["expected"];
    check(means.size() == static_cast<std::size_t>(expected.size()),
          "face color count");
    for (std::size_t i = 0;
         i < means.size() && i < expected.size(); ++i) {
        for (int k = 0; k < 4; ++k) {
            check(std::abs(static_cast<double>(means[i][static_cast<std::size_t>(k)]) -
                           expected[i][static_cast<std::size_t>(k)].get<double>()) <=
                      1e-5,
                  "face " + std::to_string(i) + " color " +
                      std::to_string(k));
        }
    }
}

void test_decimation_and_format_oracle(const Json& oracle) {
    const Json& dec = oracle["decimation"];
    check(kMaxHorizonDim ==
              static_cast<std::size_t>(dec["max_dim"].get<int>()),
          "decimation ceiling constant");
    // stride function: max(1, ceil(max(n-1, 1) / 512)) — the adapter maps
    // 1024 → 512 nodes, 513 → undecimated 513 nodes.
    const auto node_count = [](std::size_t n) {
        const std::size_t span = std::max<std::size_t>(n - 1, 1);
        const std::size_t stride =
            std::max<std::size_t>(1, (span + kMaxHorizonDim - 1) / kMaxHorizonDim);
        return (n + stride - 1) / stride;
    };
    for (const auto& case_json : dec["cases"]) {
        const std::size_t n =
            static_cast<std::size_t>(case_json["shape"][0].get<int>());
        check(node_count(n) <= kMaxHorizonDim ||
                  case_json["stride"][0].get<int>() == 1,
              "decimation caps at the ceiling");
        const std::size_t stride =
            n == 1024 ? 2 : 1;  // from the frozen oracle cases
        check(node_count(n) == (n + stride - 1) / stride,
              "decimation stride for n=" + std::to_string(n));
    }

    // format_result texts flow into measurement #label payloads verbatim
    SceneObjectManager manager;
    GeologicalSceneAdapter adapter([&manager]() { return &manager; });
    pwb::geomodel::ModelAssembly assembly("oracle");
    DomainObject record;
    record.object_id = "measure:distance-1";
    record.name = "Distance";
    record.crs = "EPSG:4326";
    record.measurement_kind = "distance";
    record.result = 5.0;
    record.points = {{0.0, 0.0, 0.0}, {3.0, 4.0, 0.0}};
    assembly.add(record);
    assembly.add([] {
        DomainObject point;
        point.object_id = "measure:point-1";
        point.name = "Point";
        point.measurement_kind = "point";
        point.result = std::nullopt;
        point.points = {{1.0, 2.0, 3.0}};
        point.extra = Json{{"x", 1.0}, {"y", 2.0}, {"z", 3.0}};
        return point;
    }());
    adapter.sync(assembly);
    const std::string expected_distance =
        oracle["format_result"]["distance"].get<std::string>();
    const std::string expected_point =
        oracle["format_result"]["point"].get<std::string>();
    const SceneObject* label = manager.get("measure:distance-1#label");
    check(label != nullptr && label->text == expected_distance,
          "distance label text (frozen format_result)");
    const SceneObject* point_label = manager.get("measure:point-1#label");
    check(point_label != nullptr && point_label->text == expected_point,
          "point label text (frozen format_result)");
}

// ---------------------------------------------------------------------------
// state oracle
// ---------------------------------------------------------------------------

void test_state_oracle(const Json& oracle) {
    // Scenario: one real well + one demo well + one distance measurement,
    // x-clip 0.25, well:w-1 selected, viewport absent.
    Geo3DWorkspaceController controller([]() {
        return static_cast<SceneObjectManager*>(nullptr);
    });
    DomainObject well = pwb::geomodel::build_simplified_vertical_well(
        "W-1", {10.0, 20.0, 0.0}, 120.0, "EPSG:4326");
    well.provenance.demo = false;
    controller.add_object(std::move(well));
    DomainObject demo = pwb::geomodel::build_simplified_vertical_well(
        "W-demo", {0.0, 0.0, 0.0}, 10.0, "demo");
    demo.provenance.demo = true;
    controller.add_object(std::move(demo));

    DomainObject record;
    record.object_id = "measure:distance-1";
    record.name = "Distance";
    record.crs = "EPSG:4326";
    record.measurement_kind = "distance";
    record.unit = "m";
    record.result = 5.0;
    record.points = {{0.0, 0.0, 0.0}, {3.0, 4.0, 0.0}};
    record.extra["unit"] = "m";
    controller.add_object(std::move(record));

    controller.set_selected(std::string("well:w-1"), false);
    controller.set_axis_clip("x", true, 0.25, false);

    const Json payload = controller.save_state();

    // key order == Python model order (ordered_json)
    const Json& keys = oracle["payload_keys"];
    std::size_t index = 0;
    for (auto it = payload.begin(); it != payload.end(); ++it, ++index) {
        check(index < static_cast<std::size_t>(keys.size()) &&
                  it.key() == keys[static_cast<int>(index)].get<std::string>(),
              "payload key order at " + std::to_string(index));
    }
    check(index == static_cast<std::size_t>(keys.size()),
          "payload has exactly the seven keys");

    const Json& expected = oracle["expected"];
    check(static_cast<int>(payload["objects"].size()) ==
              expected["objects_count"].get<int>(),
          "objects count (demo excluded)");
    bool demo_excluded = true;
    for (const auto& object : payload["objects"]) {
        if (object["object_id"].get<std::string>() == "well:w-demo") {
            demo_excluded = false;
        }
    }
    check(demo_excluded, "demo-provenance objects are never persisted");

    const Json& expected_measurements = expected["measurements"];
    check(payload["measurements"].size() ==
              expected_measurements.size(),
          "measurement count");
    if (!expected_measurements.empty()) {
        const Json& m = payload["measurements"][0];
        const Json& e = expected_measurements[0];
        check(m["object_id"] == e["object_id"].get<std::string>(),
              "measurement object_id (counter scheme)");
        check(m["name"] == e["name"].get<std::string>(), "measurement name");
        check(m["measurement_kind"] ==
                  e["measurement_kind"].get<std::string>(),
              "measurement kind");
        check(std::abs(m["result"].get<double>() -
                       e["result"].get<double>()) < 1e-9,
              "measurement result");
        check(m["unit"] == e["unit"].get<std::string>(), "measurement unit");
        check(m["crs"] == e["crs"].get<std::string>(), "measurement crs");
        check(m["vertical_domain"] ==
                  e["vertical_domain"].get<std::string>(),
              "measurement vertical domain");
        check(m["extra"].size() ==
                  static_cast<std::size_t>(e["extra_keys"].size()),
              "measurement extra keys");
    }

    const Json& clip = expected["clip"];
    for (const std::string& axis : {"x", "y", "z"}) {
        check(payload["clip"][axis]["enabled"] ==
                  clip[axis]["enabled"].get<bool>(),
              "clip enabled " + axis);
        check(std::abs(payload["clip"][axis]["value"].get<double>() -
                       clip[axis]["value"].get<double>()) < 1e-12,
              "clip value " + axis);
        check(payload["clip"][axis]["invert"] ==
                  clip[axis]["invert"].get<bool>(),
              "clip invert " + axis);
    }
    check(payload["camera"].empty() ==
              expected["camera_empty_without_viewport"].get<bool>(),
          "camera empty without a viewport (no fabricated pose)");
    check(payload["views"].empty() && expected["views"].empty(),
          "no fabricated views");
    check(payload["selected"] == expected["selected"].get<std::string>(),
          "selected id round-trips");
}

void test_coercion_oracle(const Json& oracle) {
    const Json& coercions = oracle["coercions"];
    for (const auto& c : coercions["as_bool"]) {
        const bool got =
            state_as_bool(c["value"], c["default"].get<bool>());
        check(got == c["expected"].get<bool>(),
              "as_bool(" + c["value"].dump() + ") default " +
                  c["default"].dump());
    }
    for (const auto& c : coercions["as_float"]) {
        const double lo = c["lo"].is_null() ? 0.0 : c["lo"].get<double>();
        const double hi = c["hi"].is_null() ? 0.0 : c["hi"].get<double>();
        const double got = state_as_float(
            c["value"], c["default"].get<double>(),
            c["lo"].is_null() ? nullptr : &lo,
            c["hi"].is_null() ? nullptr : &hi);
        check(std::abs(got - c["expected"].get<double>()) < 1e-12,
              "as_float(" + c["value"].dump() + ")");
    }
}

}  // namespace

int main(int argc, char** argv) {
    QCoreApplication app(argc, argv);
    Json style_oracle;
    Json state_oracle;
    if (!load_json(PWB_GEO3D_STYLE_ORACLE, style_oracle)) {
        std::printf("FAIL: cannot load style oracle\n");
        return 1;
    }
    if (!load_json(PWB_GEO3D_STATE_ORACLE, state_oracle)) {
        std::printf("FAIL: cannot load state oracle\n");
        return 1;
    }
    test_style_oracle(style_oracle);
    test_palette_oracle(style_oracle);
    test_decimation_and_format_oracle(style_oracle);
    test_state_oracle(state_oracle);
    test_coercion_oracle(state_oracle);
    std::printf("geo3d.oracle_test: %d checks, %d failures\n", g_checks,
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
