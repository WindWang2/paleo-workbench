// pwb-bench — prediction-core scenarios (cpp-close wave line 14).
//   tiled          one full run_tiled_inference over a synthetic volume with
//                  the deterministic stub session (CONV-13 oracle seam)
//   resume         resumed run with every tile marker present — isolates the
//                  completed-marker lookup path
//   model-binding  check_onnx_model_file cost (the model-gate hash the
//                  pipeline pays once per call site)
//   raw-read       RawVolumeReader window reads (per-tile file I/O path;
//                  requires PWB_BUILD_PREDICTION_RUNTIME)
#include "bench_common.hpp"

#include <pwb/prediction/tiled_inference.hpp>
#ifdef PWB_BENCH_PREDICTION_RUNTIME
#include <pwb/prediction/prediction_pipeline.hpp>
#endif

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

namespace pwb::bench {
namespace {

namespace fs = std::filesystem;
using pwb::prediction::InferenceSession;
using pwb::prediction::SessionBatch;
using pwb::prediction::SessionOutput;
using pwb::prediction::Tile3;
using pwb::prediction::TiledRunOptions;
using pwb::prediction::TiledRunStats;
using pwb::prediction::VolumeReader;

// Deterministic in-memory volume (mirrors the oracle stub reader shape).
class SynthReader final : public VolumeReader {
public:
    SynthReader(Tile3 shape, std::vector<float> data)
        : shape_(shape), data_(std::move(data)) {}
    Tile3 shape() const override { return shape_; }
    std::vector<float> read_voxel_window(int s0, int e0, int s1, int e1,
                                         int s2, int e2) const override {
        std::vector<float> out(
            static_cast<std::size_t>(e0 - s0) * (e1 - s1) * (e2 - s2));
        for (int a0 = s0; a0 < e0; ++a0) {
            for (int a1 = s1; a1 < e1; ++a1) {
                const std::size_t src =
                    (static_cast<std::size_t>(a0) * shape_[1] + a1)
                        * static_cast<std::size_t>(shape_[2])
                    + static_cast<std::size_t>(s2);
                const std::size_t dst =
                    (static_cast<std::size_t>(a0 - s0) * (e1 - s1)
                     + static_cast<std::size_t>(a1 - s1))
                        * static_cast<std::size_t>(e2 - s2);
                std::memcpy(out.data() + dst, data_.data() + src,
                            static_cast<std::size_t>(e2 - s2)
                                * sizeof(float));
            }
        }
        return out;
    }

private:
    Tile3 shape_;
    std::vector<float> data_;
};

// The two-channel "sign" stub: out = [x, -x] (cheap — isolates the fusion
// loop and marker machinery rather than session math).
class SignSession final : public InferenceSession {
public:
    std::string device_mode() const override { return "cpu"; }
    SessionOutput run(const SessionBatch& batch) override {
        SessionOutput out;
        out.ndim = 5;
        out.n = batch.n;
        out.c = 2;
        out.d = batch.d;
        out.h = batch.h;
        out.w = batch.w;
        const std::size_t voxels =
            static_cast<std::size_t>(batch.d) * batch.h * batch.w;
        out.data.resize(static_cast<std::size_t>(batch.n) * 2 * voxels);
        for (int n = 0; n < batch.n; ++n) {
            const float* src =
                batch.data.data() + static_cast<std::size_t>(n) * voxels;
            float* plane0 =
                out.data.data() + static_cast<std::size_t>(n) * 2 * voxels;
            float* plane1 = plane0 + voxels;
            for (std::size_t i = 0; i < voxels; ++i) {
                plane0[i] = src[i];
                plane1[i] = -src[i];
            }
        }
        return out;
    }
};

fs::path ensure_model_file(const fs::path& work, std::size_t bytes) {
    const fs::path model = work / "bench_model.onnx";
    if (fs::is_regular_file(model)
        && fs::file_size(model) == static_cast<std::uintmax_t>(bytes)) {
        return model;
    }
    std::ofstream out(model, std::ios::binary | std::ios::trunc);
    std::vector<char> block(1u << 20);
    for (std::size_t i = 0; i < block.size(); ++i) {
        block[i] = static_cast<char>(i * 31u + 7u);
    }
    std::size_t left = bytes;
    while (left > 0) {
        const std::size_t n = std::min(left, block.size());
        out.write(block.data(), static_cast<std::streamsize>(n));
        left -= n;
    }
    out.close();
    return model;
}

std::vector<float> synth_volume(const Tile3& shape) {
    const std::size_t voxels = static_cast<std::size_t>(shape[0]) * shape[1]
                             * shape[2];
    std::vector<float> data(voxels);
    for (std::size_t i = 0; i < voxels; ++i) data[i] = synth_float(i);
    return data;
}

Json bench_tiled(const Args& args) {
    const Tile3 shape = args.get_triple("shape", {160, 256, 512});
    const Tile3 tile = args.get_triple("tile", {64, 128, 128});
    const int overlap = static_cast<int>(args.get_int("overlap", 8));
    const int batch = static_cast<int>(args.get_int("batch", 4));
    const int samples = static_cast<int>(args.get_int("samples", 5));
    const fs::path work = args.get("work", "bench-out/tiled");

    std::error_code ec;
    fs::create_directories(work, ec);
    const fs::path model =
        ensure_model_file(work, args.get_size("model-bytes", 1u << 20));

    std::vector<float> volume = synth_volume(shape);
    SynthReader reader(shape, std::move(volume));
    SignSession session;
    const std::size_t voxels = static_cast<std::size_t>(shape[0]) * shape[1]
                             * shape[2];
    std::vector<std::uint8_t> classmap(voxels);
    std::vector<std::uint16_t> probmap(voxels);

    std::uint64_t digest = 0;
    TiledRunStats last;
    const Measured m = measure(samples, [&](int s) {
        const fs::path run_work =
            work / ("run_" + std::to_string(s) + ".work");
        fs::remove_all(run_work, ec);
        TiledRunOptions opt;
        opt.classes = 2;
        opt.work_root = run_work.generic_string();
        opt.overlap = overlap;
        opt.batch = batch;
        opt.tile = tile;
        last = run_tiled_inference(model.generic_string(), reader, session,
                                   opt, classmap, probmap);
        digest ^= fnv1a64(classmap.data(), classmap.size());
        digest ^=
            fnv1a64(probmap.data(), probmap.size() * sizeof(std::uint16_t));
        fs::remove_all(run_work, ec);
    });

    Json out = measured_to_json(m);
    out["voxels"] = voxels;
    out["tiles_total"] = last.tiles_total;
    out["tiles_done"] = last.tiles_done;
    out["tile"] = {tile[0], tile[1], tile[2]};
    out["overlap"] = overlap;
    out["batch"] = last.batch;
    out["digest"] = std::to_string(digest);
    return out;
}

Json bench_resume(const Args& args) {
    const int tiles = static_cast<int>(args.get_int("tiles", 20000));
    const int batch = static_cast<int>(args.get_int("batch", 8));
    const int samples = static_cast<int>(args.get_int("samples", 5));
    const fs::path work = args.get("work", "bench-out/resume");

    std::error_code ec;
    // Shape (tiles,1,4) with tile (1,1,4) overlap 0 -> exactly `tiles`
    // one-voxel tiles. All markers pre-created -> every run is a pure
    // completed-scan; inference never runs.
    const Tile3 shape{tiles, 1, 4};
    const Tile3 tile{1, 1, 4};
    fs::path done = work / "markers.work" / "tiles.done";
    fs::create_directories(done, ec);
    char name[64];
    for (int i = 0; i < tiles; ++i) {
        std::snprintf(name, sizeof name, "t_%05d_%05d_%05d", i, 0, 0);
        std::ofstream marker(done / name);
        marker << "ok";
    }

    std::vector<float> volume(static_cast<std::size_t>(tiles) * 4, 0.5f);
    SynthReader reader(shape, std::move(volume));
    SignSession session;
    std::vector<std::uint8_t> classmap(static_cast<std::size_t>(tiles) * 4);
    std::vector<std::uint16_t> probmap(static_cast<std::size_t>(tiles) * 4);
    const fs::path model =
        ensure_model_file(work, args.get_size("model-bytes", 1u << 20));

    TiledRunStats last;
    const Measured m = measure(samples, [&](int) {
        TiledRunOptions opt;
        opt.classes = 2;
        opt.work_root = (work / "markers.work").generic_string();
        opt.overlap = 0;
        opt.batch = batch;
        opt.tile = tile;
        last = run_tiled_inference(model.generic_string(), reader, session,
                                   opt, classmap, probmap);
    });

    Json out = measured_to_json(m);
    out["tiles_total"] = last.tiles_total;
    out["tiles_done"] = last.tiles_done;
    out["batch"] = batch;
    return out;
}

Json bench_model_binding(const Args& args) {
    const std::size_t mib = args.get_size("size-mib", 64);
    const int samples = static_cast<int>(args.get_int("samples", 5));
    const fs::path work = args.get("work", "bench-out/model-binding");
    std::error_code ec;
    fs::create_directories(work, ec);
    const fs::path model = ensure_model_file(work, mib << 20);

    pwb::prediction::ModelBinding last;
    const Measured m = measure(samples, [&](int) {
        last = pwb::prediction::check_onnx_model_file(model.generic_string());
    });
    Json out = measured_to_json(m);
    out["model_bytes"] = last.model_bytes;
    out["sha256"] = last.model_sha256;
    return out;
}

#ifdef PWB_BENCH_PREDICTION_RUNTIME
Json bench_raw_read(const Args& args) {
    const Tile3 shape = args.get_triple("shape", {32, 128, 256});
    const int reads = static_cast<int>(args.get_int("reads", 64));
    const int samples = static_cast<int>(args.get_int("samples", 5));
    const fs::path work = args.get("work", "bench-out/raw-read");
    std::error_code ec;
    fs::create_directories(work, ec);

    const fs::path volume_path = work / "volume.f32";
    const std::size_t voxels = static_cast<std::size_t>(shape[0]) * shape[1]
                             * shape[2];
    if (!fs::is_regular_file(volume_path)
        || fs::file_size(volume_path) != voxels * sizeof(float)) {
        std::ofstream out(volume_path, std::ios::binary | std::ios::trunc);
        std::vector<float> block(1u << 18);
        for (std::size_t i = 0; i < block.size(); ++i) {
            block[i] = synth_float(i);
        }
        std::size_t left = voxels;
        std::size_t base = 0;
        while (left > 0) {
            const std::size_t n = std::min(left, block.size());
            out.write(reinterpret_cast<const char*>(block.data()),
                      static_cast<std::streamsize>(n * sizeof(float)));
            left -= n;
            base += n;
        }
        out.close();
    }

    pwb::prediction::RawVolumeReader reader(volume_path.generic_string(),
                                          shape, "float32");
    // Deterministic pseudo-random-ish window walk: fixed-size tiles spread
    // over the volume so the OS cache sees realistic seek traffic.
    const int t0 = std::min(16, shape[0]);
    const int t1 = std::min(64, shape[1]);
    const int t2 = std::min(256, shape[2]);
    std::uint64_t digest = 0;
    const Measured m = measure(samples, [&](int) {
        for (int r = 0; r < reads; ++r) {
            const int s0 = (r * 7) % (shape[0] - t0 + 1);
            const int s1 = (r * 13) % (shape[1] - t1 + 1);
            const int s2 = (r * 5) % (shape[2] - t2 + 1);
            const std::vector<float> w = reader.read_voxel_window(
                s0, s0 + t0, s1, s1 + t1, s2, s2 + t2);
            digest ^= fnv1a64(w.data(), w.size() * sizeof(float));
        }
    });
    Json out = measured_to_json(m);
    out["reads_per_sample"] = reads;
    out["window"] = {t0, t1, t2};
    out["digest"] = std::to_string(digest);
    return out;
}
#endif

}  // namespace

void register_tiled_scenarios(ScenarioMap& map) {
    map["tiled"] = &bench_tiled;
    map["resume"] = &bench_resume;
    map["model-binding"] = &bench_model_binding;
#ifdef PWB_BENCH_PREDICTION_RUNTIME
    map["raw-read"] = &bench_raw_read;
#endif
}

}  // namespace pwb::bench
