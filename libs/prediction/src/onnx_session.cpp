// Native ONNX Runtime session — see include/pwb/prediction/onnx_session.hpp.
//
// The runtime library is loaded dynamically (no link-time dependency), so
// the library builds and all non-ORT tests run without an ONNX Runtime SDK.
// Vendored C API header: third_party/onnxruntime/onnxruntime_c_api.h (v1.17,
// MIT). ABI compatibility with newer runtimes is guaranteed by ONNX Runtime's
// append-only OrtApi contract; passing the runtime version API 17 works
// against any library >= 1.17 (verified against 1.29.0).

#include <pwb/prediction/onnx_session.hpp>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <mutex>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#include "onnxruntime_c_api.h"
#include "runtime_io.hpp"

namespace pwb::prediction {
namespace {

namespace fs = std::filesystem;

using OrtGetApiBaseFn = const OrtApiBase*(ORT_API_CALL*)(void)NO_EXCEPTION;

struct RuntimeCache {
    void* handle = nullptr;
    const OrtApi* api = nullptr;
    std::string path;
    std::string version;
    std::string error;
    bool loaded = false;
};

RuntimeCache& runtime_cache() {
    static RuntimeCache cache;
    return cache;
}

std::mutex& runtime_mutex() {
    static std::mutex mutex;
    return mutex;
}

#if defined(_WIN32)
std::wstring widen_utf8(const std::string& text) {
    if (text.empty()) return std::wstring();
    const int size = ::MultiByteToWideChar(CP_UTF8, 0, text.data(),
                                           static_cast<int>(text.size()),
                                           nullptr, 0);
    std::wstring out(static_cast<std::size_t>(size), L'\0');
    ::MultiByteToWideChar(CP_UTF8, 0, text.data(),
                          static_cast<int>(text.size()), out.data(), size);
    return out;
}

void* load_library(const std::string& path, std::string* error) {
    const std::wstring wide = widen_utf8(path);
    const bool has_separator =
        path.find('/') != std::string::npos
        || path.find('\\') != std::string::npos;
    HMODULE handle = nullptr;
    if (has_separator) {
        // Dependencies (onnxruntime_providers_shared.dll) live next to the
        // library: LOAD_WITH_ALTERED_SEARCH_PATH finds them.
        handle = ::LoadLibraryExW(wide.c_str(), nullptr,
                                  LOAD_WITH_ALTERED_SEARCH_PATH);
    } else {
        handle = ::LoadLibraryW(wide.c_str());
    }
    if (handle == nullptr) {
        const DWORD code = ::GetLastError();
        if (error != nullptr) {
            *error = "LoadLibrary failed (error " + std::to_string(code) + ")";
        }
    }
    return reinterpret_cast<void*>(handle);
}

void unload_library(void* handle) {
    if (handle != nullptr) {
        ::FreeLibrary(reinterpret_cast<HMODULE>(handle));
    }
}

void* library_symbol(void* handle, const char* name) {
    return reinterpret_cast<void*>(
        ::GetProcAddress(reinterpret_cast<HMODULE>(handle), name));
}
#else
void* load_library(const std::string& path, std::string* error) {
    void* handle = ::dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
    if (handle == nullptr && error != nullptr) {
        const char* message = ::dlerror();
        *error = message != nullptr ? message : "dlopen failed";
    }
    return handle;
}

void unload_library(void* handle) {
    if (handle != nullptr) {
        ::dlclose(handle);
    }
}

void* library_symbol(void* handle, const char* name) {
    return ::dlsym(handle, name);
}
#endif

std::string platform_default_library_name() {
#if defined(_WIN32)
    return "onnxruntime.dll";
#elif defined(__APPLE__)
    return "libonnxruntime.dylib";
#else
    return "libonnxruntime.so";
#endif
}

bool looks_like_path(const std::string& candidate) {
    return candidate.find('/') != std::string::npos
        || candidate.find('\\') != std::string::npos
        || fs::path(candidate).is_absolute();
}

std::vector<std::string> runtime_candidates(const std::string& explicit_path) {
    std::vector<std::string> candidates;
    const auto push = [&candidates](const std::string& value) {
        if (value.empty()) return;
        if (std::find(candidates.begin(), candidates.end(), value)
            == candidates.end()) {
            candidates.push_back(value);
        }
    };
    push(explicit_path);
    if (const char* env = std::getenv("PALEO_ONNXRUNTIME_LIBRARY");
        env != nullptr && *env != '\0') {
        push(env);
    }
#ifdef PWB_ONNXRUNTIME_LIBRARY
    push(PWB_ONNXRUNTIME_LIBRARY);
#endif
    push(platform_default_library_name());
    return candidates;
}

// Loads (once per process) the runtime library and resolves the OrtApi for
// the vendored header's API version. Throws TiledInferenceError with the
// full candidate list on failure.
const RuntimeCache& ensure_runtime(const std::string& explicit_path) {
    std::lock_guard<std::mutex> lock(runtime_mutex());
    RuntimeCache& cache = runtime_cache();
    if (cache.loaded) return cache;

    std::string failures;
    for (const std::string& candidate : runtime_candidates(explicit_path)) {
        std::string error;
        if (looks_like_path(candidate) && !fs::is_regular_file(candidate)) {
            failures += candidate + ": not found; ";
            continue;
        }
        void* handle = load_library(candidate, &error);
        if (handle == nullptr) {
            failures += candidate + ": " + error + "; ";
            continue;
        }
        auto get_api_base = reinterpret_cast<OrtGetApiBaseFn>(
            library_symbol(handle, "OrtGetApiBase"));
        if (get_api_base == nullptr) {
            failures += candidate + ": missing OrtGetApiBase; ";
            unload_library(handle);
            continue;
        }
        const OrtApiBase* base = get_api_base();
        if (base == nullptr || base->GetApi == nullptr) {
            failures += candidate + ": null OrtApiBase; ";
            unload_library(handle);
            continue;
        }
        const OrtApi* api = base->GetApi(ORT_API_VERSION);
        if (api == nullptr) {
            const char* version = base->GetVersionString != nullptr
                                      ? base->GetVersionString()
                                      : "unknown";
            failures += candidate + ": runtime version " + version
                        + " does not support API version "
                        + std::to_string(ORT_API_VERSION) + "; ";
            unload_library(handle);
            continue;
        }
        cache.handle = handle;
        cache.api = api;
        cache.path = candidate;
        cache.version = base->GetVersionString != nullptr
                            ? base->GetVersionString()
                            : "";
        cache.loaded = true;
        return cache;
    }
    cache.error = failures.empty() ? "no library candidates" : failures;
    throw TiledInferenceError(
        "ONNX Runtime native library unavailable (searched: "
        + cache.error + ")");
}

std::string status_message(const OrtApi* api, OrtStatus* status) {
    if (status == nullptr) return {};
    const char* message = api->GetErrorMessage(status);
    return message != nullptr ? std::string(message) : std::string();
}

void check_status(const OrtApi* api, OrtStatus* status,
                  const std::string& context) {
    if (status == nullptr) return;
    const std::string message = status_message(api, status);
    api->ReleaseStatus(status);
    throw TiledInferenceError("onnxruntime: " + context + ": " + message);
}

std::string element_type_name(ONNXTensorElementDataType type) {
    switch (type) {
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT: return "float32";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16: return "float16";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE: return "float64";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8: return "int8";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8: return "uint8";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT16: return "int16";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT16: return "uint16";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32: return "int32";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT32: return "uint32";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64: return "int64";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT64: return "uint64";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL: return "bool";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_STRING: return "string";
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_BFLOAT16: return "bfloat16";
        default: return "type(" + std::to_string(static_cast<int>(type)) + ")";
    }
}

bool is_convertible_to_float(ONNXTensorElementDataType type) {
    switch (type) {
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT16:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT16:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT32:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT64:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL:
            return true;
        default:
            return false;
    }
}

std::size_t element_size(ONNXTensorElementDataType type) {
    switch (type) {
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT: return 4;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16: return 2;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE: return 8;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8: return 1;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8: return 1;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT16: return 2;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT16: return 2;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32: return 4;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT32: return 4;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64: return 8;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT64: return 8;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL: return 1;
        default: return 0;
    }
}

template <typename T>
void copy_elements_as_float(const void* source, std::size_t count,
                            std::vector<float>& destination) {
    const T* typed = static_cast<const T*>(source);
    destination.resize(count);
    for (std::size_t i = 0; i < count; ++i) {
        destination[i] = static_cast<float>(typed[i]);
    }
}

void convert_output_to_float(ONNXTensorElementDataType type, const void* source,
                             std::size_t count,
                             std::vector<float>& destination) {
    switch (type) {
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT:
            destination.resize(count);
            std::memcpy(destination.data(), source, count * sizeof(float));
            return;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16: {
            const std::uint16_t* typed =
                static_cast<const std::uint16_t*>(source);
            destination.resize(count);
            for (std::size_t i = 0; i < count; ++i) {
                destination[i] = detail::half_bits_to_float(typed[i]);
            }
            return;
        }
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE:
            copy_elements_as_float<double>(source, count, destination);
            return;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8:
            copy_elements_as_float<std::int8_t>(source, count, destination);
            return;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8:
            copy_elements_as_float<std::uint8_t>(source, count, destination);
            return;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT16:
            copy_elements_as_float<std::int16_t>(source, count, destination);
            return;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT16:
            copy_elements_as_float<std::uint16_t>(source, count, destination);
            return;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32:
            copy_elements_as_float<std::int32_t>(source, count, destination);
            return;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT32:
            copy_elements_as_float<std::uint32_t>(source, count, destination);
            return;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64:
            copy_elements_as_float<std::int64_t>(source, count, destination);
            return;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT64:
            copy_elements_as_float<std::uint64_t>(source, count, destination);
            return;
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL:
            copy_elements_as_float<bool>(source, count, destination);
            return;
        default:
            throw TiledInferenceError(
                "onnxruntime: model output element type "
                + element_type_name(type)
                + " cannot be read as probabilities (expected float32, "
                  "float16, float64 or an integer type)");
    }
}

std::string get_tensor_name(const OrtApi* api, const OrtSession* session,
                            std::size_t index, bool input) {
    OrtAllocator* allocator = nullptr;
    check_status(api, api->GetAllocatorWithDefaultOptions(&allocator),
                 "GetAllocatorWithDefaultOptions");
    char* raw = nullptr;
    OrtStatus* status = input
                            ? api->SessionGetInputName(session, index, allocator,
                                                       &raw)
                            : api->SessionGetOutputName(session, index,
                                                        allocator, &raw);
    check_status(api, status, input ? "SessionGetInputName"
                                    : "SessionGetOutputName");
    std::string name = raw != nullptr ? std::string(raw) : std::string();
    if (raw != nullptr && allocator != nullptr && allocator->Free != nullptr) {
        allocator->Free(allocator, raw);
    }
    return name;
}

OnnxTensorInfo read_tensor_info(const OrtApi* api, const OrtSession* session,
                                std::size_t index, bool input) {
    OrtTypeInfo* type_info = nullptr;
    OrtStatus* status =
        input ? api->SessionGetInputTypeInfo(session, index, &type_info)
              : api->SessionGetOutputTypeInfo(session, index, &type_info);
    check_status(api, status, input ? "SessionGetInputTypeInfo"
                                    : "SessionGetOutputTypeInfo");
    if (type_info == nullptr) {
        throw TiledInferenceError("onnxruntime: null type info for "
                                  + std::string(input ? "input" : "output")
                                  + " " + std::to_string(index));
    }
    ONNXType onnx_type = ONNX_TYPE_UNKNOWN;
    api->GetOnnxTypeFromTypeInfo(type_info, &onnx_type);
    if (onnx_type != ONNX_TYPE_TENSOR) {
        api->ReleaseTypeInfo(type_info);
        throw TiledInferenceError(
            "onnxruntime: model " + std::string(input ? "input" : "output")
            + " " + std::to_string(index)
            + " is not a tensor; tiled seismic expects tensor ports");
    }
    const OrtTensorTypeAndShapeInfo* shape_info = nullptr;
    const OrtStatus* cast_status =
        api->CastTypeInfoToTensorInfo(type_info, &shape_info);
    if (cast_status != nullptr || shape_info == nullptr) {
        api->ReleaseTypeInfo(type_info);
        throw TiledInferenceError(
            "onnxruntime: model " + std::string(input ? "input" : "output")
            + " " + std::to_string(index) + " has no tensor shape info");
    }
    OnnxTensorInfo info;
    info.name = get_tensor_name(api, session, index, input);
    ONNXTensorElementDataType element_type =
        ONNX_TENSOR_ELEMENT_DATA_TYPE_UNDEFINED;
    api->GetTensorElementType(shape_info, &element_type);
    info.element_type = element_type_name(element_type);
    std::size_t rank = 0;
    api->GetDimensionsCount(shape_info, &rank);
    std::vector<std::int64_t> dims(rank, -1);
    if (rank > 0) {
        api->GetDimensions(shape_info, dims.data(), rank);
    }
    info.shape.assign(dims.begin(), dims.end());
    api->ReleaseTypeInfo(type_info);
    return info;
}

ONNXTensorElementDataType tensor_element_type(const OrtApi* api,
                                              const OrtSession* session,
                                              std::size_t index, bool input) {
    OrtTypeInfo* type_info = nullptr;
    OrtStatus* status =
        input ? api->SessionGetInputTypeInfo(session, index, &type_info)
              : api->SessionGetOutputTypeInfo(session, index, &type_info);
    check_status(api, status, "SessionGetTypeInfo");
    const OrtTensorTypeAndShapeInfo* shape_info = nullptr;
    api->CastTypeInfoToTensorInfo(type_info, &shape_info);
    ONNXTensorElementDataType element_type =
        ONNX_TENSOR_ELEMENT_DATA_TYPE_UNDEFINED;
    if (shape_info != nullptr) {
        api->GetTensorElementType(shape_info, &element_type);
    }
    api->ReleaseTypeInfo(type_info);
    return element_type;
}

std::string shape_to_string(const std::vector<long long>& shape) {
    std::string out = "(";
    for (std::size_t i = 0; i < shape.size(); ++i) {
        if (i != 0) out += ", ";
        out += std::to_string(shape[i]);
    }
    out += ")";
    return out;
}

std::size_t checked_element_count(const std::vector<std::int64_t>& dims,
                                  const std::string& what) {
    unsigned long long elements = 1;
    for (const std::int64_t dim : dims) {
        if (dim < 0) {
            throw TiledInferenceError(
                "onnxruntime: model " + what
                + " has a dynamic dimension at run time: "
                + shape_to_string(std::vector<long long>(dims.begin(),
                                                         dims.end())));
        }
        const unsigned long long value = static_cast<unsigned long long>(dim);
        if (value == 0) return 0;
        if (elements > std::numeric_limits<unsigned long long>::max() / value) {
            throw TiledInferenceError(
                "onnxruntime: model " + what + " element count overflows");
        }
        elements *= value;
    }
    return static_cast<std::size_t>(elements);
}

}  // namespace

Json OnnxTensorInfo::to_json() const {
    Json shape_json = Json::array();
    for (const long long dim : shape) shape_json.push_back(dim);
    Json out = Json::object();
    out["name"] = name;
    out["element_type"] = element_type;
    out["shape"] = std::move(shape_json);
    return out;
}

Json OnnxModelInfo::to_json() const {
    Json out = Json::object();
    out["runtime_library"] = runtime_library;
    out["runtime_version"] = runtime_version;
    out["model_sha256"] = model_sha256;
    out["model_bytes"] = model_bytes;
    out["device_mode"] = device_mode;
    out["provider"] = provider;
    out["input_count"] = input_count;
    out["output_count"] = output_count;
    out["input"] = input.to_json();
    out["output"] = output.to_json();
    out["gpu_requested"] = gpu_requested;
    return out;
}

bool onnx_runtime_available(std::string* error_out) {
    try {
        ensure_runtime("");
        return true;
    } catch (const std::exception& exc) {
        if (error_out != nullptr) *error_out = exc.what();
        return false;
    }
}

std::string onnx_runtime_library_path() {
    try {
        return ensure_runtime("").path;
    } catch (const std::exception&) {
        return {};
    }
}

std::string onnx_runtime_version() {
    try {
        return ensure_runtime("").version;
    } catch (const std::exception&) {
        return {};
    }
}

struct OnnxRuntimeSession::Impl {
    const OrtApi* api = nullptr;
    OrtEnv* env = nullptr;
    OrtSession* session = nullptr;
    OrtMemoryInfo* memory_info = nullptr;
    ONNXTensorElementDataType input_element_type =
        ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT;
    ONNXTensorElementDataType output_element_type =
        ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT;
    std::mutex run_mutex;
    OnnxModelInfo info;

