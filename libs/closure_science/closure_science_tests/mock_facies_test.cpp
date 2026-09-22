// Mock facies provider coverage (stage_actions run_well_facies_mock /
// run_seismic_facies_mock parity): model seeding is idempotent, the well
// provider emits per-well predicted regions + well_detail (INTERMEDIATE
// payload), the seismic provider emits VECTOR_POLYGONS spatial features +
// mock_grid, and both refuse honestly on missing inputs. The providers
// share execute_run with the demo/onnx paths (covered by core_test), so
// this file pins the provider-level contract the stage actions rely on.
#include <pwb/catalog/models.hpp>
#include <pwb/catalog/model_registry.hpp>
#include <pwb/catalog/service_core.hpp>
#include <pwb/closure_science/inference_service.hpp>
#include <pwb/closure_science/model_seed.hpp>
#include <pwb/closure_science/providers.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/project/manager.hpp>

#include <cstdio>
#include <cstdlib>
#ifdef _WIN32
#include <process.h>  // _getpid
#else
#include <unistd.h>
#endif
namespace { long test_pid() {
#ifdef _WIN32
    return static_cast<long>(_getpid());
#else
    return static_cast<long>(::getpid());
#endif
} }
#include <filesystem>
#include <string>

namespace {

namespace fs = std::filesystem;
using pwb::catalog::CatalogDocument;
using pwb::catalog::CatalogServiceCore;
using pwb::domain::Json;
using pwb::closure_science::ProviderRun;

int g_failures = 0;

void check(bool condition, const std::string& what) {
    if (!condition) {
        ++g_failures;
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
    }
}

void require_or_fail(bool condition, const std::string& what) {
    if (!condition) {
        std::fprintf(stderr, "FATAL %s\n", what.c_str());
        std::exit(2);
    }
}

[[nodiscard]] const Json* field(const Json& object, const char* key) {
    if (!object.is_object()) return nullptr;
    const auto it = object.find(key);
    return it != object.end() ? &*it : nullptr;
}

[[nodiscard]] std::string str_of(const Json& object, const char* key) {
    const Json* v = field(object, key);
    return v != nullptr && v->is_string() ? v->get<std::string>() : "";
}

struct TestProject {
    fs::path dir;
    fs::path project_file;

    static TestProject make(const std::string& name) {
        TestProject project;
        project.dir = fs::temp_directory_path() /
                      ("closure_science_mock_" + name + "_" +
                       std::to_string(static_cast<long long>(test_pid())));
        fs::remove_all(project.dir);
        fs::create_directories(project.dir);
        project.project_file = project.dir / (name + ".paleo.json");
        auto document = pwb::project::ProjectDocument::create_new(name, "");
        pwb::project::ProjectManager manager(project.project_file);
        const auto saved = manager.save(document);
        require_or_fail(saved.is_ok(),
                        "project save: " +
                            (saved.is_ok() ? "" : saved.error().message));
        return project;
    }
};

[[nodiscard]] std::shared_ptr<CatalogServiceCore> open_core(
    const fs::path& project_file) {
    auto opened = pwb::catalog::open_catalog(project_file);
    require_or_fail(opened.is_ok(),
                    "open catalog: " + project_file.string());
    return std::make_shared<CatalogServiceCore>(std::move(opened.value()));
}

[[nodiscard]] Json run_provider(const ProviderRun& provider,
                                Json parameters) {
    const auto outcome =
        provider(Json::object(), std::move(parameters), [] { return false; });
    require_or_fail(outcome.is_ok(),
                    "provider run: " +
                        (outcome.is_ok() ? "" : outcome.error().message));
    return outcome.value();
}

}  // namespace

