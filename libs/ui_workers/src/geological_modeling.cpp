#include "pwb/ui_workers/geological_modeling.hpp"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <thread>

#include <pwb/domain/json.hpp>
#include <pwb/geomodel/advisor_contract.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_workers {

namespace {

// Python emits integer percents (10/30/60/80/95/100); the runtime ratio
// is the same numbers / 100.
void report(job::JobContext& ctx, int percent) {
    ctx.report_progress(static_cast<double>(percent) / 100.0);
}

void default_sleep(double seconds) {
    std::this_thread::sleep_for(
        std::chrono::duration<double>(seconds));
}

// f"k={f:.2f}" label parity.
std::string k_label(double fraction) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "k=%.2f", fraction);
    return buf;
}

void write_file_bytes(const std::string& path, const std::string& bytes) {
    namespace fs = std::filesystem;
    // out.parent.mkdir(parents=True, exist_ok=True) — the Python
    // exporters create the tree; mirror it so export paths behave alike.
    const fs::path parent = fs::path(path).parent_path();
    if (!parent.empty()) {
        std::error_code ec;
        fs::create_directories(parent, ec);
    }
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw std::runtime_error("cannot open " + path + " for writing");
    }
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!out) {
        throw std::runtime_error("failed writing " + path);
    }
}

// The Python V2 exporters persist "<stem>.provenance.json" next to the
// export file (path.with_name(stem + ".provenance.json")).
void write_sidecar(const std::string& filename,
                   const pwb::geomodel::ExportWritten& written) {
    if (written.sidecar.is_null()) return;
    namespace fs = std::filesystem;
    const fs::path sidecar_path =
        fs::path(filename).parent_path() / written.sidecar_name;
    write_file_bytes(
        sidecar_path.string(),
        pwb::domain::dump_json_python_compatible(written.sidecar));
}

// The four hardcoded borehole records — geological_modeling_workers.py
// run() verbatim (kept as Json so non-ASCII lithology names survive
// untouched).
Json make_bh_raw() {
    return Json::array({
        {{"name", "钻孔 HZ21-1"},
         {"x", -40.0},
         {"y", -40.0},
         {"total_depth", 150.0},
         {"layers",
          Json::array({
              {{"top", 0.0}, {"bottom", 30.0}, {"lithology", "砂岩"},
               {"color", Json::array({0.8, 0.6, 0.4, 0.8})}},
              {{"top", 30.0}, {"bottom", 75.0}, {"lithology", "泥岩"},
               {"color", Json::array({0.5, 0.5, 0.5, 0.8})}},
              {{"top", 75.0}, {"bottom", 120.0}, {"lithology", "石灰岩"},
               {"color", Json::array({0.4, 0.7, 0.9, 0.8})}},
              {{"top", 120.0}, {"bottom", 150.0}, {"lithology", "花岗岩"},
               {"color", Json::array({0.9, 0.4, 0.4, 0.8})}},
          })}},
        {{"name", "钻孔 HZ19-6"},
         {"x", 40.0},
         {"y", -40.0},
         {"total_depth", 180.0},
         {"layers",
          Json::array({
              {{"top", 0.0}, {"bottom", 40.0}, {"lithology", "砂岩"},
               {"color", Json::array({0.8, 0.6, 0.4, 0.8})}},
              {{"top", 40.0}, {"bottom", 90.0}, {"lithology", "泥岩"},
               {"color", Json::array({0.5, 0.5, 0.5, 0.8})}},
              {{"top", 90.0}, {"bottom", 140.0}, {"lithology", "石灰岩"},
               {"color", Json::array({0.4, 0.7, 0.9, 0.8})}},
              // Intentional depth overlap check warning.
              {{"top", 135.0}, {"bottom", 180.0}, {"lithology", "花岗岩"},
               {"color", Json::array({0.9, 0.4, 0.4, 0.8})}},
          })}},
        {{"name", "钻孔 XJ24-3"},
         {"x", -40.0},
         {"y", 40.0},
         {"total_depth", 200.0},
         {"layers",
          Json::array({
              {{"top", 0.0}, {"bottom", 50.0}, {"lithology", "砂岩"},
               {"color", Json::array({0.8, 0.6, 0.4, 0.8})}},
              {{"top", 50.0}, {"bottom", 110.0}, {"lithology", "泥岩"},
               {"color", Json::array({0.5, 0.5, 0.5, 0.8})}},
              {{"top", 110.0}, {"bottom", 160.0}, {"lithology", "石灰岩"},
               {"color", Json::array({0.4, 0.7, 0.9, 0.8})}},
              {{"top", 160.0}, {"bottom", 200.0}, {"lithology", "花岗岩"},
               {"color", Json::array({0.9, 0.4, 0.4, 0.8})}},
          })}},
        {{"name", "钻孔 HZ25-2"},
         {"x", 40.0},
         {"y", 40.0},
         {"total_depth", 160.0},
         {"layers",
          Json::array({
              {{"top", 0.0}, {"bottom", 35.0}, {"lithology", "砂岩"},
               {"color", Json::array({0.8, 0.6, 0.4, 0.8})}},
              {{"top", 35.0}, {"bottom", 80.0}, {"lithology", "泥岩"},
               {"color", Json::array({0.5, 0.5, 0.5, 0.8})}},
              {{"top", 80.0}, {"bottom", 130.0}, {"lithology", "石灰岩"},
               {"color", Json::array({0.4, 0.7, 0.9, 0.8})}},
              // Exceeds total depth check warning.
              {{"top", 130.0}, {"bottom", 168.0}, {"lithology", "花岗岩"},
               {"color", Json::array({0.9, 0.4, 0.4, 0.8})}},
          })}},
    });
}

