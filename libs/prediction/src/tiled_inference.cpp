// Tiled inference geometry — faithful port of
// paleo_workbench/prediction/tiled_onnx.py (see 13-findings.md §1).
//
// FP contract: every float32 operation below is elementwise IEEE in a fixed
// left-to-right order so the C++ stub path is bit-identical to the Python
// oracle generator (which asserts the same property against numpy). This TU
// is compiled with -ffp-contract=off — an FMA contraction would break the
// bit-exactness the oracle relies on.

#include <pwb/prediction/tiled_inference.hpp>

#include <pwb/domain/sha256.hpp>

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <thread>
#include <typeinfo>

#if defined(_WIN32)
#else
#include <fcntl.h>
#include <unistd.h>
#endif

namespace pwb::prediction {

std::uint16_t detail::float_to_half_bits(float value) {
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof bits);
    const std::uint16_t sign = static_cast<std::uint16_t>((bits >> 16) & 0x8000u);
    const std::uint32_t absbits = bits & 0x7fffffffu;

    if (absbits >= 0x7f800000u) {  // Inf / NaN
        // NaN keeps a truncated payload but never collapses to Inf: numpy
        // forces the lowest mantissa bit when the truncation would be zero
        // (probe: 0x7f800001 → 0x7c01, 0x7fc00000 → 0x7e00).
        const std::uint32_t payload_bits = absbits & 0x007fffffu;
        std::uint32_t payload = 0u;
        if (payload_bits != 0u) {
            payload = (payload_bits >> 13) & 0x03ffu;
            if (payload == 0u) payload = 1u;
        }
        return static_cast<std::uint16_t>(sign | 0x7c00u | payload);
    }

    const int exp32 = static_cast<int>(absbits >> 23) - 127;
    const std::uint32_t mant32 = (absbits & 0x007fffffu) | 0x00800000u;

    if (exp32 >= -14) {  // normal half range (and overflow)
        const std::uint32_t exp16 = static_cast<std::uint32_t>(exp32 + 15);
        std::uint32_t packed = (exp16 << 10) | ((absbits & 0x007fffffu) >> 13);
        const std::uint32_t remainder = absbits & 0x1fffu;
        constexpr std::uint32_t kTie = 0x1000u;
        if (remainder > kTie || (remainder == kTie && (packed & 1u) != 0u)) {
            ++packed;  // round-to-nearest-even; carry bumps the exponent
        }
        if ((packed >> 10) >= 0x1fu) {
            return static_cast<std::uint16_t>(sign | 0x7c00u);  // overflow → Inf
        }
        return static_cast<std::uint16_t>(sign | packed);
    }

    if (exp32 < -26) return sign;  // below half subnormal minimum → zero

    // Subnormal half: value = mant(24-bit) * 2^(exp32-23); target m * 2^-24.
    const int shift = 23 - (exp32 + 24);  // in [14, 25] here
    const std::uint32_t remainder_mask = (1u << shift) - 1u;
    const std::uint32_t tie = 1u << (shift - 1);
    std::uint32_t m = mant32 >> shift;
    const std::uint32_t remainder = mant32 & remainder_mask;
    if (remainder > tie || (remainder == tie && (m & 1u) != 0u)) ++m;
    if (m >= 0x0400u) {  // rounds up into the minimum normal
        return static_cast<std::uint16_t>(sign | 0x0400u);
    }
    return static_cast<std::uint16_t>(sign | m);
}

