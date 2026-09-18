#include <pwb/prediction/prediction_input.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <filesystem>
#include <limits>
#include <string>
#include <vector>

namespace pwb::prediction {
namespace {

namespace fs = std::filesystem;

std::string ascii_lower(std::string text) {
    for (char& ch : text) {
        if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch + 32);
    }
    return text;
}

std::string strip_ascii(std::string text) {
    const auto is_space = [](char ch) {
        return ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r'
            || ch == '\f' || ch == '\v';
    };
    std::size_t begin = 0;
    while (begin < text.size() && is_space(text[begin])) ++begin;
    std::size_t end = text.size();
    while (end > begin && is_space(text[end - 1])) --end;
    return text.substr(begin, end - begin);
}

std::string lowercase_collapsed(std::string text) {
    text = ascii_lower(strip_ascii(std::move(text)));
    std::string out;
    out.reserve(text.size());
    bool previous_space = false;
    for (const char ch : text) {
        const bool is_space = ch == ' ' || ch == '\t';
        if (is_space) {
            if (!previous_space) out.push_back(' ');
            previous_space = true;
        } else {
            out.push_back(ch);
            previous_space = false;
        }
    }
    return out;
}

bool dtype_element_size(const std::string& dtype, std::size_t* bytes) {
    const std::string normalized = ascii_lower(strip_ascii(dtype));
    if (normalized == "float32" || normalized == "f4") {
        *bytes = 4;
        return true;
    }
    if (normalized == "float16" || normalized == "f2") {
        *bytes = 2;
        return true;
    }
    if (normalized == "float64" || normalized == "f8") {
        *bytes = 8;
        return true;
    }
    return false;
}

bool checked_voxel_count(const Tile3& shape, unsigned long long* out) {
    unsigned long long product = 1;
    for (const int dim : shape) {
        if (dim <= 0) return false;
        const auto value = static_cast<unsigned long long>(dim);
        if (product > std::numeric_limits<unsigned long long>::max() / value) {
            return false;
        }
        product *= value;
    }
    *out = product;
    return true;
}

bool close_enough(double left, double right) {
    const double tolerance =
        std::max(1e-9 * std::max(std::abs(left), std::abs(right)), 1e-6);
    return std::abs(left - right) <= tolerance;
}

void push_error(Json* errors, std::string message) {
    errors->push_back(std::move(message));
}

std::string joined_errors(const Json& errors) {
    std::string joined;
    for (const Json& error : errors) {
        if (!joined.empty()) joined += "; ";
        joined += error.get<std::string>();
    }
    return joined;
}

}  // namespace

Json SeismicGridDescriptor::to_json() const {
    Json out = Json::object();
    out["name"] = name;
    out["uri"] = uri;
    out["shape"] = shape;
    out["dtype"] = dtype;
    out["nodata"] = nodata ? Json(*nodata) : Json();
    out["crs"] = crs;
    out["has_geotransform"] = has_geotransform;
    out["geotransform"] = geotransform;
    out["unit"] = unit;
    out["quality_mask_uri"] = quality_mask_uri;
    out["metadata"] = metadata;
    return out;
}

Json BandMapping::to_json() const {
    Json out = Json::object();
    out["channel"] = channel;
    out["band_name"] = band_name;
    out["source_uri"] = source_uri;
    return out;
}

