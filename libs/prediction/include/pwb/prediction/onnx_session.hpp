// Native ONNX Runtime inference session — the production binding of the
// CONV-13 InferenceSession seam.
//
// Qt-free, Python-free: the runtime library is discovered and loaded at
// process start (PALEO_ONNXRUNTIME_LIBRARY -> CMake hint -> platform default
// search) and driven through the C API vendored at
// third_party/onnxruntime/onnxruntime_c_api.h. No Python interpreter,
// package, or adapter participates in this path.
//
// Honest failure policy:
// - a missing runtime library raises TiledInferenceError with the searched
//   locations (never silently degrades to a stub);
// - tensor/type/shape contract violations fail before any voxel is scored;
// - device_mode() reports "cpu" unless a CUDA provider really created the
//   session. The CPU closure is the deliverable; requesting GPU fails fast
//   instead of pretending (the Python provider falls back, but a native
//   silent fallback would misreport provenance).

#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "pwb/domain/json.hpp"
#include "pwb/prediction/tiled_inference.hpp"

namespace pwb::prediction {

using pwb::domain::Json;

// Guard against absurd model outputs before allocating (float32 bytes).
// Distinct from kOnnxModelMaxBytes, which caps the *input* file.
inline constexpr long long kMaxOnnxTensorBytes = 4LL * 1024 * 1024 * 1024;

struct OnnxSessionOptions {
    // Explicit runtime library path. Empty -> PALEO_ONNXRUNTIME_LIBRARY,
    // then the CMake-baked hint, then the platform default search.
    std::string library_path;
    // GPU is a documented future seam. true fails fast (honest) instead of
    // silently running CPU under a GPU-labelled provenance envelope.
    bool prefer_gpu = false;
    // 0 = onnxruntime default. The resource gate sets these explicitly.
    int intra_op_threads = 0;
    int inter_op_threads = 0;
};

struct OnnxTensorInfo {
    std::string name;
    std::string element_type;      // "float32" / "float16" / "float64" / ...
    std::vector<long long> shape;  // dynamic dims reported as -1

    Json to_json() const;
};

struct OnnxModelInfo {
    std::string runtime_library;   // resolved path / loader search name
    std::string runtime_version;   // e.g. "1.29.0"
    std::string model_sha256;
    long long model_bytes = 0;
    std::string device_mode = "cpu";
    std::string provider = "CPUExecutionProvider";
    std::size_t input_count = 0;
    std::size_t output_count = 0;
    OnnxTensorInfo input;
    OnnxTensorInfo output;
    bool gpu_requested = false;

    Json to_json() const;
};

// Process-wide availability probe. Never throws; `error_out` receives the
// discovery failure when the runtime cannot be loaded.
bool onnx_runtime_available(std::string* error_out = nullptr);

// Best-effort resolved library path ("" when never resolved).
std::string onnx_runtime_library_path();

// Runtime version string ("1.29.0") or "" when unavailable. Never throws.
std::string onnx_runtime_version();

// One loaded, validated ONNX model. Move-only: the session owns ORT
// handles whose release order matters (session -> options -> env).
class OnnxRuntimeSession final : public InferenceSession {
public:
    // check_onnx_model_file() gates the file (regular .onnx, size cap) and
    // the returned binding's sha256 lands in model_info().
    static OnnxRuntimeSession open_file(
        const std::string& model_path,
        const OnnxSessionOptions& options = OnnxSessionOptions{});

    // For callers that already read and hashed the bytes (the model package
    // runtime), so bytes are hashed and loaded exactly once.
    static OnnxRuntimeSession open_bytes(
        const std::string& model_sha256, std::string model_bytes,
        const OnnxSessionOptions& options = OnnxSessionOptions{});

    OnnxRuntimeSession(OnnxRuntimeSession&&) noexcept;
    OnnxRuntimeSession& operator=(OnnxRuntimeSession&&) noexcept;
    ~OnnxRuntimeSession() override;

    OnnxRuntimeSession(const OnnxRuntimeSession&) = delete;
    OnnxRuntimeSession& operator=(const OnnxRuntimeSession&) = delete;

    const OnnxModelInfo& model_info() const;
    std::string device_mode() const override;
    SessionOutput run(const SessionBatch& batch) override;

private:
    struct Impl;
    explicit OnnxRuntimeSession(std::unique_ptr<Impl> impl);
    std::unique_ptr<Impl> impl_;
};

}  // namespace pwb::prediction
