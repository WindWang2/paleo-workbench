// Model package runtime — see include/pwb/prediction/model_package_runtime.hpp.
//
// Reuses the frozen CONV-21 contract (/parse_model_package_manifest/,
// /validate_model_package/) and the interchange path-safety kernel. No
// manifest field is re-parsed with different semantics; this TU only adds
// the runtime half Python keeps in its service layer plus the native
// metadata block the tiled runtime consumes.

#include <pwb/prediction/model_package_runtime.hpp>

#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <limits>
#include <set>
#include <string>
#include <utility>

#include <pwb/domain/sha256.hpp>
#include <pwb/interchange/path_safety.hpp>

#include "runtime_io.hpp"

namespace pwb::prediction {
namespace {

namespace fs = std::filesystem;

const Json kNull;

const Json& get(const Json& obj, const char* key) {
    if (!obj.is_object()) return kNull;
    const auto it = obj.find(key);
    return it == obj.end() ? kNull : *it;
}

std::string ascii_lower(std::string text) {
    for (char& ch : text) {
        if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch + 32);
    }
    return text;
}

// float(value) semantics for metadata numbers: JSON numbers and numeric
// strings; null / arrays / objects / booleans are rejected.
bool as_finite_double(const Json& value, double* out) {
    if (value.is_number()) {
        const double number = value.get<double>();
        if (!std::isfinite(number)) return false;
        *out = number;
        return true;
    }
    if (value.is_string()) {
        const std::string text = value.get<std::string>();
        char* end = nullptr;
        const double number = std::strtod(text.c_str(), &end);
        if (end == text.c_str() || end == nullptr || *end != '\0') return false;
        if (!std::isfinite(number)) return false;
        *out = number;
        return true;
    }
    return false;
}

// int(value) semantics for metadata integers: integral numbers and numeric
// strings, Python's int() accepted set (no booleans, no fractions).
bool as_int(const Json& value, long long* out) {
    // nlohmann treats unsigned integers as is_number_integer() too, and
    // get<long long>() would wrap; handle them before the signed branch.
    if (value.is_number_unsigned()) {
        const unsigned long long number = value.get<unsigned long long>();
        if (number > static_cast<unsigned long long>(
                         std::numeric_limits<long long>::max())) {
            return false;
        }
        *out = static_cast<long long>(number);
        return true;
    }
    if (value.is_number_integer()) {
        *out = value.get<long long>();
        return true;
    }
    if (value.is_number_float()) {
        const double number = value.get<double>();
        if (!std::isfinite(number) || std::floor(number) != number) return false;
        if (number < -9.0e18 || number > 9.0e18) return false;
        *out = static_cast<long long>(number);
        return true;
    }
    if (value.is_string()) {
        const std::string text = value.get<std::string>();
        char* end = nullptr;
        const long long number = std::strtoll(text.c_str(), &end, 10);
        if (end == text.c_str() || end == nullptr || *end != '\0') return false;
        *out = number;
        return true;
    }
    return false;
}

[[noreturn]] void field_error(const std::string& path,
                              const std::string& expectation) {
    throw ModelPackageError("model package metadata." + path + " must be "
                            + expectation);
}

int positive_int_field(const Json& value, const std::string& path) {
    long long number = 0;
    if (!as_int(value, &number) || number <= 0 ||
        number > std::numeric_limits<int>::max()) {
        field_error(path, "a positive integer");
    }
    return static_cast<int>(number);
}

std::vector<std::string> string_list_field(const Json& value,
                                           const std::string& path) {
    if (!value.is_array()) {
        field_error(path, "an array of strings");
    }
    std::vector<std::string> result;
    result.reserve(value.size());
    for (const Json& item : value) {
        if (!item.is_string()) {
            field_error(path, "an array of strings");
        }
        result.push_back(item.get<std::string>());
    }
    return result;
}

void parse_normalization(const Json& value, const std::string& path,
                         BandNormalization* out) {
    if (!value.is_object()) {
        field_error(path, "an object with mean/std");
    }
    const Json& mean_value = get(value, "mean");
    const Json& std_value = value.contains("std") ? value["std"]
                                                  : get(value, "standard_deviation");
    if (mean_value.is_null() || std_value.is_null()) {
        field_error(path, "an object with mean/std");
    }
    const auto read_list = [&](const Json& v, std::vector<double>* target) {
        if (v.is_number() || v.is_string()) {
            double number = 0.0;
            if (!as_finite_double(v, &number)) {
                field_error(path, "finite numbers");
            }
            target->push_back(number);
            return;
        }
        if (!v.is_array() || v.empty()) {
            field_error(path, "finite numbers or a non-empty array of them");
        }
        target->reserve(v.size());
        for (const Json& item : v) {
            double number = 0.0;
            if (!as_finite_double(item, &number)) {
                field_error(path, "finite numbers");
            }
            target->push_back(number);
        }
    };
    read_list(mean_value, &out->mean);
    read_list(std_value, &out->standard_deviation);
    if (out->mean.size() != out->standard_deviation.size()) {
        field_error(path,
                    "mean and std arrays of the same length (1 or one per "
                    "band)");
    }
    for (const double deviation : out->standard_deviation) {
        if (deviation == 0.0) {
            field_error(path, "a non-zero std (division by zero)");
        }
    }
    out->present = true;
}

const Json& metadata_number_source(const Json& block, const Json& metadata,
                                   const char* key) {
    const Json& in_block = get(block, key);
    if (!in_block.is_null()) return in_block;
    return get(metadata, key);
}

std::optional<std::string> optional_string_field(const Json& value,
                                                 const std::string& path) {
    if (value.is_null()) return std::nullopt;
    if (!value.is_string()) {
        field_error(path, "a string");
    }
    const std::string text = value.get<std::string>();
    if (text.empty()) return std::nullopt;
    return text;
}

PredictionModelMetadata parse_prediction_metadata(const Json& metadata,
                                                  const Json& output_schema) {
    PredictionModelMetadata out;
    Json block = Json::object();
    const Json& native = get(metadata, "prediction_runtime");
    if (!native.is_null()) {
        if (!native.is_object()) {
            field_error("prediction_runtime", "an object");
        }
        block = native;
        out.raw = native;
    }

    const Json& classes_value = metadata_number_source(block, metadata, "classes");
    const Json& classes_value_fallback =
        classes_value.is_null()
            ? metadata_number_source(block, metadata, "num_classes")
            : classes_value;
    if (!classes_value_fallback.is_null()) {
        out.classes =
            positive_int_field(classes_value_fallback, "classes");
    }

    const Json& names_in_block = get(block, "class_names");
    const Json& names_in_metadata = get(metadata, "class_names");
    const Json& names_in_output = get(output_schema, "class_names");
    const Json& names_value = !names_in_block.is_null()
                                  ? names_in_block
                                  : (!names_in_metadata.is_null()
                                         ? names_in_metadata
                                         : names_in_output);
    if (!names_value.is_null()) {
        out.class_names = string_list_field(names_value, "class_names");
    }
    if (out.classes > 0 && !out.class_names.empty()
        && static_cast<int>(out.class_names.size()) != out.classes) {
        throw ModelPackageError(
            "model package metadata.class_names has "
            + std::to_string(out.class_names.size())
            + " entries but classes=" + std::to_string(out.classes)
            + "; class definitions must match the class count");
    }

    const Json& bands_in_block = get(block, "input_bands");
    const Json& bands_in_metadata = get(metadata, "input_bands");
    const Json& bands_value = !bands_in_block.is_null()
                                  ? bands_in_block
                                  : (!bands_in_metadata.is_null()
                                         ? bands_in_metadata
                                         : get(metadata, "bands"));
    if (!bands_value.is_null()) {
        out.input_bands = string_list_field(bands_value, "input_bands");
    }

    const Json& normalization_in_block = get(block, "normalization");
    const Json& normalization_in_metadata = get(metadata, "normalization");
    const Json& normalization_value = !normalization_in_block.is_null()
                                          ? normalization_in_block
                                          : normalization_in_metadata;
    if (!normalization_value.is_null()) {
        parse_normalization(normalization_value,
                            "normalization", &out.normalization);
    }
    if (out.normalization.present && out.normalization.mean.size() > 1
        && !out.input_bands.empty()
        && out.normalization.mean.size() != out.input_bands.size()) {
        throw ModelPackageError(
            "model package metadata.normalization has "
            + std::to_string(out.normalization.mean.size())
            + " per-band entries but input_bands declares "
            + std::to_string(out.input_bands.size()) + " bands");
    }

    const Json& crs_in_block = get(block, "expected_crs");
    const Json& crs_value = !crs_in_block.is_null() ? crs_in_block
                                                    : get(block, "crs");
    out.expected_crs = optional_string_field(crs_value, "expected_crs");

    const Json& pixel_size_value = metadata_number_source(block, metadata,
                                                          "pixel_size");
    if (!pixel_size_value.is_null()) {
        double number = 0.0;
        if (!as_finite_double(pixel_size_value, &number) || number <= 0.0) {
            field_error("pixel_size", "a finite positive number");
        }
        out.pixel_size = number;
    }

    const Json& input_shape_value = get(block, "input_shape");
    if (!input_shape_value.is_null()) {
        if (!input_shape_value.is_array() || input_shape_value.empty()) {
            field_error("input_shape", "a non-empty array of ints/nulls");
        }
        for (const Json& dim : input_shape_value) {
            if (dim.is_null()) {
                out.expected_input_shape.push_back(-1);
                continue;
            }
            long long number = 0;
            if (!as_int(dim, &number) || number < 0) {
                field_error("input_shape", "non-negative ints or nulls");
            }
            out.expected_input_shape.push_back(number);
        }
    }

    const Json& tile_value = metadata_number_source(block, metadata, "tile");
    if (!tile_value.is_null()) {
        if (!tile_value.is_array() || tile_value.size() != 3) {
            field_error("tile", "an [inline, xline, time] triple");
        }
        for (const Json& dim : tile_value) {
            out.tile.push_back(positive_int_field(dim, "tile"));
        }
    }

    const Json& overlap_value = metadata_number_source(block, metadata,
                                                       "overlap");
    if (!overlap_value.is_null()) {
        long long number = 0;
        if (!as_int(overlap_value, &number) || number < 0 ||
            number > std::numeric_limits<int>::max()) {
            field_error("overlap", "a non-negative integer");
        }
        out.overlap = static_cast<int>(number);
    }

    const Json& batch_value = metadata_number_source(block, metadata, "batch");
    if (!batch_value.is_null()) {
        long long number = 0;
        if (!as_int(batch_value, &number) || number < 1 ||
            number > std::numeric_limits<int>::max()) {
            field_error("batch", "an integer >= 1");
        }
        out.batch = static_cast<int>(number);
    }

    const Json& nodata_value = metadata_number_source(block, metadata,
                                                      "nodata");
    if (!nodata_value.is_null()) {
        double number = 0.0;
        if (!as_finite_double(nodata_value, &number)) {
            field_error("nodata", "a finite number");
        }
        out.nodata = number;
    }

    return out;
}

Json make_diagnostic(const std::string& code, const std::string& severity,
                     const std::string& message) {
    Json diagnostic = Json::object();
    diagnostic["code"] = code;
    diagnostic["severity"] = severity;
    diagnostic["message"] = message;
    return diagnostic;
}

Json join_errors(const Json& errors) {
    std::string joined;
    for (const Json& error : errors) {
        if (!joined.empty()) joined += "; ";
        joined += error.get<std::string>();
    }
    return Json(joined);
}

}  // namespace

