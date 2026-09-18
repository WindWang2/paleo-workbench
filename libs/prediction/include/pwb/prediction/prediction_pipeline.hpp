// Tiled prediction pipeline runtime — the native closure of
//
//   input -> tile plan -> load -> preprocess -> session -> center-crop
//   fusion -> class/probability outputs -> postprocess summary
//
// The tile geometry and fusion kernel stay in CONV-13's
// run_tiled_inference(); this runtime supplies the real ONNX session, the
// grid reader stack (raw/in-memory + nodata/quality-mask/normalization
// preprocessing), bounded output buffers, the deterministic summary,
// provenance and the spatial-result envelope. Cancellation and progress are
// the CONV-13 seams (checked between tile groups), so a cancelled run keeps
// its per-tile markers and resumes on the next execute.

#pragma once

#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <vector>

#include "pwb/domain/json.hpp"
#include "pwb/prediction/model_package_runtime.hpp"
#include "pwb/prediction/prediction_input.hpp"
#include "pwb/prediction/tiled_inference.hpp"

namespace pwb::prediction {

using pwb::domain::Json;

// Runtime-owned output buffers budget (classmap + probmap + valid mask).
// 2 GiB holds a 512^3 classmap + probmap with headroom; larger volumes must
// opt in explicitly (or be handled by a future disk-backed store).
inline constexpr long long kDefaultOutputBudgetBytes = 2LL * 1024 * 1024 * 1024;

// Headerless raw float volume reader (little-endian, C-order). Reads tile
// windows from disk; never materializes the whole volume.
class RawVolumeReader final : public VolumeReader {
public:
    RawVolumeReader(std::string path, const Tile3& shape, std::string dtype);
    ~RawVolumeReader() override;

    Tile3 shape() const override;
    std::vector<float> read_voxel_window(int s0, int e0, int s1, int e1,
                                         int s2, int e2) const override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// Caller-owned in-memory float32 volume (tests, workflow hand-off). Shape is
// validated against the vector size at construction.
class ArrayVolumeReader final : public VolumeReader {
public:
    ArrayVolumeReader(const Tile3& shape, std::vector<float> data);

    Tile3 shape() const override;
    std::vector<float> read_voxel_window(int s0, int e0, int s1, int e1,
                                         int s2, int e2) const override;

private:
    Tile3 shape_{};
    std::vector<float> data_;
};

// Preprocessing decorator applied between the reader and the session:
// quality mask (1 = valid), nodata replacement (sentinel -> 0.0) and the
// package's per-band/scalar normalization. It also owns the validity mask
// the summary and the optional mask output consume, so nodata voxels are
// marked exactly once regardless of tile overlap.
class PreprocessedVolumeReader final : public VolumeReader {
public:
    PreprocessedVolumeReader(const VolumeReader* base, const Tile3& shape,
                             std::optional<double> nodata,
                             const BandNormalization& normalization,
                             std::vector<std::uint8_t> quality_mask);

    Tile3 shape() const override;
    std::vector<float> read_voxel_window(int s0, int e0, int s1, int e1,
                                         int s2, int e2) const override;

    const std::vector<std::uint8_t>& valid_mask() const;
    long long nodata_voxels() const;

private:
    const VolumeReader* base_ = nullptr;
    Tile3 shape_{};
    std::optional<double> nodata_;
    BandNormalization normalization_;
    std::vector<std::uint8_t> quality_mask_;
    mutable std::vector<std::uint8_t> valid_mask_;
    mutable long long nodata_voxels_ = 0;
};

// Output artifacts on disk (headerless little-endian raw + descriptor JSON).
struct PredictionOutputPaths {
    std::string classmap;
    std::string probmap;
    std::string mask;
    std::string descriptor;
};

struct PredictionOutputDescriptor {
    Tile3 shape{};
    int classes = 0;
    std::vector<std::string> class_names;
    std::string classmap_path;
    std::string probmap_path;
    std::string mask_path;
    std::string classmap_dtype = "uint8";
    std::string probmap_dtype = "float16";
    std::string mask_dtype = "uint8";
    std::string byte_order = "little";
    std::string layout = "C";
    std::string crs;
    std::array<double, 6> geotransform{};
    bool has_geotransform = false;
    long long classmap_bytes = 0;
    long long probmap_bytes = 0;
    long long mask_bytes = 0;
    std::string classmap_sha256;
    std::string probmap_sha256;
    std::string mask_sha256;
    Json artifacts = Json::object();
    Json metadata = Json::object();