Json make_tunnel_raw() {
    return Json::array({
        {{"name", "巷道 A"},
         {"path", Json::array({Json::array({-50.0, -20.0, -30.0}),
                               Json::array({0.0, 0.0, -40.0}),
                               Json::array({50.0, 20.0, -50.0})})},
         {"color", Json::array({0.2, 0.8, 0.2, 0.9})}},
        {{"name", "巷道 B"},
         {"path", Json::array({Json::array({-30.0, 50.0, -20.0}),
                               Json::array({20.0, 10.0, -35.0}),
                               Json::array({60.0, -30.0, -55.0})})},
         {"color", Json::array({0.8, 0.8, 0.2, 0.9})}},
    });
}

Json make_faults_raw() {
    return Json::array({
        {{"name", "断层 F1 Surface"},
         {"normal", Json::array({1.0, 0.5, 0.2})},
         {"d", -20.0},
         {"color", Json::array({0.9, 0.2, 0.2, 0.65})}},
        {{"name", "断层 F2 Surface"},
         {"normal", Json::array({0.98, 0.52, 0.18})},
         {"d", -25.0},
         {"color", Json::array({0.9, 0.2, 0.5, 0.65})}},
    });
}

Color4 json_color(const Json& arr) {
    Color4 c = {1.0, 1.0, 1.0, 1.0};
    for (std::size_t i = 0; i < 4 && i < arr.size(); ++i) {
        c[i] = arr.at(i).get<double>();
    }
    return c;
}

}  // namespace

GeoModelingResult run_geological_modeling(const GeoModelingInput& input,
                                        job::JobContext& ctx) {
    return with_plain_errors([&]() -> GeoModelingResult {
        const auto sleep = input.sleep_fn ? input.sleep_fn
                                          : &default_sleep;
        report(ctx, 10);
        sleep(0.2);
        report(ctx, 30);

        // Density → volume grid resolution (Chinese label check verbatim).
        int dim;
        if (input.density.find("低") != std::string::npos) {
            dim = 40;
        } else if (input.density.find("中") != std::string::npos) {
            dim = 80;
        } else {
            dim = 120;
        }

        // val = kk + 8 sin(ii/8) cos(jj/8) on an (i,j,k) 'ij' meshgrid;
        // uint8 cast truncates toward zero and wraps mod 256 (%256 is a
        // no-op after the astype — numpy parity).
        GeoModelingResult result;
        result.dim = dim;
        result.volume_data.resize(
            static_cast<std::size_t>(dim) * dim * dim);
        for (int i = 0; i < dim; ++i) {
            const double si = std::sin(i / 8.0);
            for (int j = 0; j < dim; ++j) {
                const double cj = std::cos(j / 8.0);
                const double base = 8.0 * si * cj;
                for (int k = 0; k < dim; ++k) {
                    const double val =
                        (static_cast<double>(k) + base) / dim * 255.0;
                    result.volume_data
                        [(static_cast<std::size_t>(i) * dim + j) * dim +
                         k] = static_cast<std::uint8_t>(
                        static_cast<long long>(val));
                }
            }
        }

        report(ctx, 60);
        sleep(0.1);

        result.bh_raw = make_bh_raw();
        for (const auto& bh : result.bh_raw) {
            const double bx = bh.at("x").get<double>();
            const double by = bh.at("y").get<double>();
            for (const auto& lyr : bh.at("layers")) {
                const double t = lyr.at("top").get<double>();
                const double b = lyr.at("bottom").get<double>();
                NamedGeom entry;
                entry.name = bh.at("name").get<std::string>();
                entry.geom = generate_cylinder_geometry(
                    {bx, by, -t}, {bx, by, -b}, 2.5,
                    json_color(lyr.at("color")));
                result.boreholes.push_back(std::move(entry));
            }
        }

        report(ctx, 80);

        const Json tunnel_raw = make_tunnel_raw();
        for (const auto& tn : tunnel_raw) {
            std::vector<Vec3d> path;
            for (const auto& p : tn.at("path")) {
                path.push_back({p.at(0).get<double>(),
                                p.at(1).get<double>(),
                                p.at(2).get<double>()});
            }
            NamedGeom entry;
            entry.name = tn.at("name").get<std::string>();
            entry.geom = generate_tube_geometry(
                path, 3.5, json_color(tn.at("color")));
            result.tunnels.push_back(std::move(entry));
        }

        result.faults_raw = make_faults_raw();
        const std::array<double, 2> z_offsets = {20.0, 12.0};
        std::size_t fi = 0;
        for (const auto& flt : result.faults_raw) {
            NamedGeom entry;
            entry.name = flt.at("name").get<std::string>();
            entry.geom = generate_fault_geometry(
                {-60.0, 60.0}, {-60.0, 60.0}, 40, 40,
                json_color(flt.at("color")));
            // v[:, 2] += offset — applied to the float32 verts after the
            // generator returns (numpy parity).
            const float dz =
                static_cast<float>(z_offsets[fi % z_offsets.size()]);
            for (auto& v : entry.geom.vertices) v[2] += dz;
            ++fi;
            result.faults.push_back(std::move(entry));
        }

        report(ctx, 95);
        sleep(0.1);
        report(ctx, 100);

        result.demo = input.demo;
        result.source = input.demo ? "synthetic/demo" : "real_data";
        result.algorithm = input.algorithm;
        return result;
    });
}

