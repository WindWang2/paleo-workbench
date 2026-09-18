// prediction.tiled_stub — C++ tiled-inference core (libs/prediction) vs the
// frozen Python oracle. The oracle was produced by running the REAL
// paleo_workbench.prediction.tiled_onnx.run_tiled_inference with stub
// sessions standing in at the _make_session seam (see
// tools/oracle/generate_tiled_onnx_fixtures.py); the stub operators below
// mirror that generator exactly — scalar float32 ops in the same fixed
// order, compiled with -ffp-contract=off so results are bit-identical up to
// the exp() implementation (absorbed by the fp16 tolerance / argmax margins).

#include <pwb/domain/json.hpp>
#include <pwb/prediction/tiled_inference.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <limits>
#include <map>
#include <sstream>
#include <string>
#include <system_error>
#include <vector>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;
using pwb::prediction::SessionBatch;
using pwb::prediction::SessionOutput;
using pwb::prediction::Tile3;
using pwb::prediction::TiledInferenceError;
using pwb::prediction::TiledRunOptions;
using pwb::prediction::TiledRunStats;
using pwb::prediction::VolumeReader;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

// ---------------------------------------------------------------------------
// stub operators — mirror stub_run/stub_logits/stub_conv in the generator
// ---------------------------------------------------------------------------

std::vector<float> stub_conv_axis(const std::vector<float>& src, int n0,
                                  int n1, int n2, int axis) {
    std::vector<float> out(src.size());
    const int dims[3] = {n0, n1, n2};
    for (int i0 = 0; i0 < n0; ++i0) {
        for (int i1 = 0; i1 < n1; ++i1) {
            for (int i2 = 0; i2 < n2; ++i2) {
                const int c[3] = {i0, i1, i2};
                const std::size_t idx =
                    (static_cast<std::size_t>(i0) * n1 + i1) * n2 + i2;
                const float center = src[idx];
                float left = 0.0f;
                float right = 0.0f;
                if (c[axis] > 0) {
                    int l[3] = {i0, i1, i2};
                    l[axis] -= 1;
                    left = src[(static_cast<std::size_t>(l[0]) * n1 + l[1]) * n2
                               + l[2]];
                }
                if (c[axis] < dims[axis] - 1) {
                    int r[3] = {i0, i1, i2};
                    r[axis] += 1;
                    right = src[(static_cast<std::size_t>(r[0]) * n1 + r[1]) * n2
                                + r[2]];
                }
                const float acc = 0.25f * left + 0.5f * center;
                out[idx] = acc + 0.25f * right;
            }
        }
    }
    return out;
}

std::vector<float> stub_conv(const std::vector<float>& block, int d, int h,
                             int w) {
    std::vector<float> out = stub_conv_axis(block, d, h, w, 0);
    out = stub_conv_axis(out, d, h, w, 1);
    out = stub_conv_axis(out, d, h, w, 2);
    return out;
}

int stub_channels(const std::string& kind) {
    if (kind == "sign" || kind == "conv2" || kind == "oom_conv2") return 2;
    if (kind == "conv3") return 3;
    return 1;  // sigmoid1
}

