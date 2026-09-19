#include <pwb/closure_science/model_seed.hpp>

#include <pwb/catalog/model_registry.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/prediction/model_package_runtime.hpp>

namespace pwb::closure_science {

using catalog::SaveHook;

namespace {

// providers.py _ensure_model_version parity: idempotent re-registration is
// a lookup, not a duplicate — register only when the version is absent.
domain::DataError ensure_model_version(catalog::CatalogDocument& document,
                                       const SaveHook& save,
                                       catalog::RegisterModelVersionRequest request) {
    auto existing = catalog::get_model_version(document, request.model_id,
                                               request.model_version);
    if (existing.is_ok()) return domain::DataError(domain::ErrorCode::Ok, "");
    auto created = catalog::register_model_version(document, save, request);
    if (!created.is_ok()) return created.error();
    return domain::DataError(domain::ErrorCode::Ok, "");
}

catalog::RegisterModelRequest base_model_request(
    const std::string& model_id, const std::string& model_name,
    const std::string& model_type, const std::string& provider,
    domain::Json metadata) {
    catalog::RegisterModelRequest request;
    request.model_id = model_id;
    request.model_name = model_name;
    request.model_type = model_type;
    request.capability = std::string(kCapabilityFacies);
    request.provider = provider;
    request.status = "demo";
    request.metadata = std::move(metadata);
    return request;
}

}  // namespace

domain::DataError ensure_default_models(catalog::CatalogDocument& document,
                                        const SaveHook& save) {
    // Demo model (providers.py MODEL_ID_DEMO parity). Deterministic
    // synthetic — demo_only, never a scientific prediction.
    auto demo_model = catalog::register_model(
        document, save,
        base_model_request(std::string(kModelIdDemo), "演示相带预测（Demo）",
                           "demo", std::string(kProviderDemo),
                           domain::Json{{"source", "synthetic/demo"},
                                        {"demo_only", true}}));
    if (!demo_model.is_ok()) return demo_model.error();
    catalog::RegisterModelVersionRequest demo_version;
    demo_version.model_id = std::string(kModelIdDemo);
    demo_version.model_version = "1";
    demo_version.deterministic = true;
    demo_version.demo_only = true;
    demo_version.status = "demo";
    demo_version.metadata = domain::Json{{"source", "synthetic/demo"}};
    auto demo = ensure_model_version(document, save, demo_version);
    if (demo.code != domain::ErrorCode::Ok) return demo;

    // Heuristic model (providers.py MODEL_ID_HEURISTIC parity): a real
    // GR-median/window computation, honestly uncalibrated and never a
    // trained model.
    auto heuristic_model = catalog::register_model(
        document, save,
        base_model_request(std::string(kModelIdHeuristic),
                           "GR 中值启发式相带估计（非科学预测）", "heuristic",
                           std::string(kProviderLocalAsset),
                           domain::Json{{"scientific", false},
                                        {"probabilities_uncalibrated", true},
                                        {"note",
                                         "GR median/window rule — real "
                                         "computation, not a trained "
                                         "model"}}));
    if (!heuristic_model.is_ok()) return heuristic_model.error();
    catalog::RegisterModelVersionRequest heuristic_version;
    heuristic_version.model_id = std::string(kModelIdHeuristic);
    heuristic_version.model_version = "1";
    heuristic_version.deterministic = true;
    heuristic_version.demo_only = false;
    heuristic_version.status = "demo";
    heuristic_version.metadata =
        domain::Json{{"scientific", false}, {"probabilities_uncalibrated", true}};
    auto heuristic =
        ensure_model_version(document, save, heuristic_version);
    if (heuristic.code != domain::ErrorCode::Ok) return heuristic;

    return domain::DataError(domain::ErrorCode::Ok, "");
}

domain::Result<catalog::ModelVersion> register_package_model(
    catalog::CatalogDocument& document, const SaveHook& save,
    const PackageModelRequest& request) {
    if (request.manifest_path.empty()) {
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "model package manifest path is required");
    }
    // Full package load: manifest parse + artifact checksum + path
    // containment + scientific gate. Non-scientific packages are refused
    // exactly like production inference would refuse them. The loader
    // reports contract violations by throwing ModelPackageError /
    // UnicodeDecodeError (model_package_runtime.hpp contract) — translate
    // into the Result channel the catalog registry uses.
    pwb::prediction::ModelPackageLoadOptions options;
    options.allow_non_scientific = false;
    pwb::prediction::LoadedModelPackage package;
    try {
        package = pwb::prediction::load_model_package(request.manifest_path,
                                                      options);
    } catch (const std::exception& exc) {
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 std::string("model package invalid: ")
                                     + exc.what());
    }
    if (package.manifest.model_id.empty()) {
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "model package manifest has no model_id");
    }

    domain::Json metadata = package.manifest.metadata;
    metadata["source"] = "model_package";
    metadata["package_root"] = package.package_root;
    metadata["scientific"] = package.manifest.scientific;
    metadata["demo_only"] = package.manifest.demo_only;
    metadata["spatial_output_type"] = package.manifest.spatial_output_type;

    catalog::RegisterModelRequest model_request;
    model_request.model_id = package.manifest.model_id;
    model_request.model_name = package.manifest.model_name;
    model_request.model_type = package.manifest.model_type;
    model_request.capability = package.manifest.capability;
    model_request.provider = package.manifest.provider;
    model_request.status = request.status;
    model_request.metadata = metadata;
    model_request.provenance = package.manifest.provenance;
    auto model = catalog::register_model(document, save, model_request);
    if (!model.is_ok()) return model.error();

    catalog::RegisterModelVersionRequest version_request;
    version_request.model_id = package.manifest.model_id;
    version_request.model_version = package.manifest.model_version;
    version_request.artifact_uri = package.manifest_path;
    version_request.checksum = package.manifest.checksum;
    version_request.input_schema = package.manifest.input_schema;
    version_request.output_schema = package.manifest.output_schema;
    version_request.preprocessing_version =
        package.manifest.preprocessing_version;
    version_request.runtime = package.manifest.runtime;
    version_request.deterministic = package.manifest.deterministic;
    version_request.demo_only = package.manifest.demo_only;
    version_request.status = request.status;
    version_request.metadata = std::move(metadata);
    version_request.provenance = package.manifest.provenance;
    auto version =
        catalog::register_model_version(document, save, version_request);
    if (!version.is_ok()) return version.error();
    return *version.value();
}

}  // namespace pwb::closure_science