Json LoadedModelPackage::to_json() const {
    Json out = Json::object();
    out["manifest_path"] = manifest_path;
    out["package_root"] = package_root;
    out["artifact_path"] = artifact_path;
    out["artifact_sha256"] = artifact_sha256;
    out["artifact_bytes"] = artifact_bytes;
    out["model_id"] = manifest.model_id;
    out["model_version"] = manifest.model_version;
    out["model_name"] = manifest.model_name;
    out["provider"] = manifest.provider;
    out["model_type"] = manifest.model_type;
    out["capability"] = manifest.capability;
    out["preprocessing_version"] = manifest.preprocessing_version;
    out["checksum"] = manifest.checksum ? Json(*manifest.checksum) : Json();
    out["classes"] = prediction.classes;
    out["class_names"] = prediction.class_names;
    out["input_bands"] = prediction.input_bands;
    Json normalization = Json::object();
    normalization["present"] = prediction.normalization.present;
    normalization["mean"] = prediction.normalization.mean;
    normalization["std"] = prediction.normalization.standard_deviation;
    out["normalization"] = std::move(normalization);
    out["expected_crs"] =
        prediction.expected_crs ? Json(*prediction.expected_crs) : Json();
    out["pixel_size"] =
        prediction.pixel_size ? Json(*prediction.pixel_size) : Json();
    out["input_shape"] = prediction.expected_input_shape;
    out["tile"] = prediction.tile;
    out["overlap"] = prediction.overlap;
    out["batch"] = prediction.batch;
    out["nodata"] = prediction.nodata ? Json(*prediction.nodata) : Json();
    out["diagnostics"] = diagnostics;
    return out;
}

