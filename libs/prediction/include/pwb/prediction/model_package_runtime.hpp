// Model package runtime — the executable half of
// paleo_workbench/prediction/model_package.py.
//
// CONV-21 froze the pure manifest/validation contract; this is the runtime a
// prediction task actually drives: resolve the manifest on disk, enforce
// package-root path safety, verify/backfill the artifact checksum, read the
// declared prediction metadata (classes, class definitions, expected bands,
// normalization, CRS/scale requirements, tile defaults) and check it against
// the real ONNX model ports.

#pragma once

#include <optional>
#include <string>
#include <vector>

#include "pwb/domain/json.hpp"
#include "pwb/prediction/model_package.hpp"
#include "pwb/prediction/onnx_session.hpp"

namespace pwb::prediction {

using pwb::domain::Json;

struct ModelPackageLoadOptions {
    bool require_artifact = true;
    // Mirrors validate_model_package(allow_non_scientific): demo/heuristic
    // packages load for tests/harness work but are refused by default.
    bool allow_non_scientific = false;
    // Fail closed when the artifact resolves outside the manifest's
    // directory (default). The Python loader only resolves, it does not
    // contain; the native runtime refuses the escape vector.
    bool enforce_within_root = true;
};

// Per-band (or scalar) normalization declared by the package. Applied by the
// pipeline before the session sees a voxel. Python's tiled provider ignores
// this metadata (it feeds raw float32); the native runtime only applies it
// when a package declares it, so undeclared packages stay byte-compatible.
struct BandNormalization {
    bool present = false;
    std::vector<double> mean;  // size 1 (scalar) or band/channel count
    std::vector<double> standard_deviation;

    bool is_scalar() const {
        return mean.size() == 1 && standard_deviation.size() == 1;
    }
};

// The native prediction contract read from the manifest. Sources, in order:
// metadata.prediction_runtime (native block), then flat metadata keys
// (classes/num_classes/class_names/input_bands/bands/normalization), then
// output_schema.class_names. 0 / empty / nullopt means "not declared".
struct PredictionModelMetadata {
    int classes = 0;
    std::vector<std::string> class_names;
    std::vector<std::string> input_bands;
    BandNormalization normalization;
    std::optional<std::string> expected_crs;
    std::optional<double> pixel_size;
    std::vector<long long> expected_input_shape;  // -1 = dynamic
    std::vector<int> tile;                        // empty = not declared
    int overlap = -1;                             // -1 = not declared
    int batch = -1;                               // -1 = not declared
    std::optional<double> nodata;
    Json raw;                                     // native block as authored
};

struct LoadedModelPackage {
    ModelPackageManifest manifest;
    std::string manifest_path;   // as given
    std::string package_root;    // canonical manifest directory
    std::string artifact_path;   // canonical, contained when enforced
    std::string artifact_sha256;
    long long artifact_bytes = 0;
    PredictionModelMetadata prediction;
    Json diagnostics = Json::array();  // [{code, severity, message, detail?}]

    Json to_json() const;
};

// Throws ModelPackageError (bad manifest / checksum / path escape) and
// UnicodeDecodeError (non-UTF-8 manifest, leaking like Python).
LoadedModelPackage load_model_package(
    const std::string& manifest_path,
    const ModelPackageLoadOptions& options = ModelPackageLoadOptions{});

struct CompatibilityReport {
    Json errors = Json::array();
    Json warnings = Json::array();
    bool ok() const { return errors.empty(); }
};

// Checks the declared prediction metadata against the real model ports:
// input rank/channel count vs declared bands, static output channel count vs
// declared classes, declared input shape vs the model's static dims, and
// normalization array lengths. Errors are one-line, user-facing strings.
CompatibilityReport check_model_package_compatibility(
    const LoadedModelPackage& package, const OnnxRuntimeSession& session);

}  // namespace pwb::prediction