#ifdef _WIN32
int wmain() { return 0; }
#else
int main() {
    TestProject project = TestProject::make("mock_facies");
    auto core = open_core(project.project_file);
    auto save = [&core](const pwb::catalog::DirtySet& dirty) {
        return core->save(dirty);
    };

    // ---- ensure_mock_facies_models: idempotent, both versions land -------
    std::string well_version;
    std::string seismic_version;
    {
        const auto first = pwb::closure_science::ensure_mock_facies_models(
            core->document(), save);
        require_or_fail(first.is_ok(), "ensure_mock_facies_models #1");
        well_version = first.value().first;
        seismic_version = first.value().second;
        check(!well_version.empty() && !seismic_version.empty(),
              "mock model version ids returned");
        const auto second = pwb::closure_science::ensure_mock_facies_models(
            core->document(), save);
        require_or_fail(second.is_ok(), "ensure_mock_facies_models #2");
        // Register-or-keep: re-running never rewrites the existing rows.
        check(second.value().first == well_version
                  && second.value().second == seismic_version,
              "mock model seeding is idempotent");
        bool demo_flagged = false;
        for (const auto* version :
             pwb::catalog::list_model_versions(core->document(), nullptr)) {
            if (version->id == well_version || version->id == seismic_version) {
                demo_flagged |= version->demo_only
                                && version->status == "demo";
            }
        }
        check(demo_flagged, "mock models stay demo-flagged");
    }

    // ---- well provider: per-well regions + well_detail -------------------
    {
        Json wells = Json::array();
        for (int i = 0; i < 3; ++i) {
            Json row = Json::object();
            row["well_id"] = "W" + std::to_string(i + 1);
            row["well_name"] = "井-" + std::to_string(i + 1);
            row["td"] = 1000.0 + i * 50;
            wells.push_back(std::move(row));
        }
        Json parameters = Json::object();
        parameters["target_horizon"] = "T1";
        parameters["wells"] = wells;
        parameters["seed"] = 7;
        const Json result =
            run_provider(pwb::closure_science::make_mock_well_facies_provider(),
                         parameters);
        const Json* summary = field(result, "result_summary");
        require_or_fail(summary != nullptr && summary->is_object(),
                        "well payload has result_summary");
        const Json* regions = field(*summary, "predicted_regions");
        check(regions != nullptr && regions->is_array()
                  && regions->size() == 3,
              "one predicted region per well");
        const Json* detail = field(result, "well_detail");
        check(detail != nullptr && detail->is_array() && !detail->empty(),
              "well_detail carried for the INTERMEDIATE registration");
        const Json* flags = field(*summary, "is_mock");
        const Json* demo = field(result, "demo");
        check(flags != nullptr && flags->is_boolean() && flags->get<bool>()
                  && demo != nullptr && demo->is_boolean()
                  && demo->get<bool>(),
              "mock honesty flags on the payload");
    }

    // ---- well provider refuses without wells (InferenceInputError) -------
    {
        Json parameters = Json::object();
        parameters["target_horizon"] = "T1";
        parameters["wells"] = Json::array();
        const auto outcome =
            pwb::closure_science::make_mock_well_facies_provider()(
                Json::object(), parameters, [] { return false; });
        check(!outcome.is_ok()
                  && outcome.error().message.find("井") != std::string::npos,
              "empty wells -> explicit input error");
    }

    // ---- seismic provider: polygons + mock_grid --------------------------
    {
        Json extent = Json::array({0.0, 0.0, 10.0, 8.0});
        Json parameters = Json::object();
        parameters["target_horizon"] = "T1";
        parameters["extent"] = extent;
        parameters["grid_n"] = 24;
        parameters["crs"] = "EPSG:32650";
        parameters["seed"] = 11;
        const Json result = run_provider(
            pwb::closure_science::make_mock_seismic_facies_provider(),
            parameters);
        const Json* summary = field(result, "result_summary");
        require_or_fail(summary != nullptr && summary->is_object(),
                        "seismic payload has result_summary");
        const Json* spatial = field(*summary, "spatial");
        require_or_fail(spatial != nullptr && spatial->is_object()
                            && str_of(*spatial, "type") == "VECTOR_POLYGONS",
                        "seismic payload has VECTOR_POLYGONS spatial envelope");
        const Json* features = field(*spatial, "features");
        check(features != nullptr && features->is_array()
                  && !features->empty(),
              "VECTOR_POLYGONS spatial features emitted");
        bool polygon_geometry = false;
        if (features != nullptr && features->is_array()) {
            for (const Json& feature : *features) {
                const Json* geometry = field(feature, "geometry");
                if (geometry != nullptr && geometry->is_object()
                    && (*geometry)["type"] == "Polygon") {
                    polygon_geometry = true;
                }
            }
        }
        check(polygon_geometry, "spatial features are polygons");
        const Json* grid = field(result, "mock_grid");
        check(grid != nullptr && grid->is_object()
                  && grid->contains("grid_z") && grid->contains("grid_x")
                  && grid->contains("grid_y"),
              "mock_grid carried for the INTERMEDIATE registration");
    }

    // ---- seismic provider refuses without an extent -----------------------
    {
        Json parameters = Json::object();
        parameters["target_horizon"] = "T1";
        parameters["extent"] = Json();
        const auto outcome =
            pwb::closure_science::make_mock_seismic_facies_provider()(
                Json::object(), parameters, [] { return false; });
        check(!outcome.is_ok(), "missing extent -> explicit input error");
    }

    fs::remove_all(project.dir);
    if (g_failures != 0) {
        std::fprintf(stderr, "%d failure(s)\n", g_failures);
        return 1;
    }
    std::fprintf(stderr, "closure_science.mock_facies: all checks passed\n");
    return 0;
}
#endif