LoadedModelPackage load_model_package(const std::string& manifest_path,
                                      const ModelPackageLoadOptions& options) {
    LoadedModelPackage out;
    out.manifest_path = manifest_path;
    const fs::path manifest_fs = detail::path_from_utf8(manifest_path);
    std::error_code ec;
    if (!fs::is_regular_file(manifest_fs, ec)) {
        throw ModelPackageError("Manifest not found: " + manifest_path);
    }
    const fs::path canonical = fs::weakly_canonical(manifest_fs, ec);
    out.package_root = (ec ? manifest_fs.parent_path() : canonical.parent_path())
                           .generic_string();

    out.manifest = parse_model_package_manifest(
        Json(manifest_path), Json(out.package_root));

    const Json errors = validate_model_package(
        out.manifest, options.require_artifact, options.allow_non_scientific);
    if (!errors.empty()) {
        throw ModelPackageError("model package validation failed: "
                                + join_errors(errors).get<std::string>());
    }

    if (!out.manifest.artifact.empty()) {
        fs::path artifact = detail::path_from_utf8(out.manifest.artifact);
        if (options.enforce_within_root) {
            try {
                artifact = pwb::interchange::ensure_within_root(
                    detail::path_from_utf8(out.package_root), artifact);
            } catch (const std::exception& exc) {
                throw ModelPackageError(
                    "artifact path escapes the model package root: "
                    + out.manifest.artifact + " (" + exc.what() + ")");
            }
        }
        out.artifact_path = artifact.generic_string();
        out.artifact_bytes =
            static_cast<long long>(fs::file_size(artifact, ec));
        if (ec) out.artifact_bytes = 0;
        out.artifact_sha256 = out.manifest.checksum.value_or("");
        if (out.artifact_sha256.empty()) {
            out.artifact_sha256 =
                pwb::domain::Sha256::of_file(artifact).value_or("");
        }
        out.diagnostics.push_back(make_diagnostic(
            "artifact_checksum_verified", "info",
            "artifact sha256 " + out.artifact_sha256 + " verified"));
        out.diagnostics.push_back(make_diagnostic(
            "artifact_resolved", "info",
            "artifact resolved to " + out.artifact_path));
        if (!options.enforce_within_root) {
            out.diagnostics.push_back(make_diagnostic(
                "package_root_check_disabled", "warning",
                "artifact containment is disabled by load options"));
        }
    }

    out.prediction = parse_prediction_metadata(out.manifest.metadata,
                                               out.manifest.output_schema);
    if (out.prediction.classes > 0) {
        out.diagnostics.push_back(make_diagnostic(
            "classes_declared", "info",
            "package declares " + std::to_string(out.prediction.classes)
            + " class(es)"));
    } else {
        out.diagnostics.push_back(make_diagnostic(
            "classes_undeclared", "warning",
            "package does not declare classes; the run must supply them"));
    }
    if (out.prediction.normalization.present) {
        out.diagnostics.push_back(make_diagnostic(
            "normalization_declared", "info",
            "package declares input normalization; the native pipeline "
            "applies it before inference"));
    }
    return out;
}

