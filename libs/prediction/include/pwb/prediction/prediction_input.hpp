// Prediction input contract runtime — the production-side validation of a
// seismic grid before any voxel reaches the session.
//
// The Python contract (input_contract.py) normalizes a model's input schema;
// this runtime adds the tiled-seismic side the native task drives: a grid
// descriptor (shape, dtype, nodata, CRS/geotransform, optional quality
// mask), band mapping against the model package's declared bands and the
// package's CRS/scale requirements. Every violation is reported as a
// one-line, user-facing error before inference starts.

#pragma once

#include <array>
#include <optional>
#include <string>
#include <vector>

#include "pwb/domain/json.hpp"
#include "pwb/prediction/model_package_runtime.hpp"
#include "pwb/prediction/tiled_inference.hpp"

namespace pwb::prediction {

using pwb::domain::Json;

struct SeismicGridDescriptor {
    std::string name = "amplitude";
    std::string uri;                    // raw file path; "" = in-memory data
    Tile3 shape{};
    std::string dtype = "float32";      // float32 / float16 / float64
    std::optional<double> nodata;
    std::string crs;
    // GDAL geotransform order: [x0, dx, rx, y0, ry, dy].
    std::array<double, 6> geotransform{};
    bool has_geotransform = false;
    std::string unit;
    std::string quality_mask_uri;       // raw uint8, 1 = valid, 0 = nodata
    Json metadata = Json::object();

    Json to_json() const;
};

struct InputValidationOptions {
    bool require_source_uri = true;
    bool require_crs = false;
    bool require_geotransform = false;
    long long max_voxels = 0;           // 0 = no additional cap
};

// Band/channel mapping for the model input tensor. The native pipeline is a
// single-volume seismic reader, so the mapping is always channel 0; the
// type exists so the workflow/catalog descriptors carry an explicit seam.
struct BandMapping {
    int channel = 0;
    std::string band_name;
    std::string source_uri;

    Json to_json() const;
};

// Returns a JSON array of error strings (empty = valid). Never throws;
// malformed descriptor fields (NaN nodata, negative shape) are errors too.
Json validate_prediction_input(const SeismicGridDescriptor& input,
                               const LoadedModelPackage& package,
                               const InputValidationOptions& options =
                                   InputValidationOptions{});

// Throws InputContractError with the joined validation errors.
void require_valid_prediction_input(
    const SeismicGridDescriptor& input, const LoadedModelPackage& package,
    const InputValidationOptions& options = InputValidationOptions{});

// Single-volume mapping; throws InputContractError for multi-band packages
// the native pipeline cannot feed (declared explicitly rather than
// silently dropping bands).
BandMapping build_band_mapping(const SeismicGridDescriptor& input,
                               const LoadedModelPackage& package);

}  // namespace pwb::prediction