namespace {

namespace fs = std::filesystem;

std::string tile_key(const std::array<std::size_t, 3>& t) {
    char buffer[64];
    std::snprintf(buffer, sizeof buffer, "t_%05d_%05d_%05d",
                  static_cast<int>(t[0]), static_cast<int>(t[1]),
                  static_cast<int>(t[2]));
    return buffer;
}

void fsync_dir_best_effort(const fs::path& dir) {
#if defined(_WIN32)
    (void)dir;  // markers are best-effort on Windows; resume still works
#else
    const int fd = ::open(dir.c_str(), O_RDONLY);
    if (fd < 0) return;
    ::fsync(fd);
    ::close(fd);
#endif
}

// #1085 OOM classification (Python module-private _looks_like_oom):
// "type: message" lowercased contains "out of memory" or "oom", or both
// "alloc" and "fail" (Python `a or b or c and d` precedence).
bool looks_like_oom(const std::string& exception_type_and_message) {
    std::string text = exception_type_and_message;
    std::transform(text.begin(), text.end(), text.begin(),
                   [](unsigned char ch) {
                       return static_cast<char>(std::tolower(ch));
                   });
    const bool alloc_fail = text.find("alloc") != std::string::npos
                         && text.find("fail") != std::string::npos;
    return text.find("out of memory") != std::string::npos
        || text.find("oom") != std::string::npos || alloc_fail;
}

// numpy argmax over the channel axis: first maximum; NaN beats everything
// and the FIRST NaN channel wins. numpy .max over the same axis propagates
// NaN (any NaN → NaN).
void channel_argmax_and_max(const float* column, int count, int* argmax,
                            float* max_out) {
    int best = 0;
    float best_value = column[0];
    float max_value = column[0];
    bool saw_nan = std::isnan(column[0]);
    for (int c = 1; c < count; ++c) {
        const float v = column[c];
        if (std::isnan(v)) {
            if (!saw_nan) {
                best = c;
                saw_nan = true;
            }
        } else if (!saw_nan && v > best_value) {
            best = c;
            best_value = v;
        }
        if (std::isnan(v)) {
            max_value = v;  // any NaN wins the max reduction
        } else if (!std::isnan(max_value) && v > max_value) {
            max_value = v;
        }
    }
    *argmax = best;
    *max_out = max_value;
}

// One fused tile group: read halo-expanded tiles, zero-pad volume edges,
// infer once, center-crop fuse into the output stores.
void run_tile_group(const VolumeReader& reader, InferenceSession& session,
                    const Tile3& shape, const Tile3& tile,
                    const std::vector<int>* starts, const int* stride,
                    int overlap, int classes,
                    const std::vector<std::array<std::size_t, 3>>& group,
                    std::span<std::uint8_t> classmap,
                    std::span<std::uint16_t> probmap) {
    const std::size_t tile_voxels =
        static_cast<std::size_t>(tile[0]) * tile[1] * tile[2];

    SessionBatch batch;
    batch.n = static_cast<int>(group.size());
    batch.d = tile[0];
    batch.h = tile[1];
    batch.w = tile[2];
    batch.data.assign(group.size() * tile_voxels, 0.0f);

    struct CropWindow {
        std::pair<int, int> range[3];  // authoritative [lo, hi) per axis
        int offset[3][2];              // authoritative window inside the tile
    };
    std::vector<CropWindow> crops;
    crops.reserve(group.size());

    for (std::size_t b = 0; b < group.size(); ++b) {
        const std::size_t index[3] = {group[b][0], group[b][1], group[b][2]};
        const int s[3] = {starts[0][index[0]], starts[1][index[1]],
                          starts[2][index[2]]};
        const int e[3] = {std::min(s[0] + tile[0], shape[0]),
                          std::min(s[1] + tile[1], shape[1]),
                          std::min(s[2] + tile[2], shape[2])};
        const std::vector<float> block =
            reader.read_voxel_window(s[0], e[0], s[1], e[1], s[2], e[2]);

        // Edge tiles pad up to the tile shape with ZEROS: a 'same'-padding
        // model zero-pads at the volume boundary; interior cut planes never
        // pad — the overlap halo carries real data there.
        float* dst = batch.data.data() + b * tile_voxels;
        for (int a0 = 0; a0 < e[0] - s[0]; ++a0) {
            for (int a1 = 0; a1 < e[1] - s[1]; ++a1) {
                const std::size_t src_base =
                    (static_cast<std::size_t>(a0) * (e[1] - s[1]) + a1)
                    * (e[2] - s[2]);
                const std::size_t dst_base =
                    (static_cast<std::size_t>(a0) * tile[1] + a1) * tile[2];
                std::memcpy(dst + dst_base, block.data() + src_base,
                            static_cast<std::size_t>(e[2] - s[2])
                                * sizeof(float));
            }
        }

        CropWindow crop;
        crop.range[0] = authoritative_range(index[0], starts[0], stride[0],
                                            overlap, shape[0]);
        crop.range[1] = authoritative_range(index[1], starts[1], stride[1],
                                            overlap, shape[1]);
        crop.range[2] = authoritative_range(index[2], starts[2], stride[2],
                                            overlap, shape[2]);
        for (int axis = 0; axis < 3; ++axis) {
            crop.offset[axis][0] = crop.range[axis].first - s[axis];
            crop.offset[axis][1] = crop.range[axis].second - s[axis];
        }
        crops.push_back(crop);
    }

    SessionOutput out = session.run(batch);
    if (out.ndim == 4) {
        throw TiledInferenceError(
            "model output ndim=4; tiled seismic expects (N,C,64,128,128)");
    }
    if (out.ndim != 5) {
        throw TiledInferenceError("model output ndim="
                                  + std::to_string(out.ndim) + " unsupported");
    }
    // Deviation from Python (documented in 13-decisions.md D15/D18): numpy
    // silently clamps an out-of-range crop when a session returns the wrong
    // spatial tile shape, and raises IndexError/ValueError for a short batch
    // or an empty channel axis; here those would read out of bounds, so fail
    // honestly instead.
    if (out.d != tile[0] || out.h != tile[1] || out.w != tile[2]) {
        throw TiledInferenceError(
            "model output tile shape (" + std::to_string(out.d) + ", "
            + std::to_string(out.h) + ", " + std::to_string(out.w)
            + ") does not match the input tile (" + std::to_string(tile[0])
            + ", " + std::to_string(tile[1]) + ", " + std::to_string(tile[2])
            + ")");
    }
    if (out.n != static_cast<int>(group.size())) {
        throw TiledInferenceError(
            "model output batch " + std::to_string(out.n)
            + " does not match the tile group size "
            + std::to_string(group.size()));
    }
    if (out.c < 1) {
        throw TiledInferenceError("model output has no channels");
    }
    const std::size_t plane =
        static_cast<std::size_t>(out.d) * static_cast<std::size_t>(out.h)
        * static_cast<std::size_t>(out.w);
    const std::size_t expected_elements =
        static_cast<std::size_t>(out.n) * static_cast<std::size_t>(out.c)
        * plane;
    if (out.data.size() != expected_elements) {
        throw TiledInferenceError(
            "model output data size " + std::to_string(out.data.size())
            + " does not match its declared shape");
    }

    const int n_cls = out.c;
    // Softmax over the channel axis when C > 1 (max-subtracted, float32,
    // left-to-right accumulation); the 1-class path expands to the sigmoid
    // pair [1 - out, out]. Both mirror tiled_onnx._softmax / np.concatenate.
    std::vector<float> probs;
    int prob_channels = n_cls;
    if (n_cls > 1) {
        probs.resize(out.data.size());
        for (int item = 0; item < out.n; ++item) {
            const float* item_base =
                out.data.data()
                + static_cast<std::size_t>(item) * plane * n_cls;
            float* probs_base =
                probs.data()
                + static_cast<std::size_t>(item) * plane * n_cls;
            for (std::size_t voxel = 0; voxel < plane; ++voxel) {
                float m = item_base[voxel];
                for (int c = 1; c < n_cls; ++c) {
                    const float v = item_base[static_cast<std::size_t>(c) * plane + voxel];
                    if (std::isnan(v) || v > m) m = v;  // numpy max: NaN wins
                }
                float sum = 0.0f;
                for (int c = 0; c < n_cls; ++c) {
                    const float e =
                        std::exp(item_base[static_cast<std::size_t>(c) * plane + voxel] - m);
                    probs_base[static_cast<std::size_t>(c) * plane + voxel] = e;
                    sum = sum + e;
                }
                for (int c = 0; c < n_cls; ++c) {
                    float& slot =
                        probs_base[static_cast<std::size_t>(c) * plane + voxel];
                    slot = slot / sum;
                }
            }
        }
    } else {
        prob_channels = 2;
        probs.resize(out.data.size() * 2);
        // Planar layout (matches np.concatenate(axis=1) and the crop below).
        for (int item = 0; item < out.n; ++item) {
            float* slot0 = probs.data()
                         + static_cast<std::size_t>(item) * 2 * plane;
            float* slot1 = slot0 + plane;
            const float* src = out.data.data() + static_cast<std::size_t>(item) * plane;
            for (std::size_t voxel = 0; voxel < plane; ++voxel) {
                slot0[voxel] = 1.0f - src[voxel];
                slot1[voxel] = src[voxel];
            }
        }
    }

    for (std::size_t b = 0; b < group.size(); ++b) {
        const auto& crop = crops[b];
        const float* probs_base =
            probs.data() + b * plane * static_cast<std::size_t>(prob_channels);
        for (int a0 = crop.offset[0][0]; a0 < crop.offset[0][1]; ++a0) {
            for (int a1 = crop.offset[1][0]; a1 < crop.offset[1][1]; ++a1) {
                for (int a2 = crop.offset[2][0]; a2 < crop.offset[2][1]; ++a2) {
                    const std::size_t voxel =
                        (static_cast<std::size_t>(a0) * static_cast<std::size_t>(out.h)
                         + static_cast<std::size_t>(a1))
                            * static_cast<std::size_t>(out.w)
                        + static_cast<std::size_t>(a2);
                    std::vector<float> values(prob_channels);
                    for (int c = 0; c < prob_channels; ++c) {
                        values[c] = probs_base[static_cast<std::size_t>(c) * plane + voxel];
                    }
                    int argmax = 0;
                    float max_prob = 0.0f;
                    channel_argmax_and_max(values.data(), prob_channels,
                                           &argmax, &max_prob);
                    const std::size_t g0 =
                        static_cast<std::size_t>(crop.range[0].first + a0
                                                 - crop.offset[0][0]);
                    const std::size_t g1 =
                        static_cast<std::size_t>(crop.range[1].first + a1
                                                 - crop.offset[1][0]);
                    const std::size_t g2 =
                        static_cast<std::size_t>(crop.range[2].first + a2
                                                 - crop.offset[2][0]);
                    const std::size_t global =
                        (g0 * static_cast<std::size_t>(shape[1]) + g1)
                            * static_cast<std::size_t>(shape[2])
                        + g2;
                    classmap[global] = static_cast<std::uint8_t>(argmax);
                    probmap[global] = detail::float_to_half_bits(max_prob);
                }
            }
        }
    }
}

}  // namespace