CompatibilityReport check_model_package_compatibility(
    const LoadedModelPackage& package, const OnnxRuntimeSession& session) {
    CompatibilityReport report;
    const OnnxModelInfo& info = session.model_info();
    const PredictionModelMetadata& prediction = package.prediction;
    const std::vector<long long>& input_shape = info.input.shape;
    const std::vector<long long>& output_shape = info.output.shape;
    const auto error = [&report](std::string message) {
        report.errors.push_back(std::move(message));
    };
    const auto warning = [&report](std::string message) {
        report.warnings.push_back(std::move(message));
    };

    if (input_shape.size() != 5) {
        error("model input rank=" + std::to_string(input_shape.size())
              + "; tiled seismic expects (N,1,D,H,W)");
    } else if (!prediction.input_bands.empty()) {
        if (input_shape[1] >= 0
            && input_shape[1]
                   != static_cast<long long>(prediction.input_bands.size())) {
            error("model input channel count "
                  + std::to_string(input_shape[1])
                  + " does not match the package's "
                  + std::to_string(prediction.input_bands.size())
                  + " declared input bands");
        }
    }
    if (!prediction.expected_input_shape.empty()) {
        if (prediction.expected_input_shape.size() != input_shape.size()) {
            error("declared input_shape rank "
                  + std::to_string(prediction.expected_input_shape.size())
                  + " does not match the model input rank "
                  + std::to_string(input_shape.size()));
        } else {
            for (std::size_t axis = 0; axis < input_shape.size(); ++axis) {
                const long long declared = prediction.expected_input_shape[axis];
                const long long actual = input_shape[axis];
                if (declared >= 0 && actual >= 0 && declared != actual) {
                    error("declared input_shape axis " + std::to_string(axis)
                          + "=" + std::to_string(declared)
                          + " does not match the model's "
                          + std::to_string(actual));
                }
            }
        }
    }
    if (prediction.classes > 0) {
        if (output_shape.size() != 5) {
            error("model output rank=" + std::to_string(output_shape.size())
                  + "; tiled seismic expects (N,C,D,H,W)");
        } else if (output_shape[1] >= 0) {
            const long long model_channels = output_shape[1];
            // A single-channel output is the sigmoid pair [1 - p, p]
            // expanded by the fusion kernel, so it satisfies a two-class
            // declaration (tiled_onnx.py C == 1 path).
            const bool sigmoid_pair =
                model_channels == 1 && prediction.classes == 2;
            if (!sigmoid_pair
                && model_channels
                       != static_cast<long long>(prediction.classes)) {
                error("model output class count "
                      + std::to_string(model_channels)
                      + " does not match the package's declared "
                      + std::to_string(prediction.classes) + " classes");
            }
        }
    }
    if (prediction.normalization.present
        && !prediction.normalization.is_scalar()) {
        std::size_t expected = prediction.input_bands.size();
        if (expected == 0 && input_shape.size() > 1 && input_shape[1] >= 0) {
            expected = static_cast<std::size_t>(input_shape[1]);
        }
        if (expected > 0
            && prediction.normalization.mean.size() != expected) {
            error("normalization has "
                  + std::to_string(prediction.normalization.mean.size())
                  + " per-band entries but the model input has "
                  + std::to_string(expected) + " channel(s)");
        }
    }
    if (prediction.expected_crs) {
        warning("package requires CRS '" + *prediction.expected_crs
                + "'; the input grid must declare a matching CRS");
    }
    if (prediction.pixel_size) {
        warning("package requires a pixel size of "
                + std::to_string(*prediction.pixel_size)
                + "; the input grid geotransform must match");
    }
    return report;
}

}  // namespace pwb::prediction