SessionOutput stub_run(const std::string& kind, const SessionBatch& batch) {
    // Malformed-output kinds exercising the C++-only honest guards (D15/D18).
    if (kind == "wrong_d" || kind == "short_n" || kind == "zero_c"
        || kind == "short_data") {
        SessionOutput out;
        out.ndim = 5;
        out.n = kind == "short_n" ? batch.n - 1 : batch.n;
        out.c = kind == "zero_c" ? 0 : 2;
        out.d = kind == "wrong_d" ? batch.d - 1 : batch.d;
        out.h = batch.h;
        out.w = batch.w;
        if (kind != "short_data") {
            out.data.resize(static_cast<std::size_t>(out.n) * out.c
                            * out.d * out.h * out.w);
        }
        return out;
    }
    SessionOutput out;
    if (kind == "oom_conv2" && batch.n > 1) {
        throw std::runtime_error("CUDA error: out of memory");
    }
    if (kind == "ndim4" || kind == "ndim3") {
        out.ndim = kind == "ndim4" ? 4 : 3;
        out.n = batch.n;
        out.c = 2;
        out.d = batch.d;
        out.h = batch.h;
        out.w = 0;
        return out;
    }
    out.ndim = 5;
    out.n = batch.n;
    out.d = batch.d;
    out.h = batch.h;
    out.w = batch.w;
    out.c = stub_channels(kind);
    const std::size_t voxels = static_cast<std::size_t>(batch.d) * batch.h
                             * batch.w;
    out.data.resize(static_cast<std::size_t>(batch.n) * out.c * voxels);
    std::vector<float> block(voxels);
    for (int n = 0; n < batch.n; ++n) {
        std::memcpy(block.data(),
                    batch.data.data() + static_cast<std::size_t>(n) * voxels,
                    voxels * sizeof(float));
        float* plane =
            out.data.data() + static_cast<std::size_t>(n) * out.c * voxels;
        if (kind == "sign") {
            std::memcpy(plane, block.data(), voxels * sizeof(float));
            for (std::size_t i = 0; i < voxels; ++i) plane[voxels + i] = -block[i];
        } else {
            const std::vector<float> c = stub_conv(block, batch.d, batch.h, batch.w);
            std::memcpy(plane, c.data(), voxels * sizeof(float));
            if (kind == "conv2" || kind == "oom_conv2") {
                for (std::size_t i = 0; i < voxels; ++i) plane[voxels + i] = -c[i];
            } else if (kind == "conv3") {
                for (std::size_t i = 0; i < voxels; ++i) {
                    plane[voxels + i] = 2.0f * c[i] - 1.0f;
                    plane[2 * voxels + i] = 4.0f * c[i] - 6.0f;
                }
            }  // sigmoid1: single channel, nothing more
        }
    }
    return out;
}

class StubSession final : public pwb::prediction::InferenceSession {
public:
    explicit StubSession(std::string kind) : kind_(std::move(kind)) {}

    std::string device_mode() const override { return "cpu"; }

    SessionOutput run(const SessionBatch& batch) override {
        return stub_run(kind_, batch);
    }

private:
    std::string kind_;
};

class StubReader final : public VolumeReader {
public:
    StubReader(Tile3 shape, std::vector<float> data)
        : shape_(shape), data_(std::move(data)) {}

    Tile3 shape() const override { return shape_; }

    std::vector<float> read_voxel_window(int s0, int e0, int s1, int e1,
                                         int s2, int e2) const override {
        std::vector<float> out(static_cast<std::size_t>(e0 - s0) * (e1 - s1)
                               * (e2 - s2));
        for (int a0 = s0; a0 < e0; ++a0) {
            for (int a1 = s1; a1 < e1; ++a1) {
                for (int a2 = s2; a2 < e2; ++a2) {
                    const std::size_t src =
                        (static_cast<std::size_t>(a0) * shape_[1]
                         + static_cast<std::size_t>(a1))
                            * shape_[2]
                        + static_cast<std::size_t>(a2);
                    const std::size_t dst =
                        (static_cast<std::size_t>(a0 - s0) * (e1 - s1)
                         + static_cast<std::size_t>(a1 - s1))
                            * (e2 - s2)
                        + static_cast<std::size_t>(a2 - s2);
                    out[dst] = data_[src];
                }
            }
        }
        return out;
    }

private:
    Tile3 shape_;
    std::vector<float> data_;
};

// ---------------------------------------------------------------------------
// float16 helpers
// ---------------------------------------------------------------------------

// Exact binary16 → float32 widening (for decoding oracle-frozen values).
float half_to_float(std::uint16_t h) {
    const std::uint32_t sign = static_cast<std::uint32_t>(h & 0x8000u) << 16;
    const std::uint32_t exp = (h >> 10) & 0x1fu;
    const std::uint32_t mant = h & 0x3ffu;
    std::uint32_t bits;
    if (exp == 0) {
        if (mant == 0) {
            bits = sign;  // ±0
        } else {
            std::uint32_t m = mant;
            int e = -1;
            while ((m & 0x400u) == 0u) {
                m <<= 1;
                ++e;
            }
            m &= 0x3ffu;
            bits = sign | (static_cast<std::uint32_t>(127 - 15 - e) << 23)
                 | (m << 13);
        }
    } else if (exp == 0x1fu) {
        bits = sign | 0x7f800000u | (mant << 13);
    } else {
        bits = sign | ((exp + 127 - 15) << 23) | (mant << 13);
    }
    float value = 0.0f;
    std::memcpy(&value, &bits, sizeof value);
    return value;
}