std::vector<int> tile_starts(int n, int tile, int overlap) {
    if (tile <= overlap) {
        throw TiledInferenceError("tile " + std::to_string(tile)
                                  + " must exceed overlap "
                                  + std::to_string(overlap));
    }
    const int stride = tile - overlap;
    if (n <= tile) return {0};
    std::vector<int> starts;
    for (int s = 0; s < n - overlap; s += stride) starts.push_back(s);
    return starts;
}

std::pair<int, int> authoritative_range(std::size_t index,
                                        const std::vector<int>& starts,
                                        int stride, int overlap, int n) {
    (void)stride;  // the Python signature carries it too; the rule needs none
    const int lo = index == 0 ? 0 : starts[index] + overlap / 2;
    const int hi = index == starts.size() - 1
                       ? n
                       : starts[index + 1] + overlap / 2;
    return {lo, hi};
}

void validate_softmax_budget(int batch, int classes, const Tile3& tile) {
    const long long budget = kSoftmaxIntermediateBudgetBytes;
    const long long budget_mib = budget / 1024 / 1024;
    char message[512];

    // Python ints are arbitrary precision; the fixed-width product is
    // overflow-checked so pathological tiles fail closed exactly like the
    // Python budget gate instead of wrapping (13-decisions.md D18).
    const long long kMaxLL = std::numeric_limits<long long>::max();
    bool overflow = tile[1] > 0 && tile[0] > kMaxLL / tile[1];
    long long tile_voxels = 0;
    if (!overflow) {
        tile_voxels = static_cast<long long>(tile[0]) * tile[1];
        overflow = tile[2] > 0 && tile_voxels > kMaxLL / tile[2];
        if (!overflow) tile_voxels *= tile[2];
    }
    if (!overflow) overflow = tile_voxels > kMaxLL / 4;
    long long bytes_per_unit = 1;
    if (!overflow) bytes_per_unit = std::max<long long>(1, tile_voxels * 4);

    const auto throw_classes_error = [&](double mib) {
        std::snprintf(message, sizeof message,
                      "classes=%d with tile (%d, %d, %d) needs %.0f MiB of "
                      "softmax intermediates per batch item (> %lld MiB "
                      "budget); refusing: class count does not match a "
                      "runnable tile model",
                      classes, tile[0], tile[1], tile[2], mib, budget_mib);
        throw TiledInferenceError(message);
    };

    if (overflow) {
        // The exact count is unrepresentable, so it is definitionally far
        // above the budget; the MiB figure goes through double (Python
        // formats the same division as float).
        const double mib = static_cast<double>(tile[0])
                         * static_cast<double>(tile[1])
                         * static_cast<double>(tile[2]) * 4.0
                         * static_cast<double>(std::max(classes, 0))
                         / 1024.0 / 1024.0;
        throw_classes_error(mib);
    }

    const long long classes_bytes = classes * bytes_per_unit;
    if (classes_bytes > budget) {
        throw_classes_error(static_cast<double>(classes_bytes) / 1024.0
                            / 1024.0);
    }
    // planned = batch * classes_bytes > budget, overflow-free (Python-exact:
    // batch > floor(budget / classes_bytes) ⟺ batch * classes_bytes > budget
    // for positive integers).
    if (batch > budget / classes_bytes) {
        const long long max_batch = std::max<long long>(1, budget / classes_bytes);
        const double mib = static_cast<double>(batch)
                         * static_cast<double>(classes_bytes) / 1024.0
                         / 1024.0;
        std::snprintf(message, sizeof message,
                      "batch=%d × classes=%d × tile (%d, %d, %d) would need "
                      "%.0f MiB of softmax intermediates (> %lld MiB budget); "
                      "reduce batch to <= %lld",
                      batch, classes, tile[0], tile[1], tile[2], mib,
                      budget_mib, max_batch);
        throw TiledInferenceError(message);
    }
}