    ~Impl() {
        if (api == nullptr) return;
        if (memory_info != nullptr) api->ReleaseMemoryInfo(memory_info);
        if (session != nullptr) api->ReleaseSession(session);
        if (env != nullptr) api->ReleaseEnv(env);
    }
};

OnnxRuntimeSession::OnnxRuntimeSession(std::unique_ptr<Impl> impl)
    : impl_(std::move(impl)) {}

OnnxRuntimeSession::OnnxRuntimeSession(OnnxRuntimeSession&&) noexcept = default;
OnnxRuntimeSession& OnnxRuntimeSession::operator=(
    OnnxRuntimeSession&&) noexcept = default;
OnnxRuntimeSession::~OnnxRuntimeSession() = default;

const OnnxModelInfo& OnnxRuntimeSession::model_info() const {
    return impl_->info;
}

std::string OnnxRuntimeSession::device_mode() const {
    return impl_->info.device_mode;
}

OnnxRuntimeSession OnnxRuntimeSession::open_file(
    const std::string& model_path, const OnnxSessionOptions& options) {
    const ModelBinding binding = check_onnx_model_file(model_path);
    std::string error;
    std::optional<std::string> bytes =
        detail::read_file_bytes(fs::path(model_path), &error);
    if (!bytes.has_value()) {
        throw TiledInferenceError("ONNX model " + model_path
                                  + " could not be read: " + error);
    }
    if (static_cast<long long>(bytes->size()) != binding.model_bytes) {
        throw TiledInferenceError(
            "ONNX model " + model_path + " changed while loading (expected "
            + std::to_string(binding.model_bytes) + " bytes, read "
            + std::to_string(bytes->size()) + ")");
    }
    return open_bytes(binding.model_sha256, std::move(*bytes), options);
}

OnnxRuntimeSession OnnxRuntimeSession::open_bytes(
    const std::string& model_sha256, std::string model_bytes,
    const OnnxSessionOptions& options) {
    const RuntimeCache& runtime =
        ensure_runtime(options.library_path);  // throws when unavailable
    const OrtApi* api = runtime.api;

    auto impl = std::make_unique<Impl>();
    impl->api = api;
    impl->info.runtime_library = runtime.path;
    impl->info.runtime_version = runtime.version;
    impl->info.model_sha256 = model_sha256;
    impl->info.model_bytes = static_cast<long long>(model_bytes.size());
    impl->info.gpu_requested = options.prefer_gpu;

    if (model_bytes.empty()) {
        throw TiledInferenceError(
            "ONNX model bytes are empty; refusing to create a session");
    }

    check_status(api,
                 api->CreateEnv(ORT_LOGGING_LEVEL_WARNING,
                                "paleo_workbench_prediction", &impl->env),
                 "CreateEnv");

    const auto make_options = [&]() -> OrtSessionOptions* {
        OrtSessionOptions* session_options = nullptr;
        check_status(api, api->CreateSessionOptions(&session_options),
                     "CreateSessionOptions");
        try {
            if (options.intra_op_threads > 0) {
                check_status(
                    api,
                    api->SetIntraOpNumThreads(session_options,
                                              options.intra_op_threads),
                    "SetIntraOpNumThreads");
            }
            if (options.inter_op_threads > 0) {
                check_status(
                    api,
                    api->SetInterOpNumThreads(session_options,
                                              options.inter_op_threads),
                    "SetInterOpNumThreads");
            }
            check_status(
                api,
                api->SetSessionGraphOptimizationLevel(session_options,
                                                      ORT_ENABLE_ALL),
                "SetSessionGraphOptimizationLevel");
            check_status(api,
                         api->SetSessionExecutionMode(session_options,
                                                      ORT_SEQUENTIAL),
                         "SetSessionExecutionMode");
        } catch (...) {
            api->ReleaseSessionOptions(session_options);
            throw;
        }
        return session_options;
    };

    // GPU is optional: CUDA is appended only when requested, and any failure
    // falls back to the CPU provider with an honest "cpu" report (mirrors the
    // Python provider's provider list + CPU retry).
    bool gpu_applied = false;
    OrtSessionOptions* session_options = make_options();
    if (options.prefer_gpu) {
        OrtCUDAProviderOptions cuda_options;
        std::memset(&cuda_options, 0, sizeof cuda_options);
        cuda_options.device_id = 0;
        OrtStatus* cuda_status =
            api->SessionOptionsAppendExecutionProvider_CUDA(session_options,
                                                            &cuda_options);
        if (cuda_status == nullptr) {
            gpu_applied = true;
        } else {
            api->ReleaseStatus(cuda_status);
        }
    }

    OrtStatus* create_status = api->CreateSessionFromArray(
        impl->env, model_bytes.data(), model_bytes.size(), session_options,
        &impl->session);
    if (create_status != nullptr && gpu_applied) {
        // CUDA was accepted at the options level but the session could not
        // be created (missing provider binaries at run time): retry CPU-only.
        api->ReleaseStatus(create_status);
        api->ReleaseSessionOptions(session_options);
        gpu_applied = false;
        session_options = make_options();
        create_status = api->CreateSessionFromArray(
            impl->env, model_bytes.data(), model_bytes.size(), session_options,
            &impl->session);
    }
    api->ReleaseSessionOptions(session_options);
    check_status(api, create_status, "CreateSessionFromArray");
    if (impl->session == nullptr) {
        throw TiledInferenceError(
            "onnxruntime: CreateSessionFromArray returned a null session");
    }
    impl->info.device_mode = gpu_applied ? "cuda" : "cpu";
    impl->info.provider =
        gpu_applied ? "CUDAExecutionProvider" : "CPUExecutionProvider";

    std::size_t input_count = 0;
    std::size_t output_count = 0;
    check_status(api, api->SessionGetInputCount(impl->session, &input_count),
                 "SessionGetInputCount");
    check_status(api,
                 api->SessionGetOutputCount(impl->session, &output_count),
                 "SessionGetOutputCount");
    if (input_count == 0 || output_count == 0) {
        throw TiledInferenceError(
            "onnxruntime: model must declare at least one input and one "
            "output (got "
            + std::to_string(input_count) + " input(s), "
            + std::to_string(output_count) + " output(s))");
    }
    impl->info.input_count = input_count;
    impl->info.output_count = output_count;
    impl->info.input = read_tensor_info(api, impl->session, 0, true);
    impl->info.output = read_tensor_info(api, impl->session, 0, false);

    ONNXTensorElementDataType input_type =
        tensor_element_type(api, impl->session, 0, true);
    switch (input_type) {
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16:
        case ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE:
            break;
        default:
            throw TiledInferenceError(
                "onnxruntime: model input element type "
                + element_type_name(input_type)
                + " is not supported; tiled seismic feeds float32 and "
                  "converts to float16/float64");
    }
    // Keep the element types on the impl for run-time conversion.
    impl->input_element_type = input_type;
    impl->output_element_type =
        tensor_element_type(api, impl->session, 0, false);
    if (!is_convertible_to_float(impl->output_element_type)) {
        throw TiledInferenceError(
            "onnxruntime: model output element type "
            + element_type_name(impl->output_element_type)
            + " cannot be read as probabilities (expected float32, float16, "
              "float64 or an integer type)");
    }

    check_status(api,
                 api->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault,
                                          &impl->memory_info),
                 "CreateCpuMemoryInfo");
    return OnnxRuntimeSession(std::move(impl));
}