    Json to_json() const;
};

struct PredictionPipelineOptions {
    // 0 -> the package's declared classes, else the run must declare them.
    int classes = 0;
    // Sentinels: {0,0,0} / -1 / 0 fall back to the declared package
    // defaults, then kDefaultTile / kDefaultReceptiveField / 1.
    Tile3 tile{};
    int overlap = -1;
    int batch = 0;
    bool prefer_gpu = false;
    bool keep_probmap = true;
    bool write_mask = false;
    bool write_outputs = true;
    std::string output_dir;   // required when write_outputs
    std::string work_root;    // empty -> <output_dir>/inference.work
    long long output_budget_bytes = kDefaultOutputBudgetBytes;
    // Reuse <output_dir>/{classmap,probmap}.raw (a complete result or a
    // cancelled run's partial dump) and keep the per-tile markers so a
    // resumed execute only computes missing tiles. When no persisted
    // buffers exist, stale markers are cleared instead of skipping tiles
    // into a zero-filled map.
    bool resume = true;
    std::function<bool()> cancel;
    std::function<void(double, const std::string&)> progress;
};

struct PredictionPipelineResult {
    TiledRunStats stats;
    Json summary;
    Json spatial_result;
    Json output_descriptor;
    Json provenance;
    Json compatibility_warnings;
    PredictionOutputPaths paths;
    ModelBinding binding;
    bool outputs_written = false;
    bool resume_seeded = false;
    bool partial_outputs_written = false;
};

struct PredictionSummaryOptions {
    int histogram_bins = 10;
};

// Deterministic raster summary: per-class counts, confidence stats and a
// fixed-width histogram over the stored float16 probability map. NaN
// confidences are counted, never folded into the stats. `classes` fixes the
// class-count array length; out-of-range class ids land in
// `out_of_range_class_count` instead of silently growing the array.
Json compute_prediction_summary(std::span<const std::uint8_t> classmap,
                                std::span<const std::uint16_t> probmap,
                                int classes,
                                const std::vector<std::string>& class_names,
                                long long nodata_voxels,
                                bool probmap_stored,
                                const PredictionSummaryOptions& options = {});

// CLASSIFIED_RASTER envelope accepted by spatial_result::validate_spatial_result:
// grid + crs + 6-element geotransform + artifact path(s).
Json build_prediction_spatial_result(
    const PredictionOutputDescriptor& output, const Json& summary);

// Writes the raw artifacts + the descriptor JSON; fills sha256/size fields on
// `descriptor` (mutable: the descriptor describes what was written).
Json write_prediction_outputs(PredictionOutputDescriptor* descriptor,
                              std::span<const std::uint8_t> classmap,
                              std::span<const std::uint16_t> probmap,
                              std::span<const std::uint8_t> mask);

// Full pipeline. `reader` null -> RawVolumeReader over input.uri.
PredictionPipelineResult run_prediction_pipeline(
    const LoadedModelPackage& package, const SeismicGridDescriptor& input,
    const PredictionPipelineOptions& options,
    std::unique_ptr<VolumeReader> reader = nullptr);

// Convenience for in-memory callers.
PredictionPipelineResult run_prediction_pipeline(
    const LoadedModelPackage& package, const SeismicGridDescriptor& input,
    const PredictionPipelineOptions& options, std::vector<float> volume);

}  // namespace pwb::prediction