Json validate_prediction_input(const SeismicGridDescriptor& input,
                               const LoadedModelPackage& package,
                               const InputValidationOptions& options) {
    Json errors = Json::array();
    const PredictionModelMetadata& prediction = package.prediction;

    unsigned long long voxels = 0;
    if (!checked_voxel_count(input.shape, &voxels)) {
        push_error(&errors,
                   "input grid shape must be a positive (inline, xline, time) "
                   "triple whose voxel count fits in memory");
    } else if (options.max_voxels > 0
               && voxels > static_cast<unsigned long long>(
                              options.max_voxels)) {
        push_error(&errors,
                   "input grid has " + std::to_string(voxels)
                       + " voxels, above the configured limit of "
                       + std::to_string(options.max_voxels)
                       + " (raise max_voxels to run this volume)");
    }

    std::size_t element_bytes = 0;
    if (!dtype_element_size(input.dtype, &element_bytes)) {
        push_error(&errors,
                   "input dtype '" + input.dtype
                       + "' is not supported by the native prediction "
                         "runtime (float32/float16/float64 only; convert the "
                         "source before running)");
    }

    if (input.nodata
        && !std::isfinite(static_cast<double>(*input.nodata))) {
        push_error(&errors, "input nodata sentinel must be a finite number");
    }

    if (input.has_geotransform) {
        for (std::size_t i = 0; i < input.geotransform.size(); ++i) {
            if (!std::isfinite(input.geotransform[i])) {
                push_error(&errors,
                           "input geotransform entry "
                               + std::to_string(i) + " is not finite");
                break;
            }
        }
    }

    if (options.require_source_uri && input.uri.empty()) {
        push_error(&errors,
                   "input grid must provide a raw source uri (or disable "
                   "require_source_uri for in-memory pipelines)");
    }
    if (!input.uri.empty()) {
        std::error_code ec;
        const fs::path path(input.uri);
        if (!fs::is_regular_file(path, ec)) {
            push_error(&errors, "input volume not found: " + input.uri);
        } else if (voxels > 0 && element_bytes > 0) {
            const auto expected = voxels * element_bytes;
            const auto actual =
                static_cast<unsigned long long>(fs::file_size(path, ec));
            if (ec) {
                push_error(&errors,
                           "input volume " + input.uri
                               + " could not be sized");
            } else if (actual != expected) {
                push_error(
                    &errors,
                    "input volume " + input.uri + " is "
                        + std::to_string(actual) + " bytes but shape ("
                        + std::to_string(input.shape[0]) + ", "
                        + std::to_string(input.shape[1]) + ", "
                        + std::to_string(input.shape[2]) + ") with dtype "
                        + input.dtype + " needs " + std::to_string(expected)
                        + " bytes");
            }
        }
    }

    if (!input.quality_mask_uri.empty()) {
        std::error_code ec;
        const fs::path mask(input.quality_mask_uri);
        if (!fs::is_regular_file(mask, ec)) {
            push_error(&errors,
                       "quality mask not found: " + input.quality_mask_uri);
        } else if (voxels > 0) {
            const auto actual =
                static_cast<unsigned long long>(fs::file_size(mask, ec));
            if (!ec && actual != voxels) {
                push_error(&errors,
                           "quality mask " + input.quality_mask_uri + " is "
                               + std::to_string(actual)
                               + " bytes but the grid has "
                               + std::to_string(voxels) + " voxels");
            }
        }
    }

    if (options.require_crs && input.crs.empty()) {
        push_error(&errors,
                   "input grid CRS is required but the descriptor is missing "
                   "a crs");
    }
    if (options.require_geotransform && !input.has_geotransform) {
        push_error(&errors,
                   "input grid geotransform is required but the descriptor "
                   "does not carry one");
    }
    if (prediction.expected_crs && !input.crs.empty()) {
        if (lowercase_collapsed(input.crs)
            != lowercase_collapsed(*prediction.expected_crs)) {
            push_error(&errors,
                       "input CRS '" + input.crs
                           + "' does not match the model package requirement '"
                           + *prediction.expected_crs + "'");
        }
    } else if (prediction.expected_crs && input.crs.empty()) {
        push_error(&errors,
                   "model package requires CRS '" + *prediction.expected_crs
                       + "' but the input grid does not declare a CRS");
    }
    if (prediction.pixel_size) {
        if (!input.has_geotransform) {
            push_error(&errors,
                       "model package requires a pixel size of "
                           + std::to_string(*prediction.pixel_size)
                           + " but the input grid has no geotransform");
        } else {
            const double pixel_x = std::abs(input.geotransform[1]);
            const double pixel_y = std::abs(input.geotransform[5]);
            if (!close_enough(pixel_x, *prediction.pixel_size)
                || !close_enough(pixel_y, *prediction.pixel_size)) {
                push_error(&errors,
                           "input pixel size (" + std::to_string(pixel_x)
                               + ", " + std::to_string(pixel_y)
                               + ") does not match the model package "
                                 "requirement "
                               + std::to_string(*prediction.pixel_size));
            }
        }
    }

    if (prediction.input_bands.size() > 1) {
        push_error(&errors,
                   "model package declares "
                       + std::to_string(prediction.input_bands.size())
                       + " input bands ("
                       + [&prediction] {
                             std::string listed;
                             for (const std::string& band :
                                  prediction.input_bands) {
                                 if (!listed.empty()) listed += ", ";
                                 listed += band;
                             }
                             return listed;
                         }()
                       + "); the native tiled pipeline feeds a single seismic "
                         "volume — split the bands into a stacked model or "
                         "extend the pipeline");
    }

    return errors;
}

void require_valid_prediction_input(const SeismicGridDescriptor& input,
                                    const LoadedModelPackage& package,
                                    const InputValidationOptions& options) {
    const Json errors = validate_prediction_input(input, package, options);
    if (!errors.empty()) {
        throw InputContractError(joined_errors(errors));
    }
}

BandMapping build_band_mapping(const SeismicGridDescriptor& input,
                               const LoadedModelPackage& package) {
    const PredictionModelMetadata& prediction = package.prediction;
    if (prediction.input_bands.size() > 1) {
        throw InputContractError(
            "model package declares "
            + std::to_string(prediction.input_bands.size())
            + " input bands; the native tiled pipeline feeds a single "
              "seismic volume");
    }
    BandMapping mapping;
    mapping.channel = 0;
    mapping.band_name = prediction.input_bands.empty() ? input.name
                                                       : prediction.input_bands[0];
    mapping.source_uri = input.uri;
    return mapping;
}

}  // namespace pwb::prediction
