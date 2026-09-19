// pwb-bench — project persistence scenarios (cpp-close wave line 14).
//   project  save + reopen round-trip over a realistically sized
//            *.paleo.json: create_new + a mapping-workspace payload with
//            N layer/feature entries, then measured save() and load()
//            blocks (atomic write + fsync + sha256 baseline on save;
//            parse + normalize + disk-sha on load).
#include "bench_common.hpp"

#include <pwb/project/document.hpp>
#include <pwb/project/manager.hpp>

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <system_error>

namespace pwb::bench {
namespace {

namespace fs = std::filesystem;
using pwb::project::ProjectDocument;
using pwb::project::ProjectManager;

void fill_workspace(ProjectDocument& doc, std::size_t features) {
    Json& ws = doc.mapping_workspace();
    Json layers = Json::array();
    Json layer = Json::object();
    layer["layer_id"] = "bench_layer";
    layer["name"] = "bench horizon interpretation";
    layer["kind"] = "horizon";
    Json feats = Json::array();
    for (std::size_t i = 0; i < features; ++i) {
        Json f = Json::object();
        char id[32];
        std::snprintf(id, sizeof id, "feat_%08zx", i);
        f["id"] = id;
        f["geometry"] = Json::object();
        f["geometry"]["type"] = "LineString";
        // ~64 points per feature — realistic horizon-pick density and a
        // JSON payload that exercises serialize+parse at scale.
        Json coords = Json::array();
        for (std::size_t p = 0; p < 64; ++p) {
            const double x = 480000.0 + (i % 512) * 12.5 + p * 0.125;
            const double y = 3400000.0 + (i % 256) * 25.0 - p * 0.0625;
            coords.push_back({x, y});
        }
        f["geometry"]["coordinates"] = std::move(coords);
        f["attributes"] = Json::object();
        f["attributes"]["horizon"] = "top_reservoir";
        f["attributes"]["confidence"] = 0.5 + (i % 100) * 0.005;
        feats.push_back(std::move(f));
    }
    layer["features"] = std::move(feats);
    layers.push_back(std::move(layer));
    ws["layers"] = std::move(layers);
}

Json bench_project(const Args& args) {
    const std::size_t features = args.get_size("features", 4000);
    const int samples = static_cast<int>(args.get_int("samples", 5));
    const fs::path work = args.get("work", "bench-out/project");
    std::error_code ec;
    fs::create_directories(work, ec);
    const fs::path project_path = work / "bench.paleo.json";

    ProjectDocument doc =
        ProjectDocument::create_new("bench", "north-sea");
    fill_workspace(doc, features);

    Json out = Json::object();
    out["features"] = features;

    // Save block: atomic tmp+fsync+rename + disk-sha baseline per call.
    {
        ProjectManager manager(project_path);
        std::uintmax_t bytes = 0;
        const Measured m = measure(samples, [&](int) {
            auto stats = manager.save(doc);
            if (!stats) {
                throw std::runtime_error("project: save failed");
            }
            bytes = stats.value().bytes_written;
        });
        Json sub = measured_to_json(m);
        sub["bytes_written"] = bytes;
        sub["file_bytes"] = fs::file_size(project_path);
        out["save"] = std::move(sub);
    }

    // Load block: full recovery decision table + parse + normalize.
    {
        const Measured m = measure(samples, [&](int) {
            ProjectManager manager(project_path);
            auto loaded = manager.load();
            if (!loaded) {
                throw std::runtime_error("project: load failed");
            }
            if (loaded.value().recovered) {
                throw std::runtime_error("project: unexpected recovery");
            }
        });
        out["load"] = measured_to_json(m);
    }
    return out;
}

}  // namespace

void register_project_scenarios(ScenarioMap& map) {
    map["project"] = &bench_project;
}

}  // namespace pwb::bench
