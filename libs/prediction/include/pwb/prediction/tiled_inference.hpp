// CPP prediction core — tiled inference geometry ported from
// paleo_workbench/prediction/tiled_onnx.py (full-conversion plan M9, CONV-13).
//
// Qt-free, Python-free: the tile/halo/center-crop-fusion contract, the
// softmax-intermediate budget guard (#1187), the ONNX model-file gate
// (#1176), the per-tile resume markers, the OOM batch-halving protocol and
// the honest cancelled/success stats live here. The inference session itself
// is a seam (ISession): production binds onnxruntime behind it, tests bind a
// reproducible CPU stub frozen against the Python oracle.

#pragma once

#include <array>
#include <cstdint>
#include <functional>
#include <span>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace pwb::prediction {

using Tile3 = std::array<int, 3>;

inline constexpr Tile3 kDefaultTile{64, 128, 128};  // (inline, xline, time)
inline constexpr int kDefaultReceptiveField = 8;
// #1187: per-inference softmax intermediate budget (float32 logits copy).
inline constexpr long long kSoftmaxIntermediateBudgetBytes = 512LL * 1024 * 1024;
// #1176: refuse non-models before they reach a native runtime.
inline constexpr long long kOnnxModelMaxBytes = 4LL * 1024 * 1024 * 1024;

// Honest failure (bad model I/O contract, unusable input, OOM at batch 1).
class TiledInferenceError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Tile start positions covering [0, n) with stride = tile - overlap.
// n <= tile -> the single start 0; otherwise range(0, n - overlap, stride).
std::vector<int> tile_starts(int n, int tile, int overlap);

// Center-crop fusion: the ONE region tile *i* owns. First tile owns from 0,
// last tile owns to n; interiors are [start + overlap/2, next_start +
// overlap/2). Across tiles these ranges partition [0, n) exactly.
std::pair<int, int> authoritative_range(std::size_t index,
                                        const std::vector<int>& starts,
                                        int stride, int overlap, int n);

// #1187: fail closed when softmax intermediates would exceed the budget —
// explicit errors, never silent clamps. classes_bytes = classes * tile
// voxels * 4 (float32); batch * classes_bytes is the planned total.
void validate_softmax_budget(int batch, int classes, const Tile3& tile);

struct ModelBinding {
    std::string model_file;
    long long model_bytes = 0;
    std::string model_sha256;
};

// #1176: validate an ONNX model file (regular, .onnx suffix, non-empty,
// within the PALEO_ONNX_MAX_MODEL_BYTES load cap) and return binding
// metadata for provenance. The digest is computed from the file bytes
// (byte-identical to Python hashlib.sha256).
ModelBinding check_onnx_model_file(const std::string& model_path);

// Volume reader seam (production: geoviz_seismic zarr store).
class VolumeReader {
public:
    virtual ~VolumeReader() = default;
    virtual Tile3 shape() const = 0;
    // Values of volume[s0:e0, s1:e1, s2:e2] as C-order float32.
    virtual std::vector<float> read_voxel_window(int s0, int e0, int s1,
                                                 int e1, int s2,
                                                 int e2) const = 0;
};

namespace detail {

// Round-to-nearest-even float32 → float16 bits (the probmap quantization
// primitive, numpy-compatible: NaN payloads truncate, staying NaN). Exposed
// for the bit-exact oracle conversion table.
std::uint16_t float_to_half_bits(float value);

// float16 bits → float32 (IEEE 754 binary16, subnormals/inf/NaN included).
// Exact inverse of the finite path; the runtime uses it to summarize and
// inspect persisted probability maps without depending on numpy.
float half_bits_to_float(std::uint16_t bits);

}  // namespace detail

// Batched logits: float32 (N,C,D,H,W), C-order. `ndim` mirrors the numpy
// rank check (5 = runnable, 4/other = honest TiledInferenceError).
struct SessionOutput {
    int ndim = 5;
    int n = 0;
    int c = 0;
    int d = 0;
    int h = 0;
    int w = 0;
    std::vector<float> data;
};

struct SessionBatch {
    int n = 0;
    int d = 0;
    int h = 0;
    int w = 0;                      // input is (N,1,D,H,W) float32
    std::vector<float> data;
};

// Inference session seam (#1085). Production: onnxruntime session (optional
// dependency); CPU stub: the frozen per-voxel / fixed-convolution operators.
class InferenceSession {
public:
    virtual ~InferenceSession() = default;
    // Honest device reporting — never claims GPU unless CUDA really ran.
    virtual std::string device_mode() const = 0;
    virtual SessionOutput run(const SessionBatch& batch) = 0;
};

struct TiledRunOptions {
    int classes = 0;
    std::string work_root;
    int overlap = kDefaultReceptiveField;
    int batch = 1;
    Tile3 tile = kDefaultTile;
    std::function<bool()> cancel;                               // #1167
    std::function<void(double, const std::string&)> progress;   // done/total
};

struct TiledRunStats {
    std::string mode;
    int tiles_total = 0;
    int tiles_done = 0;
    bool cancelled = false;
    double elapsed_s = 0.0;
    int batch = 0;                  // batch actually used (OOM halving)
    Tile3 shape{};
    int classes = 0;
    int overlap = 0;
    bool binding_present = false;   // success path only (#1167 protocol)
};

// Stream tiles through the session; fuse by CENTER-CROP so every voxel gets
// exactly one authoritative prediction. classmap (uint8 argmax) and probmap
// (float16 bit patterns of the max probability) are caller-owned full-volume
// stores standing in for the zarr outputs; keeping them caller-owned is what
// makes a resumed run a plain second call (per-tile markers live on disk
// under <work_root>/tiles.done).
//
// Throws TiledInferenceError (contract violations, honest model errors) and
// std::invalid_argument (batch < 1 — Python raises ValueError there).
TiledRunStats run_tiled_inference(const std::string& model_path,
                                  const VolumeReader& reader,
                                  InferenceSession& session,
                                  const TiledRunOptions& options,
                                  std::span<std::uint8_t> classmap,
                                  std::span<std::uint16_t> probmap);

}  // namespace pwb::prediction