// One float16 ULP at *v* (binade-aware; subnormal step 2^-24 below 2^-14).
// The C++ pipeline may sit ±1 fp16 bit away from the frozen value when a
// float32 prob straddles a rounding boundary (exp() implementation
// differences).
double fp16_ulp(double v) {
    const double a = std::fabs(v);
    if (a < 6.103515625e-05) return 5.9604644775390625e-08;  // 2^-24
    const double e = std::floor(std::log2(a));
    return std::pow(2.0, e - 10.0);
}

// POSIX setenv/unsetenv (PALEO_ONNX_MAX_MODEL_BYTES cap case).
void set_env_var(const char* name, const char* value) {
#if defined(_WIN32)
    std::string kv = std::string(name) + "=" + value;
    _putenv(kv.c_str());
#else
    setenv(name, value, 1);
#endif
}

void unset_env_var(const char* name) {
#if defined(_WIN32)
    _putenv((std::string(name) + "=").c_str());
#else
    unsetenv(name);
#endif
}

bool same_prob(double want, const Json& want_json, std::uint16_t got_bits) {
    if (want_json.is_string()) {  // "NaN" / "Inf" / "-Inf"
        const std::string s = want_json.get<std::string>();
        const bool got_nan = (got_bits & 0x7c00u) == 0x7c00u
                          && (got_bits & 0x03ffu) != 0u;
        if (s == "NaN") return got_nan;
        if (s == "Inf") return got_bits == 0x7c00u;
        if (s == "-Inf") return got_bits == 0xfc00u;
        return false;
    }
    const float got = half_to_float(got_bits);
    if (std::isnan(static_cast<double>(got))) return false;
    const double diff = std::fabs(static_cast<double>(got) - want);
    return diff <= fp16_ulp(want) + 1e-12;
}

// ---------------------------------------------------------------------------
// fixture helpers
// ---------------------------------------------------------------------------

std::string replace_all(std::string text, const std::string& from,
                        const std::string& to) {
    std::size_t pos = 0;
    while ((pos = text.find(from, pos)) != std::string::npos) {
        text.replace(pos, from.size(), to);
        pos += to.size();
    }
    return text;
}

std::vector<std::string> list_done_markers(const fs::path& work) {
    std::vector<std::string> names;
    for (const auto& entry : fs::directory_iterator(work / "tiles.done")) {
        const std::string name = entry.path().filename().string();
        if (name.rfind("t_", 0) == 0) names.push_back(name);
    }
    std::sort(names.begin(), names.end());
    return names;
}

struct RunBuffers {
    std::vector<std::uint8_t> classmap;
    std::vector<std::uint16_t> probmap;
};

}  // namespace

