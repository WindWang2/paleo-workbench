// providers.builtins — the real providers end-to-end: factor statistics over
// a mapping_kernel dataset (normal / empty / bad-input / work-dir / catalog
// paths), map thumbnail rendering (real PNG bytes, containment, overwrite
// refusal, escape refusal, verification), and typed input adapters.

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/extract.hpp>
#include <pwb/mapping_document/map_document.hpp>
#include <pwb/providers/builtin.hpp>
#include <pwb/providers/builtin_adapters.hpp>
#include <pwb/providers/errors.hpp>
#include <pwb/providers/execution.hpp>
#include <pwb/providers/registry.hpp>

using pwb::domain::Json;
namespace pp = pwb::providers;
namespace fs = std::filesystem;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

template <typename E, typename Fn>
bool expect(Fn&& fn, std::string* message = nullptr) {
    try {
        fn();
    } catch (const E& exc) {
        if (message != nullptr) *message = exc.what();
        return true;
    } catch (...) {
        return false;
    }
    return false;
}

// Recording catalog port (registration assertions only).
class RecordingCatalog : public pp::ICatalogPort {
public:
    std::string last_kind;
    std::string last_name;
    std::optional<Json> version;
    int begin_calls = 0;

    std::optional<RunRef> begin_run(const RunSpec&) override {
        ++begin_calls;
        return RunRef{"run-1"};
    }
    void complete_run(const std::string&, const std::string&) override {}
    std::optional<Json> register_intermediate(const std::string&, const std::string& name,
                                              const std::string&, const std::string& kind,
                                              const std::string&) override {
        last_name = name;
        last_kind = kind;
        Json v = Json::object();
        v["version_id"] = "v-1";
        version = v;
        return version;
    }
};

pwb::mapping::FactorDataset sample_dataset() {
    pwb::mapping::FactorDataset dataset;
    dataset.factor_name = "sand_ratio";
    dataset.unit = "fraction";
    dataset.target_horizon = "H3";
    pwb::mapping::FactorPoint ok_point;
    ok_point.value = 0.4;
    ok_point.qc_flag = "ok";
    pwb::mapping::FactorPoint good_point;
    good_point.value = 0.6;
    good_point.qc_flag = "good";
    pwb::mapping::FactorPoint flagged_point;
    flagged_point.value = 99.0;  // excluded: qc flag not ok/good/""
    flagged_point.qc_flag = "flagged";
    pwb::mapping::FactorPoint nan_point;
    nan_point.value = std::nan("");  // excluded: non-finite
    nan_point.qc_flag = "ok";
    dataset.points = {ok_point, good_point, flagged_point, nan_point};
    return dataset;
}

class TempDir {
public:
    TempDir() {
        // Aborted runs skip destructors and leak directories; probe for a
        // free name instead of colliding with the leftover (the no-overwrite
        // contract would then refuse our own writes).
        const auto base = fs::temp_directory_path();
        for (int attempt = 0;; ++attempt) {
            const fs::path candidate =
                base / ("pwb-providers-builtin-" + std::to_string(instance_counter()++) +
                        "-" + std::to_string(attempt));
            std::error_code exists_ec;
            if (!fs::exists(candidate, exists_ec)) {
                path_ = candidate;
                break;
            }
        }
        std::error_code create_ec;
        fs::create_directories(path_, create_ec);
    }
    ~TempDir() {
        std::error_code ec;
        fs::remove_all(path_, ec);
    }
    const fs::path& path() const { return path_; }

private:
    static int& instance_counter() {
        static int counter = 0;
        return counter;
    }
    fs::path path_;
};

