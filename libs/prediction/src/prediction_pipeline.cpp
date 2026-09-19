// Tiled prediction pipeline runtime — see
// include/pwb/prediction/prediction_pipeline.hpp.
//
// The tile geometry, halo reads, zero-padding, OOM backoff, resume markers
// and center-crop fusion are CONV-13's run_tiled_inference(); this TU owns
// the reader stack, preprocessing, bounded outputs, deterministic summary,
// artifact writing, provenance and the spatial envelope.

#include <pwb/prediction/prediction_pipeline.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <string>
#include <utility>

#include <pwb/domain/sha256.hpp>
#include <pwb/prediction/spatial_result.hpp>

#include "runtime_io.hpp"

namespace pwb::prediction {
namespace {

namespace fs = std::filesystem;

constexpr double kConfidenceMinimum = 0.0;
constexpr double kConfidenceMaximum = 1.0;

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

enum class RawDtype { F32, F16, F64 };

bool parse_raw_dtype(const std::string& dtype, RawDtype* out,
                     std::size_t* element_bytes) {
    const std::string normalized = ascii_lower(strip_ascii(dtype));
    if (normalized == "float32" || normalized == "f4") {
        *out = RawDtype::F32;
        *element_bytes = 4;
        return true;
    }
    if (normalized == "float16" || normalized == "f2") {
        *out = RawDtype::F16;
        *element_bytes = 2;
        return true;
    }
    if (normalized == "float64" || normalized == "f8") {
        *out = RawDtype::F64;
        *element_bytes = 8;
        return true;
    }
    return false;
}

unsigned long long checked_voxels(const Tile3& shape) {
    unsigned long long product = 1;
    for (const int dim : shape) {
        if (dim <= 0) {
            throw TiledInferenceError(
                "volume shape must be a positive triple, got ("
                + std::to_string(shape[0]) + ", " + std::to_string(shape[1])
                + ", " + std::to_string(shape[2]) + ")");
        }
        const auto value = static_cast<unsigned long long>(dim);
        if (product > std::numeric_limits<unsigned long long>::max() / value) {
            throw TiledInferenceError(
                "volume shape voxel count overflows");
        }
        product *= value;
    }
    return product;
}

std::vector<int> tile_to_vector(const Tile3& tile) {
    return {tile[0], tile[1], tile[2]};
}

Tile3 default_tile_from_package(const LoadedModelPackage& package) {
    const std::vector<int>& declared = package.prediction.tile;
    if (declared.size() == 3) {
        return Tile3{declared[0], declared[1], declared[2]};
    }
    return kDefaultTile;
}

Json join_error_messages(const Json& errors) {
    std::string joined;
    for (const Json& error : errors) {
        if (!joined.empty()) joined += "; ";
        joined += error.get<std::string>();
    }
    return Json(joined);
}

}  // namespace

// ---------------------------------------------------------------- readers --

struct RawVolumeReader::Impl {
    fs::path path;
    std::string path_text;
    Tile3 shape{};
    RawDtype dtype = RawDtype::F32;
    std::size_t element_bytes = 4;
};

RawVolumeReader::RawVolumeReader(std::string path, const Tile3& shape,
                                 std::string dtype)
    : impl_(std::make_unique<Impl>()) {
    checked_voxels(shape);
    impl_->path_text = std::move(path);
    impl_->path = detail::path_from_utf8(impl_->path_text);
    impl_->shape = shape;
    if (!parse_raw_dtype(dtype, &impl_->dtype, &impl_->element_bytes)) {
        throw TiledInferenceError(
            "raw volume dtype '" + dtype
            + "' is not supported (float32/float16/float64)");
    }
    std::error_code ec;
    const auto size = fs::file_size(impl_->path, ec);
    if (ec) {
        throw TiledInferenceError("raw volume not found: " + impl_->path_text);
    }
    const auto expected = checked_voxels(shape) * impl_->element_bytes;
    if (size != expected) {
        throw TiledInferenceError(
            "raw volume " + impl_->path_text + " is " + std::to_string(size)
            + " bytes but shape (" + std::to_string(shape[0]) + ", "
            + std::to_string(shape[1]) + ", " + std::to_string(shape[2])
            + ") needs " + std::to_string(expected) + " bytes");
    }
}

RawVolumeReader::~RawVolumeReader() = default;

Tile3 RawVolumeReader::shape() const {
    return impl_->shape;
}

std::vector<float> RawVolumeReader::read_voxel_window(
    int s0, int e0, int s1, int e1, int s2, int e2) const {
    const Tile3& shape = impl_->shape;
    if (s0 < 0 || s1 < 0 || s2 < 0 || e0 > shape[0] || e1 > shape[1]
        || e2 > shape[2] || e0 <= s0 || e1 <= s1 || e2 <= s2) {
        throw TiledInferenceError("raw volume read out of bounds");
    }
    std::ifstream stream(impl_->path, std::ios::binary);
    if (!stream) {
        throw TiledInferenceError("raw volume " + impl_->path_text
                                  + " could not be opened");
    }
    const std::size_t width = static_cast<std::size_t>(e2 - s2);
    const std::size_t rows = static_cast<std::size_t>(e1 - s1);
    const std::size_t depth = static_cast<std::size_t>(e0 - s0);
    std::vector<float> out(depth * rows * width, 0.0f);
    std::string buffer(width * impl_->element_bytes, '\0');
    for (std::size_t a0 = 0; a0 < depth; ++a0) {
        for (std::size_t a1 = 0; a1 < rows; ++a1) {
            const std::size_t global_row =
                (static_cast<std::size_t>(s0) + a0)
                    * static_cast<std::size_t>(shape[1])
                + static_cast<std::size_t>(s1) + a1;
            const std::size_t offset =
                (global_row * static_cast<std::size_t>(shape[2])
                 + static_cast<std::size_t>(s2))
                * impl_->element_bytes;
            stream.seekg(static_cast<std::streamoff>(offset));
            stream.read(buffer.data(),
                        static_cast<std::streamsize>(buffer.size()));
            if (!stream) {
                throw TiledInferenceError(
                    "raw volume " + impl_->path_text + " short read");
            }
            const char* source = buffer.data();
            float* destination = out.data() + (a0 * rows + a1) * width;
            switch (impl_->dtype) {
                case RawDtype::F32:
                    std::memcpy(destination, source, width * sizeof(float));
                    break;
                case RawDtype::F16:
                    for (std::size_t k = 0; k < width; ++k) {
                        std::uint16_t bits = 0;
                        std::memcpy(&bits, source + k * 2, 2);
                        destination[k] = detail::half_bits_to_float(bits);
                    }
                    break;
                case RawDtype::F64:
                    for (std::size_t k = 0; k < width; ++k) {
                        double value = 0.0;
                        std::memcpy(&value, source + k * 8, 8);
                        destination[k] = static_cast<float>(value);
                    }
                    break;
            }
        }
    }
    return out;
}

ArrayVolumeReader::ArrayVolumeReader(const Tile3& shape, std::vector<float> data)
    : shape_(shape), data_(std::move(data)) {
    const unsigned long long voxels = checked_voxels(shape);
    if (voxels != data_.size()) {
        throw TiledInferenceError(
            "in-memory volume has " + std::to_string(data_.size())
            + " values but shape (" + std::to_string(shape[0]) + ", "
            + std::to_string(shape[1]) + ", " + std::to_string(shape[2])
            + ") needs " + std::to_string(voxels));
    }
}

Tile3 ArrayVolumeReader::shape() const {
    return shape_;
}

std::vector<float> ArrayVolumeReader::read_voxel_window(
    int s0, int e0, int s1, int e1, int s2, int e2) const {
    const Tile3& shape = shape_;
    if (s0 < 0 || s1 < 0 || s2 < 0 || e0 > shape[0] || e1 > shape[1]
        || e2 > shape[2] || e0 <= s0 || e1 <= s1 || e2 <= s2) {
        throw TiledInferenceError("in-memory volume read out of bounds");
    }
    const std::size_t width = static_cast<std::size_t>(e2 - s2);
    const std::size_t rows = static_cast<std::size_t>(e1 - s1);
    const std::size_t depth = static_cast<std::size_t>(e0 - s0);
    std::vector<float> out(depth * rows * width, 0.0f);
    for (std::size_t a0 = 0; a0 < depth; ++a0) {
        for (std::size_t a1 = 0; a1 < rows; ++a1) {
            const std::size_t source =
                ((static_cast<std::size_t>(s0) + a0)
                     * static_cast<std::size_t>(shape[1])
                 + static_cast<std::size_t>(s1) + a1)
                    * static_cast<std::size_t>(shape[2])
                + static_cast<std::size_t>(s2);
            std::memcpy(out.data() + (a0 * rows + a1) * width,
                        data_.data() + source, width * sizeof(float));
        }
    }
    return out;
}

PreprocessedVolumeReader::PreprocessedVolumeReader(
    const VolumeReader* base, const Tile3& shape, std::optional<double> nodata,
    const BandNormalization& normalization,
    std::vector<std::uint8_t> quality_mask,
    std::vector<std::uint8_t> seed_valid_mask)
    : base_(base),
      shape_(shape),
      nodata_(nodata),
      normalization_(normalization),
      quality_mask_(std::move(quality_mask)) {
    const auto voxels = checked_voxels(shape);
    if (!quality_mask_.empty() && quality_mask_.size() != voxels) {
        throw InputContractError(
            "quality mask has " + std::to_string(quality_mask_.size())
            + " voxels but the grid has " + std::to_string(voxels));
    }
    const bool tracking = nodata_.has_value() || !quality_mask_.empty()
                          || !seed_valid_mask.empty();
    if (tracking) {
        if (!seed_valid_mask.empty()) {
            if (seed_valid_mask.size() != voxels) {
                throw InputContractError(
                    "persisted validity mask has "
                    + std::to_string(seed_valid_mask.size())
                    + " voxels but the grid has " + std::to_string(voxels));
            }
            valid_mask_ = std::move(seed_valid_mask);
            for (const std::uint8_t value : valid_mask_) {
                if (value == 0) ++nodata_voxels_;
            }
        } else {
            valid_mask_.assign(static_cast<std::size_t>(voxels), 1);
        }
    }
}

Tile3 PreprocessedVolumeReader::shape() const {
    return shape_;
}

const std::vector<std::uint8_t>& PreprocessedVolumeReader::valid_mask() const {
    return valid_mask_;
}

long long PreprocessedVolumeReader::nodata_voxels() const {
    return nodata_voxels_;
}

std::vector<float> PreprocessedVolumeReader::read_voxel_window(
    int s0, int e0, int s1, int e1, int s2, int e2) const {
    std::vector<float> data =
        base_->read_voxel_window(s0, e0, s1, e1, s2, e2);
    const bool normalize = normalization_.present;
    const float mean = normalize
                           ? static_cast<float>(normalization_.mean.front())
                           : 0.0f;
    const float deviation =
        normalize ? static_cast<float>(
                        normalization_.standard_deviation.front())
                  : 1.0f;
    const bool track_mask = !valid_mask_.empty();
    std::size_t index = 0;
    for (int a0 = s0; a0 < e0; ++a0) {
        for (int a1 = s1; a1 < e1; ++a1) {
            for (int a2 = s2; a2 < e2; ++a2, ++index) {
                const std::size_t global =
                    (static_cast<std::size_t>(a0)
                         * static_cast<std::size_t>(shape_[1])
                     + static_cast<std::size_t>(a1))
                        * static_cast<std::size_t>(shape_[2])
                    + static_cast<std::size_t>(a2);
                bool invalid = false;
                if (track_mask) {
                    if (!quality_mask_.empty()
                        && quality_mask_[global] == 0) {
                        invalid = true;
                    }
                    // The sentinel is a float32 value in the source dtype;
                    // comparing in double would never match a sentinel that
                    // is not exactly representable in float32.
                    if (!invalid && nodata_
                        && data[index] == static_cast<float>(*nodata_)) {
                        invalid = true;
                    }
                    if (invalid && valid_mask_[global] != 0) {
                        valid_mask_[global] = 0;
                        ++nodata_voxels_;
                    }
                }
                if (invalid) {
                    data[index] = 0.0f;
                }
                // Normalize after the replacement (the oracle reference
                // feeds the zeroed sentinel through the same transform).
                if (normalize) {
                    data[index] = (data[index] - mean) / deviation;
                }
            }
        }
    }
    return data;
}

// --------------------------------------------------------------- summary ---

Json compute_prediction_summary(std::span<const std::uint8_t> classmap,
                                std::span<const std::uint16_t> probmap,
                                int classes,
                                const std::vector<std::string>& class_names,
                                long long nodata_voxels, bool probmap_stored,
                                const PredictionSummaryOptions& options) {
    if (classes < 0) {
        throw TiledInferenceError("summary classes must be >= 0");
    }
    if (!probmap.empty() && probmap.size() != classmap.size()) {
        throw TiledInferenceError(
            "summary probability map size " + std::to_string(probmap.size())
            + " does not match the class map size "
            + std::to_string(classmap.size()));
    }
    const int bins = std::max(1, options.histogram_bins);
    Json counts = Json::array();
    for (int i = 0; i < classes; ++i) counts.push_back(0);
    Json histogram = Json::array();
    for (int i = 0; i < bins; ++i) histogram.push_back(0);

    long long out_of_range = 0;
    long long nan_confidences = 0;
    long long scored = 0;
    double confidence_sum = 0.0;
    double confidence_min = std::numeric_limits<double>::infinity();
    double confidence_max = -std::numeric_limits<double>::infinity();
    // The fusion always materializes the probability map (the summary needs
    // it); `probmap_stored` only reports whether it was persisted.
    const bool have_probabilities = !probmap.empty();

    for (std::size_t voxel = 0; voxel < classmap.size(); ++voxel) {
        const std::uint8_t klass = classmap[voxel];
        if (klass < classes) {
            counts[klass] = counts[klass].get<long long>() + 1;
        } else {
            ++out_of_range;
        }
        if (!have_probabilities) continue;
        const double confidence =
            static_cast<double>(detail::half_bits_to_float(probmap[voxel]));
        if (std::isnan(confidence)) {
            ++nan_confidences;
            continue;
        }
        ++scored;
        confidence_sum += confidence;
        confidence_min = std::min(confidence_min, confidence);
        confidence_max = std::max(confidence_max, confidence);
        int bin = 0;
        if (confidence >= kConfidenceMaximum) {
            bin = bins - 1;
        } else if (confidence > kConfidenceMinimum) {
            bin = static_cast<int>(confidence * bins);
            bin = std::min(bin, bins - 1);
        }
        histogram[bin] = histogram[bin].get<long long>() + 1;
    }

    Json summary = Json::object();
    summary["summary_version"] = "pwb-prediction-summary-v1";
    summary["classes"] = classes;
    summary["class_names"] = class_names;
    summary["voxels_total"] = static_cast<long long>(classmap.size());
    summary["voxels_nodata"] = nodata_voxels;
    summary["class_counts"] = std::move(counts);
    summary["out_of_range_class_count"] = out_of_range;
    summary["probmap_stored"] = probmap_stored;
    if (have_probabilities) {
        summary["voxels_scored"] = scored;
        summary["nan_confidence_count"] = nan_confidences;
        summary["mean_confidence"] =
            scored > 0 ? Json(confidence_sum / static_cast<double>(scored))
                       : Json();
        summary["min_confidence"] =
            scored > 0 ? Json(confidence_min) : Json();
        summary["max_confidence"] =
            scored > 0 ? Json(confidence_max) : Json();
        summary["confidence_histogram"] = std::move(histogram);
        summary["confidence_histogram_bins"] = bins;
    } else {
        summary["voxels_scored"] = 0;
        summary["nan_confidence_count"] = 0;
        summary["mean_confidence"] = Json();
        summary["min_confidence"] = Json();
        summary["max_confidence"] = Json();
        summary["confidence_histogram"] = std::move(histogram);
        summary["confidence_histogram_bins"] = bins;
    }
    return summary;
}

// ------------------------------------------------------ outputs/spatial ----

Json PredictionOutputDescriptor::to_json() const {
    Json out = Json::object();
    out["shape"] = shape;
    out["classes"] = classes;
    out["class_names"] = class_names;
    out["classmap_path"] = classmap_path;
    out["probmap_path"] = probmap_path;
    out["mask_path"] = mask_path;
    out["classmap_dtype"] = classmap_dtype;
    out["probmap_dtype"] = probmap_dtype;
    out["mask_dtype"] = mask_dtype;
    out["byte_order"] = byte_order;
    out["layout"] = layout;
    out["crs"] = crs;
    out["geotransform"] = geotransform;
    out["has_geotransform"] = has_geotransform;
    out["classmap_bytes"] = classmap_bytes;
    out["probmap_bytes"] = probmap_bytes;
    out["mask_bytes"] = mask_bytes;
    out["classmap_sha256"] = classmap_sha256;
    out["probmap_sha256"] = probmap_sha256;
    out["mask_sha256"] = mask_sha256;
    out["artifacts"] = artifacts;
    out["metadata"] = metadata;
    return out;
}

Json build_prediction_spatial_result(
    const PredictionOutputDescriptor& output, const Json& summary) {
    // spatial_result.py reads the spatial contract from
    // payload.result_summary.spatial (falling back to payload.spatial), so
    // the grid/crs/geotransform/artifact_path keys live there; the flat
    // mirror on the envelope keeps direct consumers (catalog/map seams)
    // single-hop.
    Json grid = Json::object();
    grid["shape"] = output.shape;
    grid["classes"] = output.classes;
    grid["class_names"] = output.class_names;
    grid["geotransform"] = output.geotransform;
    grid["dtype"] = output.classmap_dtype;

    Json spatial = Json::object();
    spatial["spatial_output_type"] = std::string(kSpatialClassifiedRaster);
    spatial["grid"] = grid;
    spatial["grid_shape"] = output.shape;
    spatial["classes"] = output.classes;
    spatial["class_names"] = output.class_names;
    spatial["crs"] = output.crs;
    spatial["geotransform"] = output.geotransform;
    spatial["artifact_path"] = output.classmap_path;

    Json artifacts = Json::object();
    artifacts["classmap"] =
        output.classmap_path.empty() ? Json() : Json(output.classmap_path);
    artifacts["probmap"] =
        output.probmap_path.empty() ? Json() : Json(output.probmap_path);
    artifacts["mask"] = output.mask_path.empty() ? Json() : Json(output.mask_path);

    Json result_summary = Json::object();
    result_summary["spatial"] = spatial;
    result_summary["summary"] = summary;

    Json envelope = Json::object();
    envelope["spatial_output_type"] =
        std::string(kSpatialClassifiedRaster);
    envelope["crs"] = output.crs;
    envelope["geotransform"] = output.geotransform;
    envelope["grid"] = std::move(grid);
    envelope["artifact_path"] = output.classmap_path;
    envelope["artifacts"] = std::move(artifacts);
    envelope["result_summary"] = std::move(result_summary);
    envelope["summary"] = summary;
    return envelope;
}

namespace {

std::string_view as_bytes(std::span<const std::uint8_t> span) {
    return std::string_view(reinterpret_cast<const char*>(span.data()),
                            span.size());
}

std::string_view as_bytes(std::span<const std::uint16_t> span) {
    return std::string_view(reinterpret_cast<const char*>(span.data()),
                            span.size() * sizeof(std::uint16_t));
}

PredictionOutputPaths output_paths_for(const std::string& output_dir) {
    const fs::path root = detail::path_from_utf8(output_dir);
    PredictionOutputPaths paths;
    paths.classmap = (root / "classmap.raw").generic_string();
    paths.probmap = (root / "probmap.raw").generic_string();
    paths.mask = (root / "valid_mask.raw").generic_string();
    paths.descriptor = (root / "prediction_output.json").generic_string();
    return paths;
}

}  // namespace

Json write_prediction_outputs(PredictionOutputDescriptor* descriptor,
                              std::span<const std::uint8_t> classmap,
                              std::span<const std::uint16_t> probmap,
                              std::span<const std::uint8_t> mask) {
    const PredictionOutputPaths paths = output_paths_for(
        fs::path(descriptor->classmap_path).parent_path().generic_string());
    std::string error;
    if (!detail::write_file_bytes(paths.classmap, as_bytes(classmap), &error)) {
        throw TiledInferenceError("cannot write classmap: " + error);
    }
    descriptor->classmap_path = paths.classmap;
    descriptor->classmap_bytes = static_cast<long long>(classmap.size());
    descriptor->classmap_sha256 =
        pwb::domain::Sha256::of_bytes(as_bytes(classmap));

    if (!probmap.empty()) {
        if (!detail::write_file_bytes(paths.probmap, as_bytes(probmap),
                                      &error)) {
            throw TiledInferenceError("cannot write probmap: " + error);
        }
        descriptor->probmap_path = paths.probmap;
        descriptor->probmap_bytes =
            static_cast<long long>(probmap.size() * sizeof(std::uint16_t));
        descriptor->probmap_sha256 =
            pwb::domain::Sha256::of_bytes(as_bytes(probmap));
    }
    if (!mask.empty()) {
        if (!detail::write_file_bytes(paths.mask, as_bytes(mask), &error)) {
            throw TiledInferenceError("cannot write mask: " + error);
        }
        descriptor->mask_path = paths.mask;
        descriptor->mask_bytes = static_cast<long long>(mask.size());
        descriptor->mask_sha256 =
            pwb::domain::Sha256::of_bytes(as_bytes(mask));
    }
    descriptor->artifacts["classmap"] = descriptor->classmap_path;
    descriptor->artifacts["probmap"] =
        descriptor->probmap_path.empty() ? Json() : Json(descriptor->probmap_path);
    descriptor->artifacts["mask"] =
        descriptor->mask_path.empty() ? Json() : Json(descriptor->mask_path);
    const Json json = descriptor->to_json();
    if (!detail::write_file_bytes(paths.descriptor,
                                  pwb::domain::dump_json_python_compatible(json),
                                  &error)) {
        throw TiledInferenceError("cannot write output descriptor: " + error);
    }
    return json;
}

// ------------------------------------------------------- partial/resume -----

namespace {

constexpr const char* kRunFingerprintFile = "prediction_run.json";
constexpr const char* kPartialDescriptorFile =
    "prediction_output.partial.json";

// Identity of a run: everything that makes persisted classmap/probmap/mask
// reusable. Batch is deliberately excluded (it only affects scheduling, not
// the fused result).
Json build_run_fingerprint(const LoadedModelPackage& package,
                           const SeismicGridDescriptor& input, int classes,
                           const Tile3& tile, int overlap,
                           const std::string& source_sha256,
                           const std::string& quality_mask_sha256,
                           const std::optional<double>& nodata) {
    Json fingerprint = Json::object();
    fingerprint["fingerprint_version"] = 1;
    fingerprint["model_sha256"] = package.artifact_sha256;
    fingerprint["source_sha256"] = source_sha256;
    fingerprint["quality_mask_sha256"] = quality_mask_sha256;
    fingerprint["shape"] = input.shape;
    fingerprint["classes"] = classes;
    fingerprint["tile"] = tile_to_vector(tile);
    fingerprint["overlap"] = overlap;
    Json normalization = Json::object();
    normalization["present"] = package.prediction.normalization.present;
    normalization["mean"] = package.prediction.normalization.mean;
    normalization["std"] =
        package.prediction.normalization.standard_deviation;
    fingerprint["normalization"] = std::move(normalization);
    fingerprint["nodata"] = nodata ? Json(*nodata) : Json();
    return fingerprint;
}

bool fingerprint_matches(const std::string& output_dir,
                         const Json& fingerprint) {
    std::string error;
    const auto bytes = detail::read_file_bytes(
        detail::path_from_utf8(output_dir) / kRunFingerprintFile,
        &error);
    if (!bytes.has_value()) return false;
    try {
        return Json::parse(*bytes).dump() == fingerprint.dump();
    } catch (const std::exception&) {
        return false;
    }
}

void write_fingerprint(const std::string& output_dir,
                       const Json& fingerprint) {
    std::string error;
    if (!detail::write_file_bytes(
            detail::path_from_utf8(output_dir) / kRunFingerprintFile,
            pwb::domain::dump_json_python_compatible(fingerprint), &error)) {
        throw TiledInferenceError("cannot write run fingerprint: " + error);
    }
}

bool load_previous_outputs(const std::string& output_dir,
                           unsigned long long voxels,
                           std::vector<std::uint8_t>* classmap,
                           std::vector<std::uint16_t>* probmap) {
    std::error_code ec;
    const fs::path classmap_path =
        detail::path_from_utf8(output_dir) / "classmap.raw";
    const fs::path probmap_path =
        detail::path_from_utf8(output_dir) / "probmap.raw";
    if (!fs::is_regular_file(classmap_path, ec)
        || !fs::is_regular_file(probmap_path, ec)) {
        return false;
    }
    if (fs::file_size(classmap_path, ec) != voxels) return false;
    if (fs::file_size(probmap_path, ec)
        != voxels * sizeof(std::uint16_t)) {
        return false;
    }
    std::string error;
    const auto class_bytes = detail::read_file_bytes(classmap_path, &error);
    const auto prob_bytes = detail::read_file_bytes(probmap_path, &error);
    if (!class_bytes.has_value() || !prob_bytes.has_value()) return false;
    classmap->assign(class_bytes->begin(), class_bytes->end());
    probmap->resize(static_cast<std::size_t>(voxels));
    std::memcpy(probmap->data(), prob_bytes->data(),
                static_cast<std::size_t>(voxels) * sizeof(std::uint16_t));
    return true;
}

// Empty when the previous run did not persist a validity mask (or it does
// not match the grid): a tracking run must then recompute every tile.
std::vector<std::uint8_t> load_previous_mask(const std::string& output_dir,
                                             unsigned long long voxels) {
    const fs::path mask_path =
        detail::path_from_utf8(output_dir) / "valid_mask.raw";
    std::error_code ec;
    if (!fs::is_regular_file(mask_path, ec)
        || fs::file_size(mask_path, ec) != voxels) {
        return {};
    }
    std::string error;
    const auto bytes = detail::read_file_bytes(mask_path, &error);
    if (!bytes.has_value()) return {};
    return std::vector<std::uint8_t>(bytes->begin(), bytes->end());
}

void clear_resume_markers(const std::string& work_root) {
    // Without persisted buffers, a marker from an earlier run would make the
    // fusion skip that tile and leave the fresh (zero) buffer in place.
    std::error_code ec;
    fs::remove_all(detail::path_from_utf8(work_root) / "tiles.done", ec);
}

void write_partial_outputs(const std::string& output_dir, const Tile3& shape,
                           int classes,
                           std::span<const std::uint8_t> classmap,
                           std::span<const std::uint16_t> probmap,
                           std::span<const std::uint8_t> mask,
                           const TiledRunStats& stats, const Json& fingerprint,
                           PredictionOutputPaths* paths) {
    const PredictionOutputPaths full = output_paths_for(output_dir);
    std::string error;
    if (!detail::write_file_bytes(full.classmap, as_bytes(classmap), &error)) {
        throw TiledInferenceError("cannot write partial classmap: " + error);
    }
    if (!detail::write_file_bytes(full.probmap, as_bytes(probmap), &error)) {
        throw TiledInferenceError("cannot write partial probmap: " + error);
    }
    if (!mask.empty()
        && !detail::write_file_bytes(full.mask, as_bytes(mask), &error)) {
        throw TiledInferenceError("cannot write partial mask: " + error);
    }
    Json partial = Json::object();
    partial["status"] = "cancelled";
    partial["generator_version"] = "pwb-prediction-runtime-v1";
    partial["shape"] = shape;
    partial["classes"] = classes;
    partial["tiles_done"] = stats.tiles_done;
    partial["tiles_total"] = stats.tiles_total;
    partial["classmap_sha256"] =
        pwb::domain::Sha256::of_bytes(as_bytes(classmap));
    partial["probmap_sha256"] =
        pwb::domain::Sha256::of_bytes(as_bytes(probmap));
    partial["mask_sha256"] =
        mask.empty() ? Json() : Json(pwb::domain::Sha256::of_bytes(as_bytes(mask)));
    const fs::path partial_path =
        detail::path_from_utf8(output_dir) / kPartialDescriptorFile;
    if (!detail::write_file_bytes(
            partial_path,
            pwb::domain::dump_json_python_compatible(partial), &error)) {
        throw TiledInferenceError("cannot write partial descriptor: " + error);
    }
    write_fingerprint(output_dir, fingerprint);
    paths->classmap = full.classmap;
    paths->probmap = full.probmap;
    paths->mask = mask.empty() ? std::string() : full.mask;
    paths->descriptor = partial_path.generic_string();
}

}  // namespace

// -------------------------------------------------------------- pipeline ---

PredictionPipelineResult run_prediction_pipeline(
    const LoadedModelPackage& package, const SeismicGridDescriptor& input,
    const PredictionPipelineOptions& options,
    std::unique_ptr<VolumeReader> reader) {
    PredictionPipelineResult result;

    const int package_classes = package.prediction.classes;
    if (options.classes > 0 && package_classes > 0
        && options.classes != package_classes) {
        throw InputContractError(
            "run declares classes=" + std::to_string(options.classes)
            + " but the model package declares classes="
            + std::to_string(package_classes)
            + "; a class-count mismatch means the wrong label map");
    }
    const int classes =
        options.classes > 0 ? options.classes : package_classes;
    if (classes <= 0) {
        throw InputContractError(
            "prediction run must declare classes (> 0): the model package "
            "does not declare them and the run did not supply them");
    }

    Tile3 tile = options.tile;
    if (tile[0] == 0 && tile[1] == 0 && tile[2] == 0) {
        tile = default_tile_from_package(package);
    } else if (tile[0] <= 0 || tile[1] <= 0 || tile[2] <= 0) {
        // Mirrors tiled_onnx's TiledInferenceError for a malformed tile.
        throw TiledInferenceError(
            "tile must be a positive (il, xl, t) triple: ("
            + std::to_string(tile[0]) + ", " + std::to_string(tile[1]) + ", "
            + std::to_string(tile[2]) + "); refusing to silently clamp");
    }
    if (options.overlap < -1) {
        throw ValueError("overlap must be >= 0, got "
                         + std::to_string(options.overlap)
                         + "; refusing to silently clamp");
    }
    const int overlap =
        options.overlap >= 0
            ? options.overlap
            : (package.prediction.overlap >= 0 ? package.prediction.overlap
                                               : kDefaultReceptiveField);
    if (options.batch < 0) {
        // Mirrors tiled_onnx's built-in ValueError (batch is a caller knob;
        // never silently clamped).
        throw ValueError("batch must be >= 1, got "
                         + std::to_string(options.batch)
                         + "; refusing to silently clamp");
    }
    const int batch = options.batch > 0
                          ? options.batch
                          : (package.prediction.batch > 0
                                 ? package.prediction.batch
                                 : 1);

    if (package.artifact_path.empty()) {
        throw ModelPackageError(
            "model package has no artifact; a prediction run needs a "
            "loadable ONNX model");
    }

    // The package may declare the nodata sentinel; the grid descriptor wins
    // when both are present.
    const std::optional<double> effective_nodata =
        input.nodata.has_value() ? input.nodata : package.prediction.nodata;

    // Runtime-owned buffers: classmap (1 B/voxel) + probmap (2 B/voxel) +
    // validity mask (1 B/voxel when nodata/quality mask tracking is on) +
    // the quality-mask file itself when declared.
    const bool validity_tracking =
        effective_nodata.has_value() || !input.quality_mask_uri.empty();
    const long long bytes_per_voxel =
        1 + 2 + (validity_tracking ? 1 : 0)
        + (!input.quality_mask_uri.empty() ? 1 : 0);
    const long long budget = options.output_budget_bytes > 0
                                 ? options.output_budget_bytes
                                 : kDefaultOutputBudgetBytes;
    const long long budget_max_voxels = budget / bytes_per_voxel;
    if (budget_max_voxels <= 0) {
        throw InputContractError(
            "output budget " + std::to_string(budget)
            + " bytes is smaller than one voxel's "
            + std::to_string(bytes_per_voxel)
            + " bytes; raise output_budget_bytes");
    }
    InputValidationOptions validation = options.input_options;
    validation.max_voxels =
        validation.max_voxels > 0
            ? std::min(validation.max_voxels, budget_max_voxels)
            : budget_max_voxels;
    const Json input_errors =
        validate_prediction_input(input, package, validation);
    if (!input_errors.empty()) {
        throw InputContractError(
            join_error_messages(input_errors).get<std::string>());
    }
    const BandMapping mapping = build_band_mapping(input, package);

    OnnxRuntimeSession session = OnnxRuntimeSession::open_file(
        package.artifact_path, OnnxSessionOptions{"", options.prefer_gpu, 0, 0});
    const CompatibilityReport compatibility =
        check_model_package_compatibility(package, session);
    if (!compatibility.ok()) {
        throw ModelPackageError(
            join_error_messages(compatibility.errors).get<std::string>());
    }

    if (!reader) {
        reader = std::make_unique<RawVolumeReader>(input.uri, input.shape,
                                                   input.dtype);
    }

    std::vector<std::uint8_t> quality_mask;
    if (!input.quality_mask_uri.empty()) {
        std::string error;
        std::optional<std::string> bytes = detail::read_file_bytes(
            detail::path_from_utf8(input.quality_mask_uri), &error);
        if (!bytes) {
            throw InputContractError("quality mask "
                                     + input.quality_mask_uri
                                     + " could not be read: " + error);
        }
        quality_mask.assign(bytes->begin(), bytes->end());
    }

    const unsigned long long voxels = checked_voxels(input.shape);
    std::vector<std::uint8_t> classmap(static_cast<std::size_t>(voxels));
    std::vector<std::uint16_t> probmap(static_cast<std::size_t>(voxels));

    std::string work_root = options.work_root;
    if (work_root.empty()) {
        if (options.output_dir.empty()) {
            throw InputContractError(
                "output_dir or work_root is required for a tiled run "
                "(resume markers live on disk)");
        }
        work_root =
            (detail::path_from_utf8(options.output_dir) / "inference.work")
                .generic_string();
    }

    // Resume requires the persisted run fingerprint to match exactly: model
    // digest, source digest, shape, classes, tile/overlap, normalization and
    // nodata. Anything else means the previous classmap/probmap/mask belong
    // to different inputs and must not be reused.
    std::string source_sha256 = options.source_sha256;
    if (source_sha256.empty() && !input.uri.empty()) {
        source_sha256 =
            pwb::domain::Sha256::of_file(detail::path_from_utf8(input.uri))
                .value_or("");
    }
    std::string quality_mask_sha256;
    if (!input.quality_mask_uri.empty()) {
        quality_mask_sha256 =
            pwb::domain::Sha256::of_file(
                detail::path_from_utf8(input.quality_mask_uri))
                .value_or("");
    }
    const Json fingerprint = build_run_fingerprint(
        package, input, classes, tile, overlap, source_sha256,
        quality_mask_sha256, effective_nodata);

    std::vector<std::uint8_t> previous_mask;
    // No source identity (in-memory without an override, or an unreadable
    // file) means no resume: the fingerprint cannot prove the persisted
    // buffers belong to this input.
    if (options.resume && !source_sha256.empty()
        && !options.output_dir.empty()
        && fingerprint_matches(options.output_dir, fingerprint)
        && load_previous_outputs(options.output_dir, voxels, &classmap,
                                 &probmap)) {
        previous_mask = load_previous_mask(options.output_dir, voxels);
        if (!validity_tracking || !previous_mask.empty()) {
            result.resume_seeded = true;
        }
    }
    if (!result.resume_seeded) {
        clear_resume_markers(work_root);
        previous_mask.clear();
    }
    PreprocessedVolumeReader preprocessed(reader.get(), input.shape,
                                          effective_nodata,
                                          package.prediction.normalization,
                                          std::move(quality_mask),
                                          std::move(previous_mask));

    PredictionOutputDescriptor descriptor;
    descriptor.shape = input.shape;
    descriptor.classes = classes;
    descriptor.class_names = package.prediction.class_names;
    descriptor.crs = input.crs;
    descriptor.geotransform = input.geotransform;
    descriptor.has_geotransform = input.has_geotransform;

    // Validate the spatial envelope BEFORE any inference or side effect: a
    // result that fails the CLASSIFIED_RASTER contract (e.g. a missing CRS)
    // must not burn tiles nor let the cancel path persist partial artifacts.
    // Metadata needs result.binding.model_sha256, so it is filled post-run.
    const Json preflight =
        build_prediction_spatial_result(descriptor, Json::object());
    const Json preflight_errors =
        validate_spatial_result(preflight, Json(), false);
    if (!preflight_errors.empty()) {
        throw InputContractError(
            "prediction result failed the CLASSIFIED_RASTER spatial "
            "contract: "
            + join_error_messages(preflight_errors).get<std::string>());
    }

    TiledRunOptions tiled;
    tiled.classes = classes;
    tiled.work_root = work_root;
    tiled.overlap = overlap;
    tiled.batch = batch;
    tiled.tile = tile;
    tiled.cancel = options.cancel;
    tiled.progress = options.progress;
    result.stats = run_tiled_inference(package.artifact_path, preprocessed,
                                       session, tiled, classmap, probmap);
    // Perf (line 14, measured): the session already gated and hashed the
    // artifact in open_file — re-running check_onnx_model_file here paid a
    // second full-file SHA-256 (~400 ms per 64 MiB) for identical values.
    // The session's identity is also strictly the model that actually ran.
    result.binding.model_file =
        detail::path_from_utf8(package.artifact_path).filename().string();
    result.binding.model_bytes = session.model_info().model_bytes;
    result.binding.model_sha256 = session.model_info().model_sha256;
    result.compatibility_warnings = compatibility.warnings;

    Json provenance = Json::object();
    provenance["generator_version"] = "pwb-prediction-runtime-v1";
    provenance["runtime"] = session.model_info().to_json();
    Json package_provenance = Json::object();
    package_provenance["manifest_path"] = package.manifest_path;
    package_provenance["package_root"] = package.package_root;
    package_provenance["model_id"] = package.manifest.model_id;
    package_provenance["model_version"] = package.manifest.model_version;
    package_provenance["model_name"] = package.manifest.model_name;
    package_provenance["provider"] = package.manifest.provider;
    package_provenance["artifact_path"] = package.artifact_path;
    package_provenance["checksum"] = package.artifact_sha256;
    package_provenance["preprocessing_version"] =
        package.manifest.preprocessing_version;
    provenance["model_package"] = std::move(package_provenance);
    Json binding = Json::object();
    binding["model_file"] = result.binding.model_file;
    binding["model_bytes"] = result.binding.model_bytes;
    binding["model_sha256"] = result.binding.model_sha256;
    provenance["model_binding"] = std::move(binding);
    Json tiles = Json::object();
    tiles["tile"] = tile_to_vector(tile);
    tiles["overlap"] = overlap;
    tiles["batch"] = result.stats.batch;
    tiles["tiles_total"] = result.stats.tiles_total;
    tiles["tiles_done"] = result.stats.tiles_done;
    tiles["cancelled"] = result.stats.cancelled;
    tiles["resume_seeded"] = result.resume_seeded;
    provenance["tiles"] = std::move(tiles);
    Json input_provenance = Json::object();
    input_provenance["descriptor"] = input.to_json();
    input_provenance["band_mapping"] = mapping.to_json();
    input_provenance["voxels"] = static_cast<long long>(voxels);
    input_provenance["nodata_voxels"] = preprocessed.nodata_voxels();
    if (!input.uri.empty()) {
        input_provenance["source_sha256"] = source_sha256;
    }
    provenance["input"] = std::move(input_provenance);
    result.provenance = std::move(provenance);

    if (result.stats.cancelled) {
        Json summary = Json::object();
        summary["summary_version"] = "pwb-prediction-summary-v1";
        summary["cancelled"] = true;
        summary["classes"] = classes;
        summary["tiles_total"] = result.stats.tiles_total;
        summary["tiles_done"] = result.stats.tiles_done;
        result.summary = std::move(summary);
        result.output_descriptor = Json();
        result.spatial_result = Json();
        // Resume needs the fused probability map on disk; when the caller
        // disabled it there is nothing to seed from, so the markers are
        // cleared instead of skipping tiles into a zero-filled buffer.
        if (options.write_outputs && options.keep_probmap
            && !options.output_dir.empty()) {
            // Persist the in-memory fusion so the next execute can seed from
            // it and skip the marked tiles (true resume). The validity mask
            // is persisted whenever tracking is on: without it a resumed run
            // would recount nodata only for the tiles it re-reads.
            const std::span<const std::uint8_t> persisted_mask =
                (validity_tracking || options.write_mask)
                    ? std::span<const std::uint8_t>(preprocessed.valid_mask())
                    : std::span<const std::uint8_t>();
            write_partial_outputs(options.output_dir, input.shape, classes,
                                  classmap, probmap, persisted_mask,
                                  result.stats, fingerprint, &result.paths);
            result.partial_outputs_written = true;
        } else {
            clear_resume_markers(work_root);
        }
        return result;
    }
    if (!options.output_dir.empty()) {
        std::error_code ec;
        fs::remove(detail::path_from_utf8(options.output_dir)
                       / "prediction_output.partial.json",
                   ec);
    }

    const bool probmap_stored =
        options.keep_probmap && options.write_outputs
        && !options.output_dir.empty();
    result.summary = compute_prediction_summary(
        classmap, probmap, classes, package.prediction.class_names,
        preprocessed.nodata_voxels(), probmap_stored);

    descriptor.metadata["band_name"] = mapping.band_name;
    descriptor.metadata["manifest_path"] = package.manifest_path;
    descriptor.metadata["model_sha256"] = result.binding.model_sha256;

    if (options.write_outputs && options.output_dir.empty()) {
        throw InputContractError(
            "write_outputs is enabled but output_dir is empty");
    }
    PredictionOutputPaths paths;
    if (options.write_outputs) {
        paths = output_paths_for(options.output_dir);
        descriptor.classmap_path = paths.classmap;
    }

    // Build and validate the spatial envelope BEFORE any side effect: a
    // result that fails the CLASSIFIED_RASTER contract (e.g. a missing CRS)
    // must not leave artifacts or a resume fingerprint on disk.
    result.spatial_result =
        build_prediction_spatial_result(descriptor, result.summary);
    const Json spatial_errors =
        validate_spatial_result(result.spatial_result, Json(), false);
    if (!spatial_errors.empty()) {
        throw InputContractError(
            "prediction result failed the CLASSIFIED_RASTER spatial "
            "contract: "
            + join_error_messages(spatial_errors).get<std::string>());
    }

    if (options.write_outputs) {
        const std::span<const std::uint16_t> persisted_probmap =
            options.keep_probmap ? std::span<const std::uint16_t>(probmap)
                                 : std::span<const std::uint16_t>();
        const std::span<const std::uint8_t> persisted_mask =
            (validity_tracking || options.write_mask)
                ? std::span<const std::uint8_t>(preprocessed.valid_mask())
                : std::span<const std::uint8_t>();
        result.output_descriptor =
            write_prediction_outputs(&descriptor, classmap, persisted_probmap,
                                     persisted_mask);
        // Report only what was actually persisted (probmap/mask may be
        // intentionally absent).
        result.paths.classmap = descriptor.classmap_path;
        result.paths.probmap = descriptor.probmap_path;
        result.paths.mask = descriptor.mask_path;
        result.paths.descriptor = paths.descriptor;
        result.outputs_written = true;
        // Persist the fingerprint only together with the outputs: a failed
        // run leaves the previous consistent state untouched.
        write_fingerprint(options.output_dir, fingerprint);
    } else {
        result.output_descriptor = descriptor.to_json();
    }
    return result;
}

PredictionPipelineResult run_prediction_pipeline(
    const LoadedModelPackage& package, const SeismicGridDescriptor& input,
    const PredictionPipelineOptions& options, std::vector<float> volume) {
    auto reader =
        std::make_unique<ArrayVolumeReader>(input.shape, std::move(volume));
    return run_prediction_pipeline(package, input, options, std::move(reader));
}

}  // namespace pwb::prediction