int main() {
    std::ifstream stream(PWB_TILED_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open fixture\n");
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());
    const Json& meta = oracle["meta"];

    // float16 decoder sanity anchors (guard the comparison primitive).
    check(half_to_float(0x0000u) == 0.0f, "f16 0x0000");
    check(half_to_float(0x3c00u) == 1.0f, "f16 0x3c00");
    check(half_to_float(0xbc00u) == -1.0f, "f16 0xbc00");
    check(half_to_float(0x0400u) == 6.103515625e-05f, "f16 0x0400");
    check(half_to_float(0x03ffu) == 6.097555160522461e-05f,
          "f16 max subnormal");
    check(std::isinf(half_to_float(0x7c00u)), "f16 inf");
    check(std::isnan(half_to_float(0x7e00u)), "f16 nan");

    // -- fp16 conversion table (numpy bit-exact) ----------------------------
    // Frozen np.float16 bit patterns for crafted float32 inputs: binade
    // boundaries, RNE ties both parities, the subnormal band, overflow
    // edges, ±0/±Inf and NaN payloads (including the truncation-to-zero
    // payload numpy keeps as NaN). Local harness section; not a run oracle.
    std::size_t fp16_checked = 0;
    for (const auto& e : oracle["fp16_table"]) {
        const std::uint32_t in_bits =
            static_cast<std::uint32_t>(e["bits"].get<long long>());
        float x = 0.0f;
        std::memcpy(&x, &in_bits, sizeof x);
        const auto got = pwb::prediction::detail::float_to_half_bits(x);
        const auto want = static_cast<std::uint16_t>(e["h"].get<int>());
        if (got != want) {
            char what[96];
            std::snprintf(what, sizeof what,
                          "fp16(%08x) = %04x, want %04x", in_bits, got,
                          want);
            check(false, what);
        }
        ++fp16_checked;
    }
    check(fp16_checked >= 200, "fp16 table size");
    std::printf("fp16 table: %zu bit-exact conversions\n", fp16_checked);

    // Temp workspace mirroring the generator's layout (<WORK> in frozen
    // error texts maps to this directory).
    const std::uint64_t stamp = static_cast<std::uint64_t>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    const fs::path root = fs::temp_directory_path()
                        / ("conv13_tiled_stub_" + std::to_string(stamp));
    fs::create_directories(root);
    const std::string work_token = root.string();

    const std::string model_content = meta["model_content"].get<std::string>();
    const std::string model_path = (root / "stub-model.onnx").string();
    {
        std::ofstream f(model_path, std::ios::binary);
        f << model_content;
    }
    {
        std::ofstream f(root / "stub.txt", std::ios::binary);
        f << model_content;
    }
    {
        std::ofstream f(root / "empty.onnx", std::ios::binary);
    }
    {
        std::ofstream f(root / "big.onnx", std::ios::binary);
        f << "xxxxxxxxxxxxxxxx";  // 16 bytes
    }

    // -- tile_starts --------------------------------------------------------
    for (const auto& c : oracle["tile_starts"]) {
        const int n = c["n"].get<int>();
        const int tile = c["tile"].get<int>();
        const int overlap = c["overlap"].get<int>();
        const std::string id = "tile_starts(" + std::to_string(n) + ","
                               + std::to_string(tile) + ","
                               + std::to_string(overlap) + ")";
        if (c.contains("error")) {
            bool threw = false;
            try {
                pwb::prediction::tile_starts(n, tile, overlap);
            } catch (const TiledInferenceError& exc) {
                threw = true;
                check(exc.what() == c["error"].get<std::string>(),
                      id + " error text");
            }
            check(threw, id + " throws");
        } else {
            const auto starts = pwb::prediction::tile_starts(n, tile, overlap);
            const auto& want = c["starts"];
            check(starts.size() == want.size(), id + " count");
            for (std::size_t i = 0; i < starts.size() && i < want.size(); ++i) {
                check(starts[i] == want[i].get<int>(), id + " start[" + std::to_string(i) + "]");
            }
        }
    }

    // -- authoritative ranges ------------------------------------------------
    for (const auto& c : oracle["authoritative"]) {
        const int n = c["n"].get<int>();
        const int tile = c["tile"].get<int>();
        const int overlap = c["overlap"].get<int>();
        const auto starts = pwb::prediction::tile_starts(n, tile, overlap);
        const int stride = tile - overlap;
        const std::string id = "auth(" + std::to_string(n) + ","
                               + std::to_string(tile) + ","
                               + std::to_string(overlap) + ")";
        check(static_cast<int>(starts.size())
                  == static_cast<int>(c["ranges"].size()),
              id + " range count");
        for (std::size_t i = 0; i < starts.size() && i < c["ranges"].size();
             ++i) {
            const auto range = pwb::prediction::authoritative_range(
                i, starts, stride, overlap, n);
            check(range.first == c["ranges"][i][0].get<int>()
                      && range.second == c["ranges"][i][1].get<int>(),
                  id + " range[" + std::to_string(i) + "]");
        }
    }

    // -- softmax budget ------------------------------------------------------
    for (const auto& c : oracle["softmax_budget"]) {
        const int batch = c["batch"].get<int>();
        const int classes = c["classes"].get<int>();
        const Tile3 tile{c["tile"][0].get<int>(), c["tile"][1].get<int>(),
                         c["tile"][2].get<int>()};
        const std::string id = "budget(" + std::to_string(batch) + ","
                               + std::to_string(classes) + ")";
        if (c["ok"].get<bool>()) {
            bool threw = false;
            try {
                pwb::prediction::validate_softmax_budget(batch, classes, tile);
            } catch (const std::exception& exc) {
                threw = true;
                check(false, id + " unexpected error: " + exc.what());
            }
            check(!threw, id + " ok");
        } else {
            bool threw = false;
            try {
                pwb::prediction::validate_softmax_budget(batch, classes, tile);
            } catch (const TiledInferenceError& exc) {
                threw = true;
                check(exc.what() == c["error"].get<std::string>(),
                      id + " error text");
            }
            check(threw, id + " throws");
        }
    }

    // -- model-file gate -----------------------------------------------------
    for (const auto& c : oracle["model_file"]) {
        const std::string kind = c["kind"].get<std::string>();
        if (kind == "ok") {
            const auto binding = pwb::prediction::check_onnx_model_file(model_path);
            check(binding.model_file
                      == c["binding"]["model_file"].get<std::string>(),
                  "model_file ok name");
            check(binding.model_bytes
                          == c["binding"]["model_bytes"].get<long long>(),
                  "model_file ok bytes");
            check(binding.model_sha256
                      == c["binding"]["model_sha256"].get<std::string>(),
                  "model_file ok sha256");
        } else {
            std::string path;
            if (kind == "suffix") path = (root / "stub.txt").string();
            if (kind == "dir") path = root.string();
            if (kind == "empty") path = (root / "empty.onnx").string();
            if (kind == "cap") path = (root / "big.onnx").string();
            if (kind == "cap") {
                set_env_var("PALEO_ONNX_MAX_MODEL_BYTES", "8");
            }
            bool threw = false;
            std::string got;
            try {
                pwb::prediction::check_onnx_model_file(path);
            } catch (const TiledInferenceError& exc) {
                threw = true;
                got = exc.what();
            }
            if (kind == "cap") {
                unset_env_var("PALEO_ONNX_MAX_MODEL_BYTES");
            }
            const std::string want_text = replace_all(
                c["error"].get<std::string>(), "<WORK>", work_token);
            check(threw, "model_file " + kind + " throws");
            check(got == want_text,
                  "model_file " + kind + " error text\n  got:  " + got
                      + "\n  want: " + want_text);
        }
    }

    // -- full runs -----------------------------------------------------------
    std::map<std::string, RunBuffers> buffers_by_work;
    for (const auto& c : oracle["runs"]) {
        const std::string id = c["id"].get<std::string>();
        const Json& input = c["input"];
        const std::string reuse = input.contains("reuse_work_of")
                                      ? input["reuse_work_of"].get<std::string>()
                                      : std::string();
        const fs::path work = root / (reuse.empty() ? id : reuse);

        const Tile3 shape{input["volume"]["shape"][0].get<int>(),
                          input["volume"]["shape"][1].get<int>(),
                          input["volume"]["shape"][2].get<int>()};
        const std::size_t voxels = static_cast<std::size_t>(shape[0])
                                 * shape[1] * shape[2];
        std::vector<float> volume(voxels);
        const Json& volume_json = input["volume"]["data"];
        for (std::size_t i = 0; i < voxels; ++i) {
            // Non-finite volumes are frozen as "NaN"/"Inf"/"-Inf" strings.
            const Json& v = volume_json[i];
            if (v.is_string()) {
                const std::string s = v.get<std::string>();
                volume[i] = s == "Inf" ? std::numeric_limits<float>::infinity()
                          : s == "-Inf"
                              ? -std::numeric_limits<float>::infinity()
                              : std::numeric_limits<float>::quiet_NaN();
            } else {
                volume[i] = static_cast<float>(v.get<double>());
            }
        }
        StubReader reader(shape, std::move(volume));
        StubSession session(input["stub"].get<std::string>());

        RunBuffers& buffers = buffers_by_work[work.string()];
        if (buffers.classmap.size() != voxels) {
            buffers.classmap.assign(voxels, 0);
            buffers.probmap.assign(voxels, 0);
        }

        const fs::path done_dir = work / "tiles.done";
        fs::create_directories(done_dir);
        if (input.contains("predone")) {
            for (const auto& name : input["predone"]) {
                std::ofstream marker(done_dir / name.get<std::string>());
                marker << "ok";
            }
        }

        TiledRunOptions options;
        options.classes = input["classes"].get<int>();
        options.work_root = work.string();
        options.overlap = input["overlap"].get<int>();
        options.batch = input["batch"].get<int>();
        options.tile = Tile3{input["tile"][0].get<int>(),
                             input["tile"][1].get<int>(),
                             input["tile"][2].get<int>()};
        int progress_calls = 0;
        options.progress = [&](double, const std::string&) { ++progress_calls; };
        if (input.contains("cancel")) {
            const std::string mode = input["cancel"].get<std::string>();
            if (mode == "always") {
                options.cancel = [] { return true; };
            } else if (mode == "after_progress") {
                const int after = input.contains("cancel_after")
                                      ? input["cancel_after"].get<int>()
                                      : 1;
                options.cancel = [&] { return progress_calls >= after; };
            }
        }

        if (c.contains("error")) {
            const std::string want_type = c["error_type"].get<std::string>();
            bool threw = false;
            std::string got;
            try {
                pwb::prediction::run_tiled_inference(
                    model_path, reader, session, options, buffers.classmap,
                    buffers.probmap);
            } catch (const TiledInferenceError& exc) {
                threw = want_type == "TiledInferenceError";
                got = exc.what();
            } catch (const std::invalid_argument& exc) {
                threw = want_type == "ValueError";
                got = exc.what();
            }
            check(threw, id + " throws " + want_type);
            const std::string want_text = replace_all(
                c["error"].get<std::string>(), "<WORK>", work_token);
            check(got == want_text,
                  id + " error text\n  got:  " + got + "\n  want: "
                      + want_text);
            continue;
        }

        const TiledRunStats stats = pwb::prediction::run_tiled_inference(
            model_path, reader, session, options, buffers.classmap,
            buffers.probmap);
        const Json& want = c["stats"];
        check(stats.mode == want["mode"].get<std::string>(), id + " mode");
        check(stats.tiles_total == want["tiles_total"].get<int>(),
              id + " tiles_total");
        check(stats.tiles_done == want["tiles_done"].get<int>(),
              id + " tiles_done");
        check(stats.cancelled == want["cancelled"].get<bool>(),
              id + " cancelled");
        check(stats.batch == want["batch"].get<int>(), id + " batch");
        check(stats.shape[0] == want["shape"][0].get<int>()
                  && stats.shape[1] == want["shape"][1].get<int>()
                  && stats.shape[2] == want["shape"][2].get<int>(),
              id + " shape");
        check(stats.classes == want["classes"].get<int>(), id + " classes");
        check(stats.overlap == want["overlap"].get<int>(), id + " overlap");
        check(stats.binding_present == want["binding_present"].get<bool>(),
              id + " binding_present");

        const Json& classmap = c["classmap"];
        std::size_t class_mismatches = 0;
        std::size_t first_bad = 0;
        for (std::size_t i = 0; i < voxels; ++i) {
            if (static_cast<int>(buffers.classmap[i]) != classmap[i].get<int>()) {
                ++class_mismatches;
                if (class_mismatches == 1) first_bad = i;
            }
        }
        check(class_mismatches == 0,
              id + " classmap exact ("
                  + std::to_string(class_mismatches) + " mismatches, first at "
                  + std::to_string(first_bad) + ")");

        const Json& probmap = c["probmap"];
        std::size_t prob_mismatches = 0;
        first_bad = 0;
        double worst = 0.0;
        for (std::size_t i = 0; i < voxels; ++i) {
            if (!same_prob(probmap[i].is_string()
                               ? 0.0
                               : probmap[i].get<double>(),
                           probmap[i], buffers.probmap[i])) {
                ++prob_mismatches;
                if (prob_mismatches == 1) first_bad = i;
                if (!probmap[i].is_string()) {
                    worst = std::max(
                        worst,
                        std::fabs(half_to_float(buffers.probmap[i])
                                  - probmap[i].get<double>()));
                }
            }
        }
        check(prob_mismatches == 0,
              id + " probmap within 1 fp16 ulp ("
                  + std::to_string(prob_mismatches) + " mismatches, first at "
                  + std::to_string(first_bad) + ", worst |d| "
                  + std::to_string(worst) + ")");

        const auto markers = list_done_markers(work);
        const Json& want_markers = c["markers"];
        bool markers_equal = markers.size() == want_markers.size();
        for (std::size_t i = 0;
             markers_equal && i < markers.size() && i < want_markers.size();
             ++i) {
            markers_equal = markers[i] == want_markers[i].get<std::string>();
        }
        check(markers_equal, id + " markers");
    }

    // -- run-level honest errors ---------------------------------------------
    for (const auto& c : oracle["run_errors"]) {
        const std::string id = c["id"].get<std::string>();
        const Json& input = c["input"];
        std::string model = model_path;
        if (input["model"].get<std::string>() == "missing") {
            model = (root / "nope" / "absent.onnx").string();
        } else if (input["model"].get<std::string>() == "suffix") {
            model = (root / "stub.txt").string();
        }
        const Tile3 shape{4, 4, 4};
        std::vector<float> volume(64, 1.0f);
        StubReader reader(shape, std::move(volume));
        StubSession session(input["stub"].is_null()
                                ? std::string("sign")
                                : input["stub"].get<std::string>());
        TiledRunOptions options;
        options.classes = input["classes"].get<int>();
        options.work_root = (root / ("w_" + id)).string();
        options.overlap = input["overlap"].get<int>();
        options.batch = input["batch"].get<int>();
        options.tile = Tile3{input["tile"][0].get<int>(),
                             input["tile"][1].get<int>(),
                             input["tile"][2].get<int>()};
        std::vector<std::uint8_t> classmap(64, 0);
        std::vector<std::uint16_t> probmap(64, 0);

        const std::string want_type = c["error_type"].get<std::string>();
        bool threw = false;
        std::string got;
        try {
            pwb::prediction::run_tiled_inference(model, reader, session,
                                                 options, classmap, probmap);
        } catch (const TiledInferenceError& exc) {
            threw = want_type == "TiledInferenceError";
            got = exc.what();
        } catch (const std::invalid_argument& exc) {
            threw = want_type == "ValueError";
            got = exc.what();
        }
        check(threw, id + " throws " + want_type);
        const std::string want_text = replace_all(
            c["error"].get<std::string>(), "<WORK>", work_token);
        check(got == want_text,
              id + " error text\n  got:  " + got + "\n  want: " + want_text);
    }

    // -- local honest-guard cases (C++-only deviations, D15/D18) ------------
    // The frozen oracle cannot cover these: the Python code silently clamps
    // or runs on; here every guard must throw with its exact message.
    {
        const Tile3 shape{4, 4, 4};
        StubReader reader(shape, std::vector<float>(64, 1.0f));
        std::vector<std::uint8_t> classmap(64, 0);
        std::vector<std::uint16_t> probmap(64, 0);

        struct GuardCase {
            const char* id;
            std::string kind;
            int overlap;
            std::size_t classmap_size;
            std::size_t probmap_size;
            const char* want;
        };
        const GuardCase guards[] = {
            {"wrong_spatial_dims", "wrong_d", 0, 64, 64,
             "model output tile shape (3, 4, 4) does not match the input "
             "tile (4, 4, 4)"},
            {"short_batch", "short_n", 0, 64, 64,
             "model output batch 0 does not match the tile group size 1"},
            {"no_channels", "zero_c", 0, 64, 64,
             "model output has no channels"},
            {"short_data", "short_data", 0, 64, 64,
             "model output data size 0 does not match its declared shape"},
            {"negative_overlap", "sign", -1, 64, 64,
             "overlap must be >= 0, got -1"},
            {"small_span", "sign", 0, 32, 64,
             "output stores must hold shape[0]*shape[1]*shape[2] = 64 "
             "elements (got classmap 32, probmap 64)"},
        };
        for (const auto& g : guards) {
            StubSession session(g.kind);
            TiledRunOptions options;
            options.classes = 2;
            options.work_root = (root / ("guard_" + std::string(g.id))).string();
            options.overlap = g.overlap;
            options.batch = 1;
            options.tile = shape;
            std::vector<std::uint8_t> cm(g.classmap_size, 0);
            std::vector<std::uint16_t> pm(g.probmap_size, 0);
            bool threw = false;
            std::string got;
            try {
                pwb::prediction::run_tiled_inference(model_path, reader,
                                                     session, options, cm,
                                                     pm);
            } catch (const TiledInferenceError& exc) {
                threw = true;
                got = exc.what();
            }
            check(threw && got == g.want,
                  std::string("guard ") + g.id + "\n  got:  " + got
                      + "\n  want: " + g.want);
        }
    }

    std::error_code cleanup_ec;
    fs::remove_all(root, cleanup_ec);

    std::printf("%s: %d failure(s) over %d tiled-stub checks\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, g_checks);
    return g_failures == 0 ? 0 : 1;
}