int main() {
    // --- factor stats over a real kernel dataset ----------------------------
    {
        TempDir temp;
        pp::FactorStatsProvider provider;
        pp::ProviderInputs inputs;
        inputs.set("dataset", pp::make_dataset_typed_input("dataset", sample_dataset()));
        pp::ProviderContext context;
        context.work_dir = temp.path().generic_string();
        Json empty_params = Json::object();

        pp::ProviderResult result =
            pp::execute_provider(provider, inputs, empty_params, &context, nullptr);
        check(result.metrics.at("count") == 2, "valid points only counted");
        check(result.metrics.at("finite") == 2, "finite equals count for valid points");
        check(std::abs(result.metrics.at("min").get<double>() - 0.4) < 1e-12, "min");
        check(std::abs(result.metrics.at("max").get<double>() - 0.6) < 1e-12, "max");
        check(std::abs(result.metrics.at("mean").get<double>() - 0.5) < 1e-12, "mean");
        // Sample stdev over {0.4, 0.6}: sqrt(((0.1)^2+(0.1)^2)/1) = sqrt(0.02).
        check(std::abs(result.metrics.at("stdev").get<double>() - std::sqrt(0.02)) < 1e-12,
              "stdev");
        check(result.artifacts.size() == 1 && result.artifacts.front().kind == "file",
              "one file artifact");
        const std::string report_path = *result.artifacts.front().path;
        std::ifstream in(report_path);
        std::string body((std::istreambuf_iterator<char>(in)),
                         std::istreambuf_iterator<char>());
        check(body.find("\"factor_name\": \"sand_ratio\"") != std::string::npos,
              "report carries factor name");
        check(body.find("\"count\": 2") != std::string::npos, "report carries count");
        check(result.warnings.empty(), "verify passes on healthy stats");

        // Catalog-bound run registers the report as an intermediate.
        RecordingCatalog catalog;
        pp::ProviderContext catalog_context;
        catalog_context.work_dir = temp.path().generic_string();
        catalog_context.catalog = &catalog;
        Json run_params = Json::object();
        auto bound = pp::execute_provider(provider, inputs, run_params, &catalog_context,
                                          nullptr);
        check(catalog.begin_calls == 1, "executor opened a run");
        check(catalog.last_kind == "factor_stats_report" &&
                  catalog.last_name == "factor-stats",
              "report registered as intermediate");
        check(bound.artifacts.front().version.is_object(), "artifact version recorded");
    }
    {
        // Empty dataset: execute succeeds, verify fails closed.
        TempDir temp;
        pp::FactorStatsProvider provider;
        pwb::mapping::FactorDataset empty_dataset = sample_dataset();
        empty_dataset.points.clear();
        pp::ProviderInputs inputs;
        inputs.set("dataset",
                   pp::make_dataset_typed_input("dataset", empty_dataset));
        pp::ProviderContext context;
        context.work_dir = temp.path().generic_string();
        std::string message;
        check(expect<pp::ProviderVerificationError>(
                  [&] {
                      Json empty_params = Json::object();
                      pp::execute_provider(provider, inputs, empty_params, &context, nullptr);
                  },
                  &message),
              "empty statistics fail verification");
        check(message ==
                  "provider 'geology.factor_stats' verification failed: no valid "
                  "points — empty statistics",
              "empty verify message parity: " + message);
    }
    {
        // Declared-type input with a non-dataset payload: the provider's own
        // rejection (the executor's type-name gate is covered in
        // providers.execution).
        pp::FactorStatsProvider provider;
        pp::ProviderInputs inputs;
        pp::TypedInput ref_only;
        ref_only.type_name = "FactorDatasetRef";
        Json payload = Json::object();
        payload["factor_name"] = "sand_ratio";
        ref_only.payload = payload;
        inputs.set("dataset", ref_only);
        std::string message;
        check(expect<pp::ProviderRejectedInputError>(
                  [&] {
                      Json empty_params = Json::object();
                      pp::execute_provider(provider, inputs, empty_params, nullptr, nullptr);
                  },
                  &message),
              "bad input rejected");
        check(message.find("input 'dataset' must be a GeologicalFactorDataset") !=
                  std::string::npos,
              "rejected message parity");
    }
    {
        // No work_dir → refusal (never write to cwd).
        pp::FactorStatsProvider provider;
        pp::ProviderInputs inputs;
        inputs.set("dataset", pp::make_dataset_typed_input("dataset", sample_dataset()));
        pp::ProviderContext context;  // work_dir empty
        std::string message;
        check(expect<pp::ProviderRejectedInputError>(
                  [&] {
                      Json empty_params = Json::object();
                      pp::execute_provider(provider, inputs, empty_params, &context, nullptr);
                  },
                  &message),
              "missing work_dir refused");
        check(message.find("context.work_dir is required") != std::string::npos,
              "work_dir message parity");
    }
    {
        // Custom report_name parameter + schema enforced.
        TempDir temp;
        pp::FactorStatsProvider provider;
        pp::ProviderInputs inputs;
        inputs.set("dataset", pp::make_dataset_typed_input("dataset", sample_dataset()));
        pp::ProviderContext context;
        context.work_dir = temp.path().generic_string();
        Json params = Json::object();
        params["report_name"] = "sand-stats";
        auto result = pp::execute_provider(provider, inputs, params, &context, nullptr);
        check(result.artifacts.front().name == "sand-stats.json",
              "report_name honored");
        // additionalProperties=false at the SDK level.
        Json bad_params = Json::object();
        bad_params["surprise"] = 1;
        std::string message;
        check(expect<pp::InvalidParametersError>(
                  [&] { pp::execute_provider(provider, inputs, bad_params, &context, nullptr); },
                  &message),
              "undeclared parameter rejected");
        (void)message;
    }

    // --- map thumbnail: real render into a contained PNG ---------------------
    {
        TempDir temp;
        pp::MapThumbnailProvider provider;

        // Build a real MapDocument with a polygon + a point feature.
        Json polygon_feature = Json::object();
        Json polygon_geometry = Json::object();
        polygon_geometry["type"] = "Polygon";
        Json polygon_coords = Json::array();
        Json ring = Json::array();
        const double ring_xy[][2] = {{0.0, 0.0}, {1.0, 0.0}, {1.0, 1.0}, {0.0, 1.0},
                                     {0.0, 0.0}};
        for (const auto& xy : ring_xy) {
            ring.push_back(Json::array({xy[0], xy[1]}));
        }
        polygon_coords.push_back(ring);
        polygon_geometry["coordinates"] = polygon_coords;
        polygon_feature["geometry"] = polygon_geometry;

        Json point_feature = Json::object();
        Json point_geometry = Json::object();
        point_geometry["type"] = "Point";
        point_geometry["coordinates"] = Json::array({0.5, 0.5});
        point_feature["geometry"] = point_geometry;

        Json layer_payload = Json::object();
        layer_payload["id"] = "facies";
        Json style = Json::object();
        style["fill"] = "#22b8a7";
        style["stroke"] = "#26364d";
        layer_payload["style"] = style;
        layer_payload["features"] = Json::array({polygon_feature, point_feature});
        Json doc_payload = Json::object();
        doc_payload["id"] = "doc-1";
        doc_payload["layers"] = Json::array({layer_payload});
        const auto document = pwb::mapping_document::parse_map_document(doc_payload);

        pp::TypedInput document_input;
        document_input.type_name = "MapDocument";
        document_input.payload = pwb::mapping_document::dump_map_document(document);

        pp::ProviderInputs inputs;
        inputs.set("document", document_input);
        pp::ProviderContext context;
        context.work_dir = temp.path().generic_string();
        Json params = Json::object();
        params["output_path"] = "thumbs/map.png";
        params["width"] = 128;
        params["height"] = 96;
        pp::ProviderResult result =
            pp::execute_provider(provider, inputs, params, &context, nullptr);
        check(result.artifacts.size() == 1, "thumbnail artifact produced");
        const std::string artifact_path = *result.artifacts.front().path;
        check(fs::exists(artifact_path), "PNG written");
        // Contained inside the work dir.
        check(artifact_path.find(temp.path().generic_string()) == 0, "output contained");
        // Real PNG: magic + IHDR dims.
        std::ifstream in(artifact_path, std::ios::binary);
        std::vector<char> bytes((std::istreambuf_iterator<char>(in)),
                                std::istreambuf_iterator<char>());
        const unsigned char magic[8] = {0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};
        check(bytes.size() > 16 &&
                  std::equal(magic, magic + 8, reinterpret_cast<const unsigned char*>(bytes.data())),
              "PNG signature");
        // IHDR width/height big-endian at offsets 16/20.
        const auto be32 = [&](std::size_t offset) {
            return (static_cast<unsigned char>(bytes[offset]) << 24) |
                   (static_cast<unsigned char>(bytes[offset + 1]) << 16) |
                   (static_cast<unsigned char>(bytes[offset + 2]) << 8) |
                   static_cast<unsigned char>(bytes[offset + 3]);
        };
        check(be32(16) == 128 && be32(20) == 96, "IHDR dimensions 128x96");
        // The render actually painted: the stored-deflate IDAT carries the
        // raw RGB scanlines verbatim, so the teal fill (#22b8a7) must appear.
        bool painted = false;
        for (std::size_t i = 44; i + 2 < bytes.size(); ++i) {
            if (static_cast<unsigned char>(bytes[i]) == 0x22 &&
                static_cast<unsigned char>(bytes[i + 1]) == 0xB8 &&
                static_cast<unsigned char>(bytes[i + 2]) == 0xA7) {
                painted = true;
                break;
            }
        }
        check(painted, "polygon fill painted teal");
        check(result.diagnostics.at("bytes") == bytes.size(),
              "diagnostics bytes match the file");

        // Deterministic bytes: same inputs → identical file content.
        TempDir temp2;
        pp::ProviderContext context2;
        context2.work_dir = temp2.path().generic_string();
        auto result2 = pp::execute_provider(provider, inputs, params, &context2, nullptr);
        std::ifstream in2(*result2.artifacts.front().path, std::ios::binary);
        std::vector<char> bytes2((std::istreambuf_iterator<char>(in2)),
                                 std::istreambuf_iterator<char>());
        check(bytes == bytes2, "render is byte-deterministic");

        // Cancel before execute: the context token aborts the run (#1137
        // surfaces through check_cancelled inside providers that poll it; the
        // thumbnail provider is short-running so the executor-level contract
        // is that a pre-cancelled token refuses to start).
        pp::CancelToken token;
        token.cancel();
        pp::ProviderContext cancelled_context;
        cancelled_context.work_dir = temp.path().generic_string();
        cancelled_context.cancel = &token;
        // The thumbnail provider does not poll the token mid-render; the SDK
        // contract (check_cancelled) is exercised in providers.execution.
    }
    {
        // Output path escaping the workspace is refused (#1177).
        TempDir temp;
        pp::MapThumbnailProvider provider;
        pp::TypedInput document_input;
        document_input.type_name = "MapDocument";
        document_input.payload = Json::object();
        document_input.payload["id"] = "doc-1";
        document_input.payload["layers"] = Json::array();
        pp::ProviderInputs inputs;
        inputs.set("document", document_input);
        pp::ProviderContext context;
        context.work_dir = temp.path().generic_string();
        Json params = Json::object();
        params["output_path"] = "../outside.png";
        std::string message;
        check(expect<pp::ProviderExecutionError>(
                  [&] { pp::execute_provider(provider, inputs, params, &context, nullptr); },
                  &message),
              "workspace escape refused");
        check(message.find("resolves outside the execution workspace") != std::string::npos,
              "escape message parity: " + message);
    }
    {
        // Overwriting an existing file is refused.
        TempDir temp;
        const auto existing = temp.path() / "exists.png";
        { std::ofstream creator(existing, std::ios::binary); creator << "x"; }
        pp::MapThumbnailProvider provider;
        pp::TypedInput document_input;
        document_input.type_name = "MapDocument";
        document_input.payload = Json::object();
        document_input.payload["id"] = "doc-1";
        document_input.payload["layers"] = Json::array();
        pp::ProviderInputs inputs;
        inputs.set("document", document_input);
        pp::ProviderContext context;
        context.work_dir = temp.path().generic_string();
        Json params = Json::object();
        params["output_path"] = "exists.png";
        std::string message;
        check(expect<pp::ProviderExecutionError>(
                  [&] { pp::execute_provider(provider, inputs, params, &context, nullptr); },
                  &message),
              "overwrite refused");
        check(message.find("refusing to overwrite existing file") != std::string::npos,
              "overwrite message parity");
    }
    {
        // Missing document is rejected with the Python type-name message.
        pp::MapThumbnailProvider provider;
        pp::ProviderInputs inputs;  // no document at all
        pp::ProviderContext context;
        Json params = Json::object();
        params["output_path"] = "thumb.png";
        std::string message;
        check(expect<pp::ProviderRejectedInputError>(
                  [&] { pp::execute_provider(provider, inputs, params, &context, nullptr); },
                  &message),
              "missing document rejected");
        check(message.find("must be a MapDocument or MapDocumentRef, got NoneType") !=
                  std::string::npos,
              "NoneType message parity: " + message);
    }

    // --- registry exposure: capability query over real descriptors ----------
    {
        pp::ProviderRegistry registry;
        pp::register_builtin_providers(registry);
        const auto exporters = registry.by_family(pp::ProviderFamily::Exporter);
        check(exporters.size() == 1 &&
                  exporters.front()->descriptor().provider_id == "export.map_thumbnail",
              "exporter family query");
        const auto descriptors = registry.descriptors();
        check(descriptors.size() == 2, "capability listing over builtins");
        check(descriptors.front().provider_id == "export.map_thumbnail",
              "sorted listing (exporter < interpolation)");
        check(descriptors.front().capabilities ==
                  std::vector<std::string>({"export", "thumbnail"}),
              "thumbnail capabilities");
        check(registry.find("geology.factor_stats")->descriptor().input_types ==
                  std::vector<std::string>({"GeologicalFactorDataset", "FactorDatasetRef"}),
              "factor stats input contract");
    }

    if (g_failures != 0) {
        std::fprintf(stderr, "providers.builtins: %d checks, %d failures\n", g_checks,
                     g_failures);
        return 1;
    }
    std::printf("providers.builtins: %d checks passed\n", g_checks);
    return 0;
}