job::JobSpec make_geological_modeling_job_spec(
    GeoModelingInput input,
    std::function<void(const GeoModelingResult&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel) {
    job::JobSpec spec;
    spec.kind = "geomodel.generate";
    spec.title = "三维地质模型生成";
    spec.run = [input = std::move(input)](job::JobContext& ctx) -> std::any {
        return run_geological_modeling(input, ctx);
    };
    spec.on_done = [on_done = std::move(on_done)](const std::any& result) {
        if (on_done) {
            on_done(std::any_cast<const GeoModelingResult&>(result));
        }
    };
    spec.on_fail = std::move(on_fail);
    spec.on_cancel = std::move(on_cancel);
    return spec;
}

// ---------------------------------------------------------------------------
// StratalWorker
// ---------------------------------------------------------------------------

StratalResult run_stratal(const StratalInput& input, job::JobContext& ctx) {
    return with_plain_errors([&]() -> StratalResult {
        ctx.check_cancelled();
        StratalResult result;
        result.demo = input.demo;
        for (double f : input.fractions) {
            result.labels.push_back(k_label(f));
        }

        if (input.demo) {
            auto [vol, top, bot] = make_demo_stratal_grids(
                input.demo_shape[0], input.demo_shape[1],
                input.demo_shape[2], input.demo_noise_fn);
            result.volume = vol;
            result.surfaces =
                build_proportional_surfaces(top, bot, input.fractions);
            for (const auto& surface : result.surfaces) {
                ctx.check_cancelled();
                result.amplitudes.push_back(extract_stratal_slice(vol, surface));
            }
            return result;
        }

        std::optional<std::pair<Grid2D, Grid2D>> grids = input.preview_grids;
        if (!grids && input.grids_fn) {
            grids = input.grids_fn(input, input.n_i_prev, input.n_x_prev,
                                   input.stride_i, input.stride_x,
                                   input.dt_ms, input.t0_ms,
                                   input.sample_stride);
        }
        if (!grids) {
            throw StratalSoftFail(
                "survey/registration 不可用或体数据未就绪，无法对齐 "
                "horizon。");
        }
        auto out = build_stratal_surfaces(grids->first, grids->second,
                                          input.n_s_prev, input.fractions);
        if (!out) {
            throw StratalSoftFail(
                "horizon 对全部倒转或无效，未生成切片。");
        }
        result.surfaces = std::move(out->first);
        ctx.check_cancelled();
        if (input.amplitudes_fn) {
            result.amplitudes = input.amplitudes_fn(result.surfaces, ctx);
            if (result.amplitudes.size() != result.surfaces.size())
                throw std::runtime_error("stratal amplitude map count mismatch");
            for (std::size_t k = 0; k < result.surfaces.size(); ++k) {
                const auto& a = result.amplitudes[k];
                const auto& s = result.surfaces[k];
                if (a.rows != s.rows || a.cols != s.cols || a.data.size() != s.data.size())
                    throw std::runtime_error("stratal amplitude map shape mismatch");
            }
        }
        return result;
    });
}

job::JobSpec make_stratal_job_spec(
    StratalInput input,
    std::function<void(const StratalResult&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel) {
    job::JobSpec spec;
    spec.kind = "geomodel.stratal";
    spec.title = "地层切片计算";
    spec.run = [input = std::move(input)](job::JobContext& ctx) -> std::any {
        return run_stratal(input, ctx);
    };
    spec.on_done = [on_done = std::move(on_done)](const std::any& result) {
        if (on_done) {
            on_done(std::any_cast<const StratalResult&>(result));
        }
    };
    spec.on_fail = std::move(on_fail);
    spec.on_cancel = std::move(on_cancel);
    return spec;
}

// ---------------------------------------------------------------------------
// ExportWorker
// ---------------------------------------------------------------------------

ExportResult run_export(const ExportInput& input, job::JobContext& ctx) {
    return with_plain_errors([&]() -> ExportResult {
        const bool v2 = input.volume.has_value() || input.surface.has_value();
        ExportResult result;
        result.filename = input.filename;

        if (!v2) {
            // Legacy GridSpec path — non-"flac3d" modes fall through to
            // abaqus exactly like the Python `else`.
            const GridSpecSlice& s = input.grid_spec;
            result.written.file =
                (input.mode == "flac3d")
                    ? pwb::geomodel::legacy_export_to_flac3d(
                          s.nx, s.ny, s.nz, s.dx, s.dy, s.dz)
                    : pwb::geomodel::legacy_export_to_abaqus(
                          s.nx, s.ny, s.nz, s.dx, s.dy, s.dz);
            write_file_bytes(input.filename, result.written.file);
            return result;
        }

        const pwb::geomodel::DomainObject& target =
            input.volume ? *input.volume : *input.surface;
        if (input.mode == "flac3d" || input.mode == "abaqus") {
            // Python passes self.volume (possibly None) — the exporter
            // then raises inside assert_exportable/qc_object on the
            // NoneType. A missing volume is the same failure class here.
            if (!input.volume) {
                // qc_object(None) -> obj.object_id AttributeError.
                throw std::invalid_argument(
                    "'NoneType' object has no attribute 'object_id'");
            }
            result.written =
                (input.mode == "flac3d")
                    ? pwb::geomodel::export_volume_flac3d(
                          *input.volume, input.filename, input.top,
                          input.base)
                    : pwb::geomodel::export_volume_abaqus(
                          *input.volume, input.filename, input.top,
                          input.base);
        } else if (input.mode == "obj") {
            result.written =
                pwb::geomodel::export_mesh_obj(target, input.filename);
        } else if (input.mode == "stl") {
            result.written =
                pwb::geomodel::export_mesh_stl(target, input.filename);
        } else if (input.mode == "vtp") {
            result.written = pwb::geomodel::export_mesh_vtp(
                target, input.filename, input.point_data);
        } else {
            // raise ValueError(f"unknown export mode {mode!r}") parity —
            // bare str(e) through on_fail.
            throw std::invalid_argument("unknown export mode '" +
                                        input.mode + "'");
        }
        write_file_bytes(input.filename, result.written.file);
        write_sidecar(input.filename, result.written);
        return result;
    });
}

job::JobSpec make_export_job_spec(
    ExportInput input,
    std::function<void(const ExportResult&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel) {
    job::JobSpec spec;
    spec.kind = "geomodel.export";
    spec.title = "地质模型导出";
    spec.run = [input = std::move(input)](job::JobContext& ctx) -> std::any {
        return run_export(input, ctx);
    };
    spec.on_done = [on_done = std::move(on_done)](const std::any& result) {
        if (on_done) {
            on_done(std::any_cast<const ExportResult&>(result));
        }
    };
    spec.on_fail = std::move(on_fail);
    spec.on_cancel = std::move(on_cancel);
    return spec;
}

// ---------------------------------------------------------------------------
// AdvisorWorker
// ---------------------------------------------------------------------------

AdvisorResult run_advisor(const AdvisorInput& input, job::JobContext& ctx) {
    return with_plain_errors([&]() -> AdvisorResult {
        AdvisorResult result;
        result.bh_report =
            pwb::geomodel::check_boreholes(input.boreholes);
        result.fault_report =
            pwb::geomodel::check_coplanar_faults(input.faults);
        return result;
    });
}

job::JobSpec make_advisor_job_spec(
    AdvisorInput input,
    std::function<void(const AdvisorResult&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel) {
    job::JobSpec spec;
    spec.kind = "geomodel.advisor";
    spec.title = "地质数据一致性分析";
    spec.run = [input = std::move(input)](job::JobContext& ctx) -> std::any {
        return run_advisor(input, ctx);
    };
    spec.on_done = [on_done = std::move(on_done)](const std::any& result) {
        if (on_done) {
            on_done(std::any_cast<const AdvisorResult&>(result));
        }
    };
    spec.on_fail = std::move(on_fail);
    spec.on_cancel = std::move(on_cancel);
    return spec;
}

}  // namespace pwb::ui_workers
