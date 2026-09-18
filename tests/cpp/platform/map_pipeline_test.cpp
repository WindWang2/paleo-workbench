// platform.map_pipeline — CONV-01: the REAL MainWindow runs the frozen
// mapping_kernel chain behind the 地质因子图 action (well points ->
// extract_factors -> IDW/kriging -> marching-squares contours + facies
// polygons -> QgsVectorLayer memory layers). Two gates in one process:
//
//   1. Oracle reconciliation — every case of the fixture frozen by
//      tools/oracle/generate_map_pipeline_fixtures.py from the REAL Python
//      product (11 cases: idw/kriging, default/explicit levels+thresholds,
//      qc filter, undeclared CRS, validate-error wording, all-NaN, partial
//      NaN, constant field, projected CRS, audit-#1150 zero coordinate).
//      The runner's
//      grid, features, statistics and error text must match the Python
//      product.
//   2. User flow E2E — run through the window API the menu action calls:
//      the two product layers appear in the layer tree (contour/polygon,
//      non-empty, oracle attribute readback), re-runs regenerate in place,
//      failure branches surface the exact kernel message, and the
//      factor_workbench policy row keeps the no-project gate.

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <string>
#include <vector>

#include <QFile>
#include <QTemporaryDir>
#include <qgsapplication.h>
#include <qgsfeature.h>
#include <qgsfields.h>
#include <qgsgeometry.h>
#include <qgsproject.h>
#include <qgsvectorlayer.h>

#include <pwb/application/map_pipeline_runner.hpp>
#include <pwb/qgis/layer_adapter.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/tool_policy/tool_availability.hpp>

#include "main_window.hpp"

#include "test_fixtures.hpp"
#include "test_framework.hpp"

namespace fs = std::filesystem;
using pwb::app::MainWindow;
using pwb::domain::Json;