ModelBinding check_onnx_model_file(const std::string& model_path) {
    const fs::path path(model_path);
    std::error_code ec;
    const fs::file_status status = fs::status(path, ec);
    const bool regular = !ec && status.type() == fs::file_type::regular;
    std::string suffix;
    if (path.has_extension()) {
        suffix = path.extension().string();
        std::transform(suffix.begin(), suffix.end(), suffix.begin(),
                       [](unsigned char ch) {
                           return static_cast<char>(std::tolower(ch));
                       });
    }
    long long size = 0;
    if (regular) {
        size = static_cast<long long>(fs::file_size(path, ec));
        if (ec) size = 0;
    }
    if (!regular || suffix != ".onnx" || size <= 0) {
        throw TiledInferenceError(
            "refusing to load non-model file as ONNX: " + model_path
            + " (regular .onnx files only)");
    }

    long long cap = kOnnxModelMaxBytes;
    const char* raw_cap = std::getenv("PALEO_ONNX_MAX_MODEL_BYTES");
    if (raw_cap != nullptr && *raw_cap != '\0') {
        char* end = nullptr;
        const long long parsed = std::strtoll(raw_cap, &end, 10);
        if (end != raw_cap && *end == '\0') cap = parsed;
    }
    if (size > cap) {
        throw TiledInferenceError(
            "ONNX model " + model_path + " is " + std::to_string(size)
            + " bytes, above the " + std::to_string(cap)
            + "-byte load cap (PALEO_ONNX_MAX_MODEL_BYTES overrides)");
    }

    ModelBinding binding;
    binding.model_file = path.filename().string();
    binding.model_bytes = size;
    binding.model_sha256 = pwb::domain::Sha256::of_file(path).value_or("");
    return binding;
}