SessionOutput OnnxRuntimeSession::run(const SessionBatch& batch) {
    Impl& state = *impl_;
    const OrtApi* api = state.api;

    if (batch.n < 1) {
        throw TiledInferenceError("onnxruntime: session batch must be >= 1");
    }
    if (batch.d <= 0 || batch.h <= 0 || batch.w <= 0) {
        throw TiledInferenceError(
            "onnxruntime: session batch tile dimensions must be positive");
    }
    const std::size_t expected =
        static_cast<std::size_t>(batch.n)
        * static_cast<std::size_t>(batch.d)
        * static_cast<std::size_t>(batch.h)
        * static_cast<std::size_t>(batch.w);
    if (batch.data.size() != expected) {
        throw TiledInferenceError(
            "onnxruntime: session batch data size "
            + std::to_string(batch.data.size())
            + " does not match (N,D,H,W) = ("
            + std::to_string(batch.n) + ", " + std::to_string(batch.d) + ", "
            + std::to_string(batch.h) + ", " + std::to_string(batch.w)
            + ")");
    }

    std::lock_guard<std::mutex> lock(state.run_mutex);

    const auto& input_shape = state.info.input.shape;
    if (input_shape.size() != 5) {
        throw TiledInferenceError(
            "onnxruntime: model input rank="
            + std::to_string(input_shape.size())
            + "; tiled seismic expects (N,1,D,H,W)");
    }
    const long long expected_dims[5] = {batch.n, 1, batch.d, batch.h, batch.w};
    for (int axis = 0; axis < 5; ++axis) {
        const long long model_dim = input_shape[static_cast<std::size_t>(axis)];
        if (model_dim >= 0 && model_dim != expected_dims[axis]) {
            throw TiledInferenceError(
                "onnxruntime: batch shape "
                + shape_to_string({batch.n, 1, batch.d, batch.h, batch.w})
                + " does not match the model input shape "
                + shape_to_string(input_shape));
        }
    }

    std::vector<std::uint16_t> half_input;
    std::vector<double> double_input;
    const void* input_data = batch.data.data();
    if (state.input_element_type == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16) {
        half_input.resize(batch.data.size());
        for (std::size_t i = 0; i < batch.data.size(); ++i) {
            half_input[i] = detail::float_to_half_bits(batch.data[i]);
        }
        input_data = half_input.data();
    } else if (state.input_element_type
               == ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE) {
        double_input.assign(batch.data.begin(), batch.data.end());
        input_data = double_input.data();
    }

    const std::int64_t tensor_shape[5] = {batch.n, 1, batch.d, batch.h,
                                          batch.w};
    OrtValue* input_value = nullptr;
    check_status(
        api,
        api->CreateTensorWithDataAsOrtValue(
            state.memory_info, const_cast<void*>(input_data),
            batch.data.size() * sizeof(float), tensor_shape, 5,
            state.input_element_type, &input_value),
        "CreateTensorWithDataAsOrtValue");

    const char* input_names[] = {state.info.input.name.c_str()};
    const char* output_names[] = {state.info.output.name.c_str()};
    const OrtValue* input_values[1] = {input_value};
    OrtValue* outputs[1] = {nullptr};
    OrtStatus* run_status =
        api->Run(state.session, nullptr, input_names, input_values, 1,
                 output_names, 1, outputs);
    api->ReleaseValue(input_value);
    check_status(api, run_status, "Run");
    if (outputs[0] == nullptr) {
        throw TiledInferenceError("onnxruntime: Run returned a null output");
    }
    OrtValue* output_value = outputs[0];

    OrtTensorTypeAndShapeInfo* shape_info = nullptr;
    check_status(api,
                 api->GetTensorTypeAndShape(output_value, &shape_info),
                 "GetTensorTypeAndShape");
    std::size_t rank = 0;
    check_status(api, api->GetDimensionsCount(shape_info, &rank),
                 "GetDimensionsCount");
    std::vector<std::int64_t> dims(rank, 0);
    if (rank > 0) {
        check_status(api, api->GetDimensions(shape_info, dims.data(), rank),
                     "GetDimensions");
    }
    ONNXTensorElementDataType output_type =
        ONNX_TENSOR_ELEMENT_DATA_TYPE_UNDEFINED;
    check_status(api, api->GetTensorElementType(shape_info, &output_type),
                 "GetTensorElementType");
    api->ReleaseTensorTypeAndShapeInfo(shape_info);
    if (!is_convertible_to_float(output_type)) {
        api->ReleaseValue(output_value);
        throw TiledInferenceError(
            "onnxruntime: model output element type "
            + element_type_name(output_type)
            + " cannot be read as probabilities");
    }

    const std::size_t elements =
        checked_element_count(dims, "output");
    const std::size_t output_element_bytes = element_size(output_type);
    if (output_element_bytes == 0
        || elements
               > static_cast<std::size_t>(kMaxOnnxTensorBytes)
                     / output_element_bytes) {
        api->ReleaseValue(output_value);
        throw TiledInferenceError(
            "onnxruntime: model output needs more than "
            + std::to_string(kMaxOnnxTensorBytes)
            + " bytes, above the tensor cap; refusing to allocate");
    }

    void* raw_output = nullptr;
    check_status(api, api->GetTensorMutableData(output_value, &raw_output),
                 "GetTensorMutableData");

    SessionOutput out;
    out.ndim = static_cast<int>(rank);
    for (std::size_t axis = 0; axis < rank && axis < 5; ++axis) {
        const std::int64_t dim = dims[axis];
        if (dim < 0
            || dim > static_cast<std::int64_t>(
                         std::numeric_limits<int>::max())) {
            api->ReleaseValue(output_value);
            throw TiledInferenceError(
                "onnxruntime: model output dimension out of range");
        }
        const int value = static_cast<int>(dim);
        switch (axis) {
            case 0: out.n = value; break;
            case 1: out.c = value; break;
            case 2: out.d = value; break;
            case 3: out.h = value; break;
            default: out.w = value; break;
        }
    }
    convert_output_to_float(output_type, raw_output, elements, out.data);
    api->ReleaseValue(output_value);
    return out;
}

}  // namespace pwb::prediction