namespace {

bool number_close(const Json& value, double expected, double tol) {
    return value.is_number()
        && std::fabs(value.get<double>() - expected) <= tol;
}

// Relative-aware close for large magnitudes (area_approx_m2 is ~1e8 where
// a binary/decimal round(…, 4) boundary flip is far above an absolute
// 2e-4 but far below double epsilon).
bool number_close_rel(const Json& value, double expected, double abs_tol) {
    if (!value.is_number()) return false;
    const double actual = value.get<double>();
    return std::fabs(actual - expected)
        <= std::max(abs_tol, 1e-9 * std::fabs(expected));
}

// Statistics entries are NaN on all-nodata grids: the frozen oracle writes
// null, the C++ diagnostics carry a NaN double.
bool stats_close(const Json& produced, const Json& frozen,
                 const char* key, const std::string& name) {
    if (frozen.at(key).is_null()) {
        const Json& value = produced.at(key);
        const bool nan_ok = value.is_number()
            && std::isnan(value.get<double>());
        PWB_CHECK_MSG(nan_ok,
                      name + " stats " + key
                          + " should be NaN on the all-nodata grid");
        return nan_ok;
    }
    const bool ok = number_close(produced.at(key),
                                 frozen.at(key).get<double>(), 1e-9);
    PWB_CHECK_MSG(ok, name + " stats " + key);
    return ok;
}

bool same_bool(const Json& value, bool expected) {
    return value.is_boolean() && value.get<bool>() == expected;
}

bool same_string(const Json& value, const std::string& expected) {
    return value.is_string() && value.get<std::string>() == expected;
}

bool coordinate_lists_close(const Json& frozen, const Json& produced,
                            double tol, std::string* why) {
    if (!frozen.is_array() || !produced.is_array()
        || frozen.size() != produced.size()) {
        *why = "coordinate list size/type mismatch";
        return false;
    }
    for (std::size_t i = 0; i < frozen.size(); ++i) {
        const Json& f = frozen[i];
        const Json& p = produced[i];
        if (f.is_array() && f.size() == 2 && p.is_array() && p.size() == 2) {
            if (!number_close(p[0], f[0].get<double>(), tol)
                || !number_close(p[1], f[1].get<double>(), tol)) {
                *why = "coordinate value mismatch at " + std::to_string(i);
                return false;
            }
            continue;
        }
        if (!coordinate_lists_close(f, p, tol, why)) return false;
    }
    return true;
}

pwb::application::MapPipelineRequest request_from_case(const Json& request) {
    pwb::application::MapPipelineRequest out;
    out.factor_name = request.at("factor_name").get<std::string>();
    out.target_horizon = request.at("target_horizon").get<std::string>();
    if (!request.at("unit").is_null()) {
        out.unit = request.at("unit").get<std::string>();
    }
    out.crs = request.at("crs").get<std::string>();
    out.method = request.at("method").get<std::string>();
    out.grid_n = request.at("grid_n").get<int>();
    out.power = request.at("power").get<double>();
    out.min_neighbors = request.at("min_neighbors").get<int>();
    if (!request.at("search_radius").is_null()) {
        out.search_radius = request.at("search_radius").get<double>();
    }
    if (request.contains("contour_levels")
        && !request.at("contour_levels").is_null()) {
        for (const auto& level : request.at("contour_levels")) {
            out.contour_levels.push_back(level.get<double>());
        }
    }
    if (request.contains("class_thresholds")
        && !request.at("class_thresholds").is_null()) {
        for (const auto& th : request.at("class_thresholds")) {
            out.class_thresholds.push_back(th.get<double>());
        }
    }
    if (request.contains("facies_names")
        && !request.at("facies_names").is_null()) {
        for (const auto& name : request.at("facies_names")) {
            out.facies_names.push_back(name.get<std::string>());
        }
    }
    return out;
}

void compare_features(const Json& frozen_features, const Json& produced,
                      const char* kind, int* compared) {
    PWB_CHECK_MSG(produced.is_array(), kind);
    PWB_CHECK_MSG(produced.size() == frozen_features.size(),
                  std::string(kind) + ": feature count "
                      + std::to_string(produced.size()) + " != frozen "
                      + std::to_string(frozen_features.size()));
    for (std::size_t i = 0;
         i < frozen_features.size() && i < produced.size(); ++i) {
        const Json& f = frozen_features[i];
        const Json& p = produced[i];
        ++*compared;
        const std::string at =
            std::string(kind) + "[" + std::to_string(i) + "]";
        PWB_CHECK_MSG(same_string(p.at("type"), "Feature"), at);
        PWB_CHECK_MSG(same_string(p.at("geometry").at("type"),
                                  f.at("geometry").at("type")
                                      .get<std::string>()
                                      .c_str()),
                      at + " geometry type");
        std::string why;
        PWB_CHECK_MSG(coordinate_lists_close(
                          f.at("geometry").at("coordinates"),
                          p.at("geometry").at("coordinates"), 1e-9, &why),
                      at + " geometry: " + why);
        const Json& fp = f.at("properties");
        const Json& pp = p.at("properties");
        for (auto it = fp.begin(); it != fp.end(); ++it) {
            const Json& expected = it.value();
            if (!pp.contains(it.key())) {
                PWB_CHECK_MSG(false, at + " missing property " + it.key());
                continue;
            }
            const Json& actual = pp.at(it.key());
            if (expected.is_null()) {
                PWB_CHECK_MSG(actual.is_null(),
                              at + " property " + it.key());
            } else if (expected.is_boolean()) {
                PWB_CHECK_MSG(same_bool(actual, expected.get<bool>()),
                              at + " property " + it.key());
            } else if (expected.is_string()) {
                PWB_CHECK_MSG(same_string(actual,
                                          expected.get<std::string>()),
                              at + " property " + it.key());
            } else if (it.key() == "mean_value") {
                // np.mean over float32 cells accumulates in float32;
                // the runner sums in float64 — 1e-3 absorbs the rounding
                // boundary noise after round(v, 4).
                PWB_CHECK_MSG(number_close(actual, expected.get<double>(),
                                           1e-3),
                              at + " property " + it.key());
            } else if (it.key() == "area" || it.key() == "area_percent") {
                // round(v, 4): binary vs decimal half-even boundaries.
                PWB_CHECK_MSG(number_close(actual, expected.get<double>(),
                                           2e-4),
                              at + " property " + it.key());
            } else if (it.key() == "area_approx_m2") {
                PWB_CHECK_MSG(number_close_rel(actual,
                                               expected.get<double>(), 2e-4),
                              at + " property " + it.key());
            } else if (it.key() == "length") {
                PWB_CHECK_MSG(number_close(actual, expected.get<double>(),
                                           1e-9),
                              at + " property " + it.key());
            } else {
                PWB_CHECK_MSG(number_close(actual, expected.get<double>(),
                                           1e-12),
                              at + " property " + it.key());
            }
        }
        PWB_CHECK_MSG(pp.size() == fp.size(),
                      at + " property key set parity ("
                          + std::to_string(pp.size()) + " vs "
                          + std::to_string(fp.size()) + ")");
    }
}

void compare_case(const std::string& name, const Json& case_json,
                  int* compared_features) {
    const pwb::application::MapPipelineRequest request =
        request_from_case(case_json.at("request"));
    const pwb::application::MapPipelineOutcome outcome =
        pwb::application::run_map_pipeline(case_json.at("records"), request);

    if (case_json.contains("error")) {
        PWB_CHECK_MSG(!outcome.ok, name + ": expected failure");
        PWB_CHECK_MSG(outcome.error == case_json.at("error").get<std::string>(),
                      name + ": error wording drifted: '" + outcome.error
                          + "'");
        return;
    }
    PWB_CHECK_MSG(outcome.ok, name + ": runner failed: " + outcome.error);

    // --- grid: the pinned interpolation stage --------------------------
    const Json& frozen_grid = case_json.at("grid");
    const Json& grid = outcome.diagnostics.at("grid");
    PWB_CHECK(grid.at("width").get<int>() == frozen_grid.at("width").get<int>());
    PWB_CHECK(grid.at("height").get<int>() == frozen_grid.at("height").get<int>());
    {
        const Json& fx = frozen_grid.at("grid_x");
        const Json& gy_x = grid.at("grid_x");
        PWB_CHECK_MSG(gy_x.size() == fx.size(), name + " grid_x size");
        for (std::size_t i = 0; i < fx.size(); ++i) {
            PWB_CHECK_MSG(number_close(gy_x[i], fx[i].get<double>(), 1e-12),
                          name + " grid_x value");
        }
        const Json& fy = frozen_grid.at("grid_y");
        const Json& gy_y = grid.at("grid_y");
        PWB_CHECK_MSG(gy_y.size() == fy.size(), name + " grid_y size");
        for (std::size_t i = 0; i < fy.size(); ++i) {
            PWB_CHECK_MSG(number_close(gy_y[i], fy[i].get<double>(), 1e-12),
                          name + " grid_y value");
        }
        const Json& fz = frozen_grid.at("grid_z");
        const Json& pz = grid.at("grid_z");
        int nan_mismatches = 0;
        double max_diff = 0.0;
        for (std::size_t i = 0; i < fz.size() && i < pz.size(); ++i) {
            for (std::size_t j = 0; j < fz[i].size() && j < pz[i].size();
                 ++j) {
                const Json& f = fz[i][j];
                const Json& p = pz[i][j];
                if (f.is_null() || p.is_null()) {
                    if (!(f.is_null() && p.is_null())) ++nan_mismatches;
                    continue;
                }
                max_diff = std::max(
                    max_diff,
                    std::fabs(p.get<double>() - f.get<double>()));
            }
        }
        PWB_CHECK_MSG(nan_mismatches == 0,
                      name + " nodata pattern mismatch");
        PWB_CHECK_MSG(max_diff <= 1e-6,
                      name + " grid_z max_diff=" + std::to_string(max_diff));
    }

    // --- statistics (float64 on both sides; NaN ↔ null on all-nodata) ---
    const Json& fs = frozen_grid.at("statistics");
    const Json& ps = outcome.diagnostics.at("statistics");
    PWB_CHECK_MSG(ps.at("valid_count").get<int>()
                          == fs.at("valid_count").get<int>(),
                  name + " valid_count");
    stats_close(ps, fs, "min", name);
    stats_close(ps, fs, "max", name);
    stats_close(ps, fs, "mean", name);
    stats_close(ps, fs, "std", name);

    // --- distance policy annotation ------------------------------------
    const Json& params = frozen_grid.at("algorithm_parameters");
    PWB_CHECK_MSG(same_string(outcome.diagnostics.at("distance_policy"),
                              params.at("distance_policy")
                                  .get<std::string>()
                                  .c_str()),
                  name + " distance_policy");
    PWB_CHECK_MSG(same_string(
                      outcome.diagnostics.at("distance_policy_annotation"),
                      params.at("distance_policy_annotation")
                          .get<std::string>()
                          .c_str()),
                  name + " distance_policy_annotation");

    compare_features(case_json.at("contours").at("features"),
                     outcome.contour_features, "contours",
                     compared_features);
    compare_features(case_json.at("polygons").at("features"),
                     outcome.polygon_features, "polygons",
                     compared_features);

    if (name == "zero_coordinate_kept") {
        // Audit #1150 through the window: the (0,0) well survives, the
        // mixed-family record is skipped and counted, never cross-paired.
        const Json& meta = outcome.diagnostics.at("extract_metadata");
        PWB_CHECK_MSG(meta.at("skipped_missing_coordinates").get<int>() == 1,
                      name + " skipped_missing_coordinates");
        PWB_CHECK_MSG(meta.at("coordinate_key_families_used")
                              .at("xy")
                              .get<int>()
                          == 2,
                      name + " coordinate_key_families_used");
        PWB_CHECK_MSG(meta.contains("coordinate_key_family_mixing") == false,
                      name + " must not flag mixing for one family");
    }
}

// A memory point layer carrying the 8-well fixture as REAL QGIS features
// (the "选/导入井点" user path).
QgsVectorLayer* add_well_point_layer(MainWindow& window, const QString& id) {
    const QString uri =
        QStringLiteral("Point?crs=EPSG:4326&field=well_id:string(16)"
                       "&field=name:string(32)&field=qc_flag:string(8)"
                       "&field=%1:double").arg(QStringLiteral("孔隙度"));
    auto* layer = new QgsVectorLayer(uri, id, QStringLiteral("memory"));
    if (!layer->isValid()) {
        delete layer;
        return nullptr;
    }
    const pwb::qgis::LayerBinding binding{id.toStdString(), "", "", "vector"};
    pwb::qgis::layer_adapter::apply(layer, binding);
    window.session()->map().project()->addMapLayer(layer);
    const struct {
        const char* id;
        const char* name;
        double x;
        double y;
        double porosity;
    } wells[] = {
        {"W1", "井-1", 114.10, 22.50, 18.5}, {"W2", "井-2", 114.25, 22.52, 22.3},
        {"W3", "井-3", 114.38, 22.48, 15.2}, {"W4", "井-4", 114.15, 22.65, 24.1},
        {"W5", "井-5", 114.30, 22.68, 19.8}, {"W6", "井-6", 114.42, 22.62, 12.4},
        {"W7", "井-7", 114.20, 22.80, 26.5}, {"W8", "井-8", 114.35, 22.82, 21.0},
    };
    QgsFeatureList features;
    for (const auto& well : wells) {
        QgsFeature feature(layer->fields());
        feature.setAttribute(QStringLiteral("well_id"), well.id);
        feature.setAttribute(QStringLiteral("name"), well.name);
        feature.setAttribute(QStringLiteral("qc_flag"), "ok");
        feature.setAttribute(QStringLiteral("孔隙度"), well.porosity);
        feature.setGeometry(
            QgsGeometry::fromPointXY(QgsPointXY(well.x, well.y)));
        features.push_back(feature);
    }
    layer->dataProvider()->addFeatures(features);
    layer->updateExtents();

    pwb::application::DomainLayerFacts facts;
    facts.layer_id = id.toStdString();
    facts.role = "factor_input";
    facts.role_label = id.toStdString();
    facts.artifact_maturity = "raw";
    facts.write_granted = false;
    window.session()->set_active_layer(facts);
    return layer;
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    // ---- gate 1: oracle reconciliation over the frozen product chain ----
    {
        const QString fixture_path =
            pwb::test_fixtures::test_data_path(QStringLiteral(
                "fixtures/map_pipeline_oracle.json"));
        QFile file(fixture_path);
        PWB_CHECK_MSG(file.open(QIODevice::ReadOnly),
                      "cannot open oracle fixture: "
                          + fixture_path.toStdString());
        const QByteArray raw = file.readAll();
        Json root = Json::parse(raw.constData(), raw.constData() + raw.size());
        PWB_CHECK_MSG(root.contains("cases"), "fixture missing cases");
        int compared_features = 0;
        int cases_run = 0;
        for (auto it = root.at("cases").begin();
             it != root.at("cases").end(); ++it) {
            compare_case(it.key(), it.value(), &compared_features);
            ++cases_run;
        }
        PWB_CHECK_MSG(cases_run == 11, "expected 11 frozen cases, ran "
                          + std::to_string(cases_run));
        std::printf("oracle reconciliation: %d cases, %d features compared\n",
                    cases_run, compared_features);
        PWB_CHECK(compared_features >= 20);
    }

    // ---- gate 2: the user flow through the REAL MainWindow --------------
    {
        MainWindow window;

        // Builtin fixture flow (the menu action's default well source).
        const QString result = window.runGeologicalFactorMap(
            QStringLiteral("builtin.sample_wells"), "孔隙度", "idw", 30,
            "T1");
        PWB_CHECK_MSG(result.isEmpty(), result.toStdString());
        auto* session = window.session();
        QgsVectorLayer* contour =
            session->map().vectorLayerById("factor.contour");
        QgsVectorLayer* facies =
            session->map().vectorLayerById("factor.classification");
        PWB_CHECK_MSG(contour != nullptr, "contour layer missing from tree");
        PWB_CHECK_MSG(facies != nullptr, "facies layer missing from tree");
        // Oracle eight_well_idw_defaults (the exact request the window
        // API issues): 11 contour lines / 4 facies polygons.
        PWB_CHECK_MSG(contour->featureCount() == 11,
                      "contour count " + std::to_string(contour->featureCount()));
        PWB_CHECK_MSG(facies->featureCount() == 4,
                      "facies count " + std::to_string(facies->featureCount()));
        // Tree order (top-first) carries both product layers.
        bool has_contour = false;
        bool has_facies = false;
        for (const std::string& id : session->map().layerIdsTopFirst()) {
            if (id == "factor.contour") has_contour = true;
            if (id == "factor.classification") has_facies = true;
        }
        PWB_CHECK(has_contour && has_facies);
        // Attribute readback: the first contour feature is the level-15
        // index contour; the first polygon is the first facies class.
        const QgsFeature first_line = contour->getFeature(1);
        PWB_CHECK(first_line.isValid());
        PWB_CHECK(std::fabs(first_line.attribute("level").toDouble() - 14.0)
                  < 1e-9);
        PWB_CHECK(first_line.attribute("is_index_contour").toInt() == 1);
        PWB_CHECK(first_line.attribute("factor").toString()
                  == QStringLiteral("孔隙度"));
        PWB_CHECK(first_line.attribute("unit").toString()
                  == QStringLiteral("%"));
        PWB_CHECK(first_line.hasGeometry()
                  && first_line.geometry().type()
                      == Qgis::GeometryType::Line);
        const QgsFeature first_poly = facies->getFeature(1);
        PWB_CHECK(first_poly.isValid());
        PWB_CHECK(first_poly.attribute("facies_name").toString()
                  == QStringLiteral("低值相带"));
        PWB_CHECK(first_poly.attribute("facies_id").toInt() == 1);
        PWB_CHECK(first_poly.attribute("area_unit").toString()
                  == QStringLiteral("deg²"));
        PWB_CHECK(first_poly.hasGeometry()
                  && first_poly.geometry().type() == Qgis::GeometryType::Polygon);

        // Idempotent re-run: regenerate in place, no duplicate layers.
        const int layers_before =
            static_cast<int>(session->map().layerIdsTopFirst().size());
        const QString rerun = window.runGeologicalFactorMap(
            QStringLiteral("builtin.sample_wells"), "孔隙度", "idw", 30,
            "T1");
        PWB_CHECK_MSG(rerun.isEmpty(), rerun.toStdString());
        PWB_CHECK(static_cast<int>(session->map().layerIdsTopFirst().size())
                  == layers_before);
        PWB_CHECK(session->map().vectorLayerById("factor.contour")
                      ->featureCount() == 11);
        PWB_CHECK(session->map().vectorLayerById("factor.classification")
                      ->featureCount() == 4);

        // Failure branch: the builtin fixture carries no 砂岩厚度 values —
        // the kernel's validate() message surfaces verbatim.
        const QString factor_error = window.runGeologicalFactorMap(
            QStringLiteral("builtin.sample_wells"), "砂岩厚度", "idw", 30,
            "T1");
        PWB_CHECK_MSG(
            factor_error.toStdString()
                == "Insufficient sample points (0); at least 2 valid "
                   "points required for spatial interpolation.",
            "unexpected error: " + factor_error.toStdString());

        // User path: import the 8 wells as a REAL point layer, then run.
        QgsVectorLayer* wells_layer =
            add_well_point_layer(window, QStringLiteral("well_points"));
        PWB_CHECK_MSG(wells_layer != nullptr, "well point layer add failed");
        PWB_CHECK(wells_layer->featureCount() == 8);
        const QString layer_result = window.runGeologicalFactorMap(
            QStringLiteral("well_points"), "孔隙度", "idw", 30, "T1");
        PWB_CHECK_MSG(layer_result.isEmpty(), layer_result.toStdString());
        PWB_CHECK(session->map().vectorLayerById("factor.contour")
                      ->featureCount() == 11);
        PWB_CHECK(session->map().vectorLayerById("factor.classification")
                      ->featureCount() == 4);

        // Non-point well source is rejected honestly.
        QTemporaryDir temp_dir;
        const QString gpkg_uri =
            pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
        PWB_CHECK(!gpkg_uri.isEmpty());
        const QString open_error = window.openVectorLayer(gpkg_uri);
        PWB_CHECK_MSG(open_error.isEmpty(), open_error.toStdString());
        const QString kind_error = window.runGeologicalFactorMap(
            QStringLiteral("fixture"), "孔隙度", "idw", 30, "T1");
        PWB_CHECK_MSG(kind_error.toStdString().find("井点源必须是点图层") == 0,
                      "unexpected error: " + kind_error.toStdString());

        // Point layer WITHOUT a factor/value field: honest rejection.
        {
            const QString uri = QStringLiteral(
                "Point?crs=EPSG:4326&field=well_id:string(16)");
            auto* bare = new QgsVectorLayer(uri, QStringLiteral("bare"),
                                            QStringLiteral("memory"));
            PWB_CHECK(bare->isValid());
            pwb::qgis::LayerBinding bare_binding{"bare_points", "", "",
                                                 "vector"};
            pwb::qgis::layer_adapter::apply(bare, bare_binding);
            window.session()->map().project()->addMapLayer(bare);
            QgsFeature f(bare->fields());
            f.setGeometry(
                QgsGeometry::fromPointXY(QgsPointXY(1.0, 2.0)));
            QgsFeatureList bare_features{f};
            bare->dataProvider()->addFeatures(bare_features);
            const QString field_error = window.runGeologicalFactorMap(
                QStringLiteral("bare_points"), "孔隙度", "idw", 30, "T1");
            PWB_CHECK_MSG(
                field_error.toStdString().find("图层缺少因子取值字段") == 0,
                "unexpected error: " + field_error.toStdString());
        }

        // ---- policy wiring: governed action + no-project gate ----------
        // The factor_workbench rule (project_gate) pre-exists in the
        // canonical evaluator; this task wires the 地质因子图 action to it
        // and pins the no-project verdict here.
        PWB_CHECK(window.actionWired("factor_workbench"));
        QAction* action = window.governedAction("factor_workbench");
        PWB_CHECK(action != nullptr);
        PWB_CHECK(action->text() == QObject::tr("地质因子图…"));
        {
            pwb::tool_policy::ToolContextSnapshot closed;
            closed.project_open = false;
            const auto verdict =
                pwb::tool_policy::evaluate_tool("factor_workbench", closed);
            PWB_CHECK(!verdict.enabled);
            PWB_CHECK(verdict.disabled_reason == "未打开工程");
        }
        {
            const auto availability =
                pwb::tool_policy::evaluate_all(session->snapshot());
            PWB_CHECK(availability.at("factor_workbench").enabled);
        }

        window.close();
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.map_pipeline");
}