TiledRunStats run_tiled_inference(const std::string& model_path,
                                  const VolumeReader& reader,
                                  InferenceSession& session,
                                  const TiledRunOptions& options,
                                  std::span<std::uint8_t> classmap,
                                  std::span<std::uint16_t> probmap) {
    if (!fs::is_regular_file(fs::path(model_path))) {
        throw TiledInferenceError("ONNX model not found: " + model_path);
    }
    (void)check_onnx_model_file(model_path);

    const Tile3 tile = options.tile;
    if (tile[0] <= 0 || tile[1] <= 0 || tile[2] <= 0) {
        throw TiledInferenceError(
            "tile must be a positive (il, xl, t) triple: ("
            + std::to_string(tile[0]) + ", " + std::to_string(tile[1]) + ", "
            + std::to_string(tile[2]) + ")");
    }
    if (options.classes <= 0) {
        throw TiledInferenceError("classes must be > 0, got "
                                  + std::to_string(options.classes));
    }
    if (options.batch < 1) {
        throw std::invalid_argument(
            "batch must be >= 1, got " + std::to_string(options.batch)
            + "; refusing to silently clamp");
    }
    if (options.overlap < 0) {
        // Deviation from Python (D18): a negative receptive field reaches
        // numpy's silent wrap-around there; fail closed here instead.
        throw TiledInferenceError("overlap must be >= 0, got "
                                  + std::to_string(options.overlap));
    }
    validate_softmax_budget(options.batch, options.classes, tile);

    const auto t0 = std::chrono::steady_clock::now();
    const Tile3 shape = reader.shape();

    // Caller-owned output stores (D9) must hold the full volume; anything
    // else would be a silent out-of-bounds write.
    const std::size_t voxels = static_cast<std::size_t>(shape[0])
                             * static_cast<std::size_t>(shape[1])
                             * static_cast<std::size_t>(shape[2]);
    if (classmap.size() != voxels || probmap.size() != voxels) {
        throw TiledInferenceError(
            "output stores must hold shape[0]*shape[1]*shape[2] = "
            + std::to_string(voxels) + " elements (got classmap "
            + std::to_string(classmap.size()) + ", probmap "
            + std::to_string(probmap.size()) + ")");
    }

    const fs::path work(options.work_root);
    fs::create_directories(work);
    const fs::path done_dir = work / "tiles.done";
    fs::create_directories(done_dir);

    std::vector<int> starts[3] = {
        tile_starts(shape[0], tile[0], options.overlap),
        tile_starts(shape[1], tile[1], options.overlap),
        tile_starts(shape[2], tile[2], options.overlap),
    };
    const int stride[3] = {tile[0] - options.overlap,
                           tile[1] - options.overlap,
                           tile[2] - options.overlap};

    std::vector<std::array<std::size_t, 3>> tiles;
    for (std::size_t i = 0; i < starts[0].size(); ++i)
        for (std::size_t j = 0; j < starts[1].size(); ++j)
            for (std::size_t k = 0; k < starts[2].size(); ++k)
                tiles.push_back({i, j, k});

    std::vector<std::string> completed;
    for (const auto& entry : fs::directory_iterator(done_dir)) {
        const std::string name = entry.path().filename().string();
        if (name.rfind("t_", 0) == 0) completed.push_back(name);
    }
    const auto is_completed = [&](const std::array<std::size_t, 3>& t) {
        const std::string key = tile_key(t);
        return std::find(completed.begin(), completed.end(), key)
               != completed.end();
    };

    TiledRunStats stats;
    stats.mode = session.device_mode();
    stats.tiles_total = static_cast<int>(tiles.size());
    stats.batch = std::max(1, options.batch);
    stats.shape = shape;
    stats.classes = options.classes;
    stats.overlap = options.overlap;

    int done_count = 0;
    std::size_t idx = 0;
    while (idx < tiles.size()) {
        if (options.cancel != nullptr && options.cancel()) {
            // #1167: keep the protocol complete so callers distinguish a
            // cancelled (resumable) run from a failed one — and note the
            // cancelled result carries NO model binding.
            stats.cancelled = true;
            stats.tiles_done = done_count;
            stats.elapsed_s =
                std::chrono::duration<double>(std::chrono::steady_clock::now()
                                              - t0)
                    .count();
            return stats;
        }
        std::vector<std::array<std::size_t, 3>> pending;
        const auto group_end =
            std::min(idx + static_cast<std::size_t>(stats.batch),
                     tiles.size());
        for (std::size_t t = idx; t < group_end; ++t) {
            if (!is_completed(tiles[t])) pending.push_back(tiles[t]);
        }
        if (pending.empty()) {
            idx += static_cast<std::size_t>(stats.batch);
            continue;
        }
        try {
            run_tile_group(reader, session, shape, tile, starts, stride,
                           options.overlap, options.classes, pending,
                           classmap, probmap);
        } catch (const std::exception& exc) {
            if (stats.batch > 1
                && looks_like_oom(std::string(typeid(exc).name()) + ": "
                                  + exc.what())) {
                stats.batch = std::max(1, stats.batch / 2);
                std::this_thread::sleep_for(
                    std::chrono::duration<double>(0.5 / stats.batch));
                continue;
            }
            throw;
        }
        for (const auto& t : pending) {
            std::ofstream marker(done_dir / tile_key(t));
            marker << "ok";
        }
        fsync_dir_best_effort(done_dir);
        done_count += static_cast<int>(pending.size());
        idx += static_cast<std::size_t>(stats.batch);
        if (options.progress != nullptr) {
            const double ratio =
                static_cast<double>(done_count)
                / static_cast<double>(std::max(stats.tiles_total, 1));
            options.progress(ratio,
                             std::to_string(done_count) + "/"
                                 + std::to_string(stats.tiles_total)
                                 + " tiles");
        }
    }

    stats.tiles_done = done_count;
    stats.cancelled = false;
    stats.elapsed_s =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - t0)
            .count();
    stats.binding_present = true;
    return stats;
}

}  // namespace pwb::prediction
