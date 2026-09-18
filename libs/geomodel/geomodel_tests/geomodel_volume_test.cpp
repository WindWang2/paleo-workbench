// geomodel.volume — CONV-12 oracle conformance: replays the frozen Python
// oracle (libs/geomodel/geomodel_tests/fixtures/geomodel_volume_oracle.json)
// against pwb_geomodel, one case at a time, all 12 families.

#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <functional>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/geomodel/builders.hpp>
#include <pwb/geomodel/fault_displacement.hpp>
#include <pwb/geomodel/mesh_qc.hpp>
#include <pwb/geomodel/measurements.hpp>
#include <pwb/geomodel/sculpting.hpp>
#include <pwb/geomodel/section.hpp>
#include <pwb/geomodel/volume.hpp>

using pwb::domain::Json;
namespace gm = pwb::geomodel;

namespace {

int g_failures = 0;
int g_cases = 0;

// Case-scoped failure tracker so one case can report every mismatch.
struct Case {
    std::string id;
    int failures = 0;

    void check(bool ok, const std::string& what) {
        if (!ok) {
            std::fprintf(stderr, "FAIL [%s] %s\n", id.c_str(), what.c_str());
            ++failures;
            ++g_failures;
        }
    }
};

double num(const Json& v) {
    return v.is_null() ? std::numeric_limits<double>::quiet_NaN()
                       : v.get<double>();
}

gm::Vec3 vec3(const Json& a) {
    return {num(a[0]), num(a[1]), num(a[2])};
}

std::vector<gm::Vec3> verts_of(const Json& a) {
    std::vector<gm::Vec3> out;
    out.reserve(a.size());
    for (const auto& row : a) {
        out.push_back(vec3(row));
    }
    return out;
}

std::vector<std::array<double, 2>> ring_of(const Json& a) {
    std::vector<std::array<double, 2>> out;
    out.reserve(a.size());
    for (const auto& row : a) {
        out.push_back({num(row[0]), num(row[1])});
    }
    return out;
}

std::vector<std::array<std::int64_t, 3>> faces_of(const Json& a) {
    std::vector<std::array<std::int64_t, 3>> out;
    out.reserve(a.size());
    for (const auto& row : a) {
        out.push_back({row[0].get<std::int64_t>(), row[1].get<std::int64_t>(),
                       row[2].get<std::int64_t>()});
    }
    return out;
}

void expect_raises(Case& cs, const Json& c, const std::function<void()>& fn) {
    try {
        fn();
        cs.check(false, "expected exception, got none");
    } catch (const std::exception& e) {
        const std::string want = c["raises"].get<std::string>();
        cs.check(e.what() == want,
                 "error text\n     got: " + std::string(e.what()) +
                     "\n    want: " + want);
    }
}

gm::HorizonGrid grid_of(const Json& c, const char* key) {
    const Json& g = c[key];
    gm::HorizonGrid grid;
    grid.rows = g["rows"].get<int>();
    grid.cols = g["cols"].get<int>();
    // Grid-entry fields win, then case-level fields, then the builder
    // defaults the generator used.
    grid.origin_x = 0.0;
    grid.origin_y = 0.0;
    grid.spacing_y = 10.0;
    grid.spacing_x = 10.0;
    if (c.contains("origin") && !c["origin"].is_null()) {
        grid.origin_x = c["origin"][0].get<double>();
        grid.origin_y = c["origin"][1].get<double>();
    }
    if (c.contains("spacing") && !c["spacing"].is_null()) {
        grid.spacing_y = c["spacing"][0].get<double>();
        grid.spacing_x = c["spacing"][1].get<double>();
    }
    if (g.contains("origin") && !g["origin"].is_null()) {
        grid.origin_x = g["origin"][0].get<double>();
        grid.origin_y = g["origin"][1].get<double>();
    }
    if (g.contains("spacing") && !g["spacing"].is_null()) {
        grid.spacing_y = g["spacing"][0].get<double>();
        grid.spacing_x = g["spacing"][1].get<double>();
    }
    grid.vertical_domain = c.value("vertical_domain", std::string("depth"));
    grid.unit = "m";
    grid.object_id = key;
    grid.z.reserve(static_cast<std::size_t>(grid.rows) * grid.cols);
    for (const auto& v : g["z"]) {
        grid.z.push_back(num(v));
    }
    return grid;
}

bool num_eq(double got, double want, double tol) {
    if (std::isnan(got) && std::isnan(want)) {
        return true;
    }
    if (std::isnan(got) != std::isnan(want)) {
        return false;
    }
    return std::fabs(got - want) <= tol;
}

void expect_array(Case& cs, const std::vector<double>& got,
                  const Json& want, double tol, const std::string& what) {
    if (got.size() != want.size()) {
        cs.check(false, what + ": size " + std::to_string(got.size()) +
                            " != " + std::to_string(want.size()));
        return;
    }
    for (std::size_t i = 0; i < got.size(); ++i) {
        const double w = num(want[i]);
        if (!num_eq(got[i], w, tol)) {
            cs.check(false,
                     what + "[" + std::to_string(i) + "] got " +
                         std::to_string(got[i]) + " want " +
                         (std::isnan(w) ? std::string("nan")
                                        : std::to_string(w)));
            return;
        }
    }
}

void expect_verts(Case& cs, const std::vector<gm::Vec3>& got,
                  const Json& want, double tol, const std::string& what) {
    if (got.size() != want.size()) {
        cs.check(false, what + ": vertex count " + std::to_string(got.size()) +
                            " != " + std::to_string(want.size()));
        return;
    }
    for (std::size_t i = 0; i < got.size(); ++i) {
        for (int k = 0; k < 3; ++k) {
            const double w = num(want[i][k]);
            if (!num_eq(got[i][k], w, tol)) {
                cs.check(false,
                         what + "[" + std::to_string(i) + "]." +
                             std::to_string(k) + " got " +
                             std::to_string(got[i][k]) + " want " +
                             std::to_string(w));
                return;
            }
        }
    }
}

void expect_faces(Case& cs,
                  const std::vector<std::array<std::int64_t, 3>>& got,
                  const Json& want, const std::string& what) {
    if (got.size() != want.size()) {
        cs.check(false, what + ": face count " + std::to_string(got.size()) +
                            " != " + std::to_string(want.size()));
        return;
    }
    for (std::size_t i = 0; i < got.size(); ++i) {
        for (int k = 0; k < 3; ++k) {
            if (got[i][k] != want[i][k].get<std::int64_t>()) {
                cs.check(false, what + "[" + std::to_string(i) + "] got {" +
                                    std::to_string(got[i][0]) + "," +
                                    std::to_string(got[i][1]) + "," +
                                    std::to_string(got[i][2]) + "}");
                return;
            }
        }
    }
}

std::vector<float> float_z_of(const Json& z) {
    std::vector<float> out;
    out.reserve(z.size());
    for (const auto& v : z) {
        out.push_back(static_cast<float>(v.get<double>()));
    }
    return out;
}

// ---------------------------------------------------------------------------
// family runners
// ---------------------------------------------------------------------------

void run_volume(Case& cs, const Json& c) {
    const auto top = verts_of(c["top"]);
    const auto bot = verts_of(c["bot"]);
    if (c.contains("raises")) {
        expect_raises(cs, c, [&] {
            gm::closed_mesh_volume(top, bot,
                                   c["rows"].get<std::size_t>(),
                                   c["cols"].get<std::size_t>());
        });
        return;
    }
    const double got = gm::closed_mesh_volume(
        top, bot, c["rows"].get<std::size_t>(), c["cols"].get<std::size_t>());
    const double want = c["volume"].get<double>();
    const double rtol = c["rtol"].get<double>();
    cs.check(std::fabs(got - want) <= rtol * std::max(1.0, std::fabs(want)),
             "volume got " + std::to_string(got) + " want " +
                 std::to_string(want));
}

void run_sculpt(Case& cs, const Json& c) {
    const std::string id = c["id"].get<std::string>();
    const double z_tol = c.value("z_tol", 0.0);
    if (c.contains("raises")) {
        if (id == "anneal_reshape_mismatch") {
            std::vector<gm::SculptVertex> vs(36);
            for (auto& v : vs) {
                v = {0.0f, 0.0f, 0.0f};
            }
            gm::SculptableHorizonMesh mesh(vs, std::make_pair(6, 5));
            expect_raises(cs, c, [&] { mesh.smooth_anneal(); });
            return;
        }
        gm::SculptableHorizonMesh mesh(std::vector<gm::SculptVertex>(36));
        expect_raises(cs, c, [&] { mesh.smooth_anneal(); });
        return;
    }
    // Rebuild the mesh state per case from the frozen final/intermediate
    // expectations; each case re-executes the Python sequence.
    if (id == "brush_center_rim_zero") {
        std::vector<gm::SculptVertex> vs(25);
        for (int i = 0; i < 5; ++i) {
            for (int j = 0; j < 5; ++j) {
                vs[i * 5 + j] = {static_cast<float>(j), static_cast<float>(i),
                                 100.0f};
            }
        }
        gm::SculptableHorizonMesh mesh(vs);
        mesh.sculpt_surface(0.0, 0.0, 10.0, 3.0);
        std::vector<double> z;
        for (const auto& v : mesh.vertices()) {
            z.push_back(v.z);
        }
        expect_array(cs, z, c["z"], z_tol, "z");
        const auto& patch = mesh.undo_patches().at(0);
        cs.check(patch.indices.size() ==
                     static_cast<std::size_t>(c["patch_indices"].size()),
                 "patch size");
        for (std::size_t k = 0; k < patch.indices.size() &&
                                k < c["patch_indices"].size();
             ++k) {
            cs.check(patch.indices[k] == c["patch_indices"][k].get<int>(),
                     "patch index " + std::to_string(k));
        }
        return;
    }
    if (id == "undo_redo_roundtrip") {
        std::vector<gm::SculptVertex> vs(25);
        for (int i = 0; i < 5; ++i) {
            for (int j = 0; j < 5; ++j) {
                vs[i * 5 + j] = {static_cast<float>(j), static_cast<float>(i),
                                 50.0f};
            }
        }
        gm::SculptableHorizonMesh mesh(vs);
        const bool can_undo_before = mesh.can_undo();
        cs.check(can_undo_before == c["can_undo_before"].get<bool>(),
                 "can_undo_before");
        mesh.sculpt_surface(2.0, 2.0, 15.0, 2.5);
        std::vector<double> after_sculpt;
        for (const auto& v : mesh.vertices()) {
            after_sculpt.push_back(v.z);
        }
        expect_array(cs, after_sculpt, c["after_sculpt"], z_tol,
                     "after_sculpt");
        const bool did_undo = mesh.undo();
        cs.check(did_undo == c["did_undo"].get<bool>(), "did_undo");
        std::vector<double> after_undo;
        for (const auto& v : mesh.vertices()) {
            after_undo.push_back(v.z);
        }
        expect_array(cs, after_undo, c["after_undo"], z_tol, "after_undo");
        const bool did_redo = mesh.redo();
        cs.check(did_redo == c["did_redo"].get<bool>(), "did_redo");
        std::vector<double> after_redo;
        for (const auto& v : mesh.vertices()) {
            after_redo.push_back(v.z);
        }
        expect_array(cs, after_redo, c["after_redo"], z_tol, "after_redo");
        cs.check(mesh.can_undo() == c["can_undo_after_sculpt"].get<bool>(),
                 "can_undo_after");
        return;
    }
    if (id == "nonpositive_radius_noop") {
        std::vector<gm::SculptVertex> vs(25);
        for (auto& v : vs) {
            v = {0.0f, 0.0f, 100.0f};
        }
        gm::SculptableHorizonMesh mesh(vs);
        mesh.sculpt_surface(0.5, 0.5, -3.0, 0.0);
        mesh.sculpt_surface(0.5, 0.5, -3.0, -1.0);
        std::vector<double> z;
        for (const auto& v : mesh.vertices()) {
            z.push_back(v.z);
        }
        expect_array(cs, z, c["z"], z_tol, "z");
        cs.check(mesh.undo_patches().size() ==
                     static_cast<std::size_t>(c["undo_depth"].get<int>()),
                 "undo stack empty");
        return;
    }
    if (id == "set_heights") {
        std::vector<gm::SculptVertex> vs(25);
        for (auto& v : vs) {
            v = {0.0f, 0.0f, 50.0f};
        }
        gm::SculptableHorizonMesh mesh(vs);
        mesh.set_heights({3, 7}, {-5.0f, 2.5f});
        std::vector<double> z;
        for (const auto& v : mesh.vertices()) {
            z.push_back(v.z);
        }
        expect_array(cs, z, c["z"], z_tol, "z");
        const auto& patch = mesh.undo_patches().at(0);
        std::vector<double> old_z;
        for (const float v : patch.old_z) {
            old_z.push_back(v);
        }
        expect_array(cs, old_z, c["patch_old_z"], 0.0, "patch_old_z");
        return;
    }
    if (id == "anneal_sparse_patch") {
        std::vector<gm::SculptVertex> vs(36);
        for (std::size_t i = 0; i < 36; ++i) {
            vs[i] = {static_cast<float>(i % 6), static_cast<float>(i / 6), 0.0f};
        }
        vs[14].z = 5.0f;
        gm::SculptableHorizonMesh mesh(vs, std::make_pair(6, 6));
        mesh.smooth_anneal(1);
        std::vector<double> z;
        for (const auto& v : mesh.vertices()) {
            z.push_back(v.z);
        }
        expect_array(cs, z, c["z"], z_tol, "z");
        const auto& patch = mesh.undo_patches().at(0);
        std::vector<double> new_z;
        for (const float v : patch.new_z) {
            new_z.push_back(v);
        }
        expect_array(cs, new_z, c["patch_new_z"], z_tol, "patch_new_z");
        cs.check(patch.indices.size() ==
                     static_cast<std::size_t>(c["patch_indices"].size()),
                 "patch_indices size");
        cs.check(patch.indices.size() < 36, "patch is sparse (< 36)");
        return;
    }
    if (id == "anneal_3_iterations") {
        if (!c.contains("anneal_input")) {
            cs.check(false, "anneal_3_iterations needs anneal_input");
            return;
        }
        std::vector<gm::SculptVertex> vs;
        const Json& in = c["anneal_input"];
        for (std::size_t i = 0; i < in.size(); ++i) {
            vs.push_back({0.0f, 0.0f, static_cast<float>(num(in[i]))});
        }
        gm::SculptableHorizonMesh mesh(vs, std::make_pair(10, 10));
        mesh.smooth_anneal(3);
        std::vector<double> z;
        for (const auto& v : mesh.vertices()) {
            z.push_back(v.z);
        }
        expect_array(cs, z, c["z"], z_tol, "z");
        return;
    }
    if (id == "anneal_no_change" || id == "set_heights_empty") {
        const std::size_t n_pts = id == "anneal_no_change" ? 36 : 25;
        const float base_z = id == "anneal_no_change" ? 7.0f : 50.0f;
        std::vector<gm::SculptVertex> vs(n_pts);
        for (auto& v : vs) {
            v = {0.0f, 0.0f, base_z};
        }
        if (id == "anneal_no_change") {
            gm::SculptableHorizonMesh mesh(vs, std::make_pair(6, 6));
            mesh.smooth_anneal(2);
            std::vector<double> z;
            for (const auto& v2 : mesh.vertices()) {
                z.push_back(v2.z);
            }
            expect_array(cs, z, c["z"], z_tol, "z");
            cs.check(mesh.undo_patches().size() ==
                         static_cast<std::size_t>(c["undo_depth"].get<int>()),
                     "undo depth (no patch on no-change)");
        } else {
            gm::SculptableHorizonMesh mesh(vs);
            mesh.set_heights({}, {});
            std::vector<double> z;
            for (const auto& v2 : mesh.vertices()) {
                z.push_back(v2.z);
            }
            expect_array(cs, z, c["z"], z_tol, "z");
            cs.check(mesh.undo_patches().size() ==
                         static_cast<std::size_t>(c["undo_depth"].get<int>()),
                     "undo depth (empty set_heights)");
        }
        return;
    }
    if (id == "sculpt_outside_no_patch") {
        std::vector<gm::SculptVertex> vs(25);
        for (int i = 0; i < 5; ++i) {
            for (int j = 0; j < 5; ++j) {
                vs[i * 5 + j] = {static_cast<float>(j), static_cast<float>(i),
                                 50.0f};
            }
        }
        gm::SculptableHorizonMesh mesh(vs);
        mesh.sculpt_surface(2.0, 2.0, 1.0, 2.0);
        mesh.undo();
        mesh.redo();
        mesh.sculpt_surface(1000.0, 1000.0, 5.0, 3.0);
        std::vector<double> z;
        for (const auto& v : mesh.vertices()) {
            z.push_back(v.z);
        }
        expect_array(cs, z, c["z"], z_tol, "z");
        cs.check(mesh.undo_patches().size() ==
                     static_cast<std::size_t>(c["undo_depth"].get<int>()),
                 "undo depth");
        return;
    }
    cs.check(false, "unhandled sculpt case " + id);
}

void run_fault(Case& cs, const Json& c) {
    gm::FaultSpec spec;
    spec.fault_line_x = c.value("fault_line_x", 0.0);
    spec.throw_z = c.value("throw_z", 0.0);
    spec.fault_line_y = c.value("fault_line_y", 0.0);
    spec.throw_x = c.value("throw_x", 0.0);
    spec.dip_deg = c.value("dip_deg", 60.0);
    spec.strike_deg = c.value("strike_deg", 0.0);
    spec.decay_radius = c.value("decay_radius", 0.0);
    if (c.contains("spec")) {
        const Json& s = c["spec"];
        spec.fault_line_x = s["fault_line_x"].get<double>();
        spec.throw_z = s["throw_z"].get<double>();
        spec.fault_line_y = s["fault_line_y"].get<double>();
        spec.throw_x = s["throw_x"].get<double>();
        spec.dip_deg = s["dip_deg"].get<double>();
        spec.strike_deg = s["strike_deg"].get<double>();
        spec.decay_radius = s["decay_radius"].get<double>();
    }
    const double tol = c.value("tol", 0.0);
    const auto verts = verts_of(c["verts"]);

    auto compare = [&](const auto& got, const Json& want, const std::string& what) {
        std::vector<double> flat;
        for (const auto& v : got) {
            flat.push_back(v[0]);
            flat.push_back(v[1]);
            flat.push_back(v[2]);
        }
        std::vector<double> want_flat;
        for (const auto& row : want) {
            for (int k = 0; k < 3; ++k) {
                want_flat.push_back(num(row[k]));
            }
        }
        expect_array(cs, flat, want_flat, tol, what);
    };

    if (c.contains("spec")) {
        const auto out = gm::apply_fault_throw<double>(verts, spec);
        compare(out, c["out"], "out");
        return;
    }
    if (c.contains("out_local")) {
        // The port must reproduce both runs, and the displacement fields
        // must be translation-invariant: (out_shifted - shifted) ==
        // (out_local - local).
        std::vector<gm::Vec3> shifted = verts;
        for (auto& v : shifted) {
            v[0] += 500000.0;
            v[1] += 3200000.0;
        }
        gm::FaultSpec utm_spec = spec;
        utm_spec.fault_line_x = 500000.0;
        utm_spec.fault_line_y = 3200000.0;
        const auto out_local = gm::apply_fault_throw<double>(verts, spec);
        const auto out_shifted =
            gm::apply_fault_throw<double>(shifted, utm_spec);
        compare(out_local, c["out_local"], "out_local");
        compare(out_shifted, c["out_shifted"], "out_shifted");
        for (std::size_t i = 0; i < verts.size(); ++i) {
            for (int k = 0; k < 3; ++k) {
                const double d_local = out_local[i][k] - verts[i][k];
                const double d_shifted = out_shifted[i][k] - shifted[i][k];
                if (std::fabs(d_local - d_shifted) > tol) {
                    cs.check(false,
                             "translation invariance at " + std::to_string(i) +
                                 "." + std::to_string(k));
                    return;
                }
            }
        }
        return;
    }
    if (c["dtype"].get<std::string>() == "float32") {
        std::vector<std::array<float, 3>> v32;
        for (const auto& v : verts) {
            v32.push_back({static_cast<float>(v[0]), static_cast<float>(v[1]),
                           static_cast<float>(v[2])});
        }
        const auto out = gm::apply_fault_throw<float>(v32, spec);
        compare(out, c["out"], "out");
    } else {
        const auto out = gm::apply_fault_throw<double>(verts, spec);
        compare(out, c["out"], "out");
    }
}

void run_triangulate(Case& cs, const Json& c) {
    const gm::HorizonGrid grid = grid_of(c, "grid");
    const gm::TriMesh mesh = gm::triangulate_heightfield(grid);
    expect_verts(cs, mesh.verts, c["verts"], 0.0, "verts");
    expect_faces(cs, mesh.faces, c["faces"], "faces");
}

void run_curtain(Case& cs, const Json& c) {
    if (c.contains("raises")) {
        const std::string id = c["id"].get<std::string>();
        if (id == "err_inverted_z") {
            expect_raises(cs, c, [&] {
                gm::build_fault_curtain_from_trace("F", {{0.0, 0.0}, {1.0, 1.0}},
                                                   300.0, 100.0);
            });
            return;
        }
        if (id == "err_nonfinite_trace") {
            const double nan = std::numeric_limits<double>::quiet_NaN();
            expect_raises(cs, c, [&] {
                gm::build_fault_curtain_from_trace(
                    "F", {{0.0, 0.0}, {nan, 1.0}}, 100.0, 300.0);
            });
            return;
        }
        if (id == "err_equal_z") {
            expect_raises(cs, c, [&] {
                gm::build_fault_curtain_from_trace("F", {{0.0, 0.0}, {1.0, 1.0}},
                                                   100.0, 100.0);
            });
            return;
        }
        expect_raises(cs, c, [&] {
            gm::build_fault_curtain_from_trace("F", {{0.0, 0.0}}, 100.0, 300.0);
        });
        return;
    }
    const gm::TriMesh mesh = gm::build_fault_curtain_from_trace(
        "F1", {{0.0, 0.0}, {100.0, 0.0}, {100.0, 50.0}}, 100.0, 300.0);
    expect_verts(cs, mesh.verts, c["verts"], 0.0, "verts");
    expect_faces(cs, mesh.faces, c["faces"], "faces");
}

void run_shell(Case& cs, const Json& c) {
    const std::string id = c["id"].get<std::string>();
    const std::string object_id = c.value("object_id", std::string("volume:v"));
    if (c.contains("raises")) {
        // Error cases reconstruct minimal inputs by id (mirrors the Python
        // generator calls).
        const std::vector<std::array<double, 2>> square = {
            {0.0, 0.0}, {10.0, 0.0}, {10.0, 10.0}, {0.0, 10.0}};
        if (id == "err_domain_mismatch") {
            gm::HorizonGrid t = gm::build_horizon_from_grid(
                3, 3, 0, 0, 10, 10, std::vector<double>(9, 100.0), "depth", "m",
                "horizon:top");
            gm::HorizonGrid b = gm::build_horizon_from_grid(
                3, 3, 0, 0, 10, 10, std::vector<double>(9, 150.0), "twt", "m",
                "horizon:base");
            expect_raises(cs, c, [&] {
                gm::build_volume_shell(t, b, square, object_id);
            });
            return;
        }
        if (id == "err_grid_mismatch") {
            gm::HorizonGrid b = gm::build_horizon_from_grid(
                6, 6, 0, 0, 10, 10, std::vector<double>(36, 150.0), "depth",
                "m", "horizon:base");
            gm::HorizonGrid other = gm::build_horizon_from_grid(
                5, 5, 0, 0, 10, 10, std::vector<double>(25, 100.0), "depth",
                "m", "horizon:t2");
            expect_raises(cs, c, [&] {
                gm::build_volume_shell(other, b, square, object_id);
            });
            return;
        }
        if (id == "err_boundary_nonfinite") {
            const double nan = std::numeric_limits<double>::quiet_NaN();
            gm::HorizonGrid g = gm::build_horizon_from_grid(
                6, 6, 0, 0, 10, 10, std::vector<double>(36, 100.0), "depth",
                "m", "horizon:top");
            std::vector<std::array<double, 2>> ring = {
                {0.0, 0.0}, {10.0, nan}, {10.0, 10.0}, {0.0, 10.0}};
            expect_raises(cs, c, [&] {
                gm::build_volume_shell(g, g, ring, object_id);
            });
            return;
        }
        if (id == "err_boundary_two_points") {
            gm::HorizonGrid g = gm::build_horizon_from_grid(
                6, 6, 0, 0, 10, 10, std::vector<double>(36, 100.0), "depth",
                "m", "horizon:top");
            std::vector<std::array<double, 2>> two = {{0.0, 0.0}, {10.0, 0.0}};
            expect_raises(cs, c, [&] {
                gm::build_volume_shell(g, g, two, object_id);
            });
            return;
        }
        if (id == "err_single_row_lattice") {
            gm::HorizonGrid g = gm::build_horizon_from_grid(
                1, 6, 0, 0, 10, 10, std::vector<double>(6, 100.0), "depth",
                "m", "horizon:top");
            std::vector<std::array<double, 2>> ring = {
                {0, 0}, {50, 0}, {50, 10}, {0, 10}};
            expect_raises(cs, c, [&] {
                gm::build_volume_shell(g, g, ring, object_id);
            });
            return;
        }
        cs.check(false, "unhandled shell error case " + id);
        return;
    }

    const gm::HorizonGrid top = grid_of(c, "top");
    const gm::HorizonGrid base = grid_of(c, "base");
    const std::vector<std::array<double, 2>> bnd = ring_of(c["boundary"]);
    const gm::VolumeShell shell =
        gm::build_volume_shell(top, base, bnd, object_id);
    const Json& want_qc = c["qc"];
    const double qc_tol = c.value("tol", 0.0);
    cs.check(shell.qc.column_count == want_qc["column_count"].get<std::int64_t>(),
             "qc.column_count");
    cs.check(shell.qc.dropped_crossed ==
                 want_qc["dropped_crossed"].get<std::int64_t>(),
             "qc.dropped_crossed");
    cs.check(shell.qc.dropped_nan_nodes ==
                 want_qc["dropped_nan_nodes"].get<std::int64_t>(),
             "qc.dropped_nan_nodes");
    cs.check(shell.qc.negative_thickness_count ==
                 want_qc["negative_thickness_count"].get<std::int64_t>(),
             "qc.negative_thickness_count");
    cs.check(num_eq(shell.qc.min_thickness, num(want_qc["min_thickness"]), qc_tol),
             "qc.min_thickness");
    cs.check(num_eq(shell.qc.max_thickness, num(want_qc["max_thickness"]), qc_tol),
             "qc.max_thickness");
    cs.check(num_eq(shell.qc.mean_thickness, num(want_qc["mean_thickness"]), qc_tol),
             "qc.mean_thickness");
    cs.check(shell.qc.closed == want_qc["closed"].get<bool>(), "qc.closed");
    cs.check(shell.qc.unit == want_qc["unit"].get<std::string>(), "qc.unit");
    expect_verts(cs, shell.mesh.verts, c["verts"], 0.0, "verts");
    expect_faces(cs, shell.mesh.faces, c["faces"], "faces");
}

void run_hex(Case& cs, const Json& c) {
    const std::string id0 = c["id"].get<std::string>();
    if (id0 == "boundary_outside_empty_mesh") {
        gm::HorizonGrid top = gm::build_horizon_from_grid(
            3, 3, 0, 0, 10, 10, std::vector<double>(9, 100.0), "depth", "m",
            "horizon:top");
        gm::HorizonGrid base = gm::build_horizon_from_grid(
            3, 3, 0, 0, 10, 10, std::vector<double>(9, 150.0), "depth", "m",
            "horizon:base");
        std::vector<std::array<double, 2>> far = {
            {1000.0, 1000.0}, {1040.0, 1000.0}, {1040.0, 1040.0},
            {1000.0, 1040.0}};
        const gm::HexMesh mesh = gm::build_columnar_hex_mesh(top, base, far, 4);
        expect_verts(cs, mesh.nodes, c["nodes"], 0.0, "nodes");
        cs.check(mesh.hexes.size() == static_cast<std::size_t>(c["hexes"].size()),
                 "empty hexes");
        const Json& want = c["info"];
        cs.check(mesh.info.n_cells == want["n_cells"].get<std::int64_t>(),
                 "info.n_cells");
        cs.check(mesh.info.skipped_crossed ==
                     want["skipped_crossed"].get<std::int64_t>(),
                 "info.skipped_crossed");
        return;
    }
    if (c.contains("raises")) {
        const std::string id = c["id"].get<std::string>();
        if (id == "err_boundary_two_points") {
            gm::HorizonGrid g = gm::build_horizon_from_grid(
                6, 6, 0, 0, 10, 10, std::vector<double>(36, 100.0), "depth",
                "m", "horizon:top");
            std::vector<std::array<double, 2>> two = {{0.0, 0.0}, {10.0, 0.0}};
            expect_raises(cs, c, [&] {
                gm::build_columnar_hex_mesh(g, g, two, 4);
            });
            return;
        }
        if (id == "err_boundary_nonfinite") {
            const double nan = std::numeric_limits<double>::quiet_NaN();
            gm::HorizonGrid g = gm::build_horizon_from_grid(
                6, 6, 0, 0, 10, 10, std::vector<double>(36, 100.0), "depth",
                "m", "horizon:top");
            std::vector<std::array<double, 2>> ring = {
                {0.0, 0.0}, {10.0, nan}, {10.0, 10.0}, {0.0, 10.0}};
            expect_raises(cs, c, [&] {
                gm::build_columnar_hex_mesh(g, g, ring, 4);
            });
            return;
        }
        if (id == "err_domain_mismatch") {
            gm::HorizonGrid t = gm::build_horizon_from_grid(
                6, 6, 0, 0, 10, 10, std::vector<double>(36, 100.0), "depth",
                "m", "horizon:top");
            gm::HorizonGrid b = gm::build_horizon_from_grid(
                6, 6, 0, 0, 10, 10, std::vector<double>(36, 150.0), "twt", "m",
                "horizon:base");
            std::vector<std::array<double, 2>> ring = {
                {0, 0}, {10, 0}, {10, 10}, {0, 10}};
            expect_raises(cs, c, [&] {
                gm::build_columnar_hex_mesh(t, b, ring, 4);
            });
            return;
        }
        if (id == "err_zero_layers") {
            gm::HorizonGrid g = gm::build_horizon_from_grid(
                6, 6, 0, 0, 10, 10, std::vector<double>(36, 100.0), "depth",
                "m", "horizon:top");
            std::vector<std::array<double, 2>> ring = {
                {0, 0}, {10, 0}, {10, 10}, {0, 10}};
            expect_raises(cs, c, [&] {
                gm::build_columnar_hex_mesh(g, g, ring, 0);
            });
            return;
        }
        if (id == "err_grid_mismatch") {
            gm::HorizonGrid t5 = gm::build_horizon_from_grid(
                5, 5, 0, 0, 10, 10, std::vector<double>(25, 100.0), "depth",
                "m", "horizon:t2");
            gm::HorizonGrid b6 = gm::build_horizon_from_grid(
                6, 6, 0, 0, 10, 10, std::vector<double>(36, 150.0), "depth",
                "m", "horizon:base");
            std::vector<std::array<double, 2>> ring = {
                {0, 0}, {10, 0}, {10, 10}, {0, 10}};
            expect_raises(cs, c, [&] {
                gm::build_columnar_hex_mesh(t5, b6, ring, 4);
            });
            return;
        }
        cs.check(false, "unhandled hex error case " + c["id"].get<std::string>());
        return;
    }
    const gm::HorizonGrid top = grid_of(c, "top");
    const gm::HorizonGrid base = grid_of(c, "base");
    const std::vector<std::array<double, 2>> bnd = ring_of(c["boundary"]);
    const gm::HexMesh mesh = gm::build_columnar_hex_mesh(
        top, base, bnd, c["n_layers"].get<int>());
    expect_verts(cs, mesh.nodes, c["nodes"], 0.0, "nodes");
    // hexes: 8 columns
    if (mesh.hexes.size() != c["hexes"].size()) {
        cs.check(false, "hex count " + std::to_string(mesh.hexes.size()));
        return;
    }
    for (std::size_t i = 0; i < mesh.hexes.size(); ++i) {
        for (int k = 0; k < 8; ++k) {
            if (mesh.hexes[i][k] != c["hexes"][i][k].get<std::int64_t>()) {
                cs.check(false, "hexes[" + std::to_string(i) + "] connectivity");
                return;
            }
        }
    }
    const Json& want = c["info"];
    cs.check(mesh.info.n_cells == want["n_cells"].get<std::int64_t>(),
             "info.n_cells");
    cs.check(mesh.info.n_layers == want["n_layers"].get<std::int64_t>(),
             "info.n_layers");
    cs.check(mesh.info.n_hexes == want["n_hexes"].get<std::int64_t>(),
             "info.n_hexes");
    cs.check(mesh.info.skipped_crossed ==
                 want["skipped_crossed"].get<std::int64_t>(),
             "info.skipped_crossed");
    cs.check(mesh.info.unit == want["unit"].get<std::string>(), "info.unit");
    cs.check(mesh.info.merge == want["merge"].get<std::string>(), "info.merge");
}

void run_pip(Case& cs, const Json& c) {
    std::vector<std::array<double, 2>> ring;
    for (const auto& p : c["ring"]) {
        ring.push_back({num(p[0]), num(p[1])});
    }
    const Json& probes = c["probes"];
    for (std::size_t i = 0; i < probes.size(); ++i) {
        const bool got = gm::point_in_ring_strict(num(probes[i][0]),
                                                  num(probes[i][1]), ring);
        cs.check(got == c["inside"][i].get<bool>(),
                 "probe " + std::to_string(i) + " got " +
                     (got ? "true" : "false"));
    }
}

void run_dedupe(Case& cs, const Json& c) {
    if (c.contains("raises")) {
        std::vector<std::array<double, 4>> stations;
        for (const auto& row : c["stations"]) {
            stations.push_back({num(row[0]), num(row[1]), num(row[2]), num(row[3])});
        }
        expect_raises(cs, c, [&] { gm::dedupe_stations(stations); });
        return;
    }
    std::vector<std::array<double, 4>> stations;
    for (const auto& row : c["stations"]) {
        stations.push_back({num(row[0]), num(row[1]), num(row[2]), num(row[3])});
    }
    auto [kept, dropped] = gm::dedupe_stations(stations);
    cs.check(dropped == c["dropped"].get<int>(), "dropped");
    if (kept.size() != c["kept"].size()) {
        cs.check(false, "kept size");
        return;
    }
    for (std::size_t i = 0; i < kept.size(); ++i) {
        for (int k = 0; k < 4; ++k) {
            cs.check(num_eq(kept[i][k], num(c["kept"][i][k]), 0.0),
                     "kept[" + std::to_string(i) + "][" + std::to_string(k) + "]");
        }
    }
}

void run_measure(Case& cs, const Json& c) {
    const std::string id = c["id"].get<std::string>();
    const std::string kind = c.value("kind", std::string());
    const double tol = c.value("tol", 0.0);
    if (c.contains("raises")) {
        if (id == "thickness_hole_raises") {
            gm::HorizonGrid top = gm::build_horizon_from_grid(
                4, 4, 0, 0, 10, 10, std::vector<double>(16, 0.0), "depth", "m",
                "horizon:t");
            std::vector<double> bz(16, 50.0);
            bz[0] = std::numeric_limits<double>::quiet_NaN();
            gm::HorizonGrid base = gm::build_horizon_from_grid(
                4, 4, 0, 0, 10, 10, bz, "depth", "m", "horizon:b");
            expect_raises(cs, c, [&] { gm::thickness_at(1.0, 1.0, top, base); });
            return;
        }
        if (id == "thickness_domain_mismatch_raises") {
            gm::HorizonGrid top = gm::build_horizon_from_grid(
                3, 3, 0, 0, 10, 10, std::vector<double>(9, 0.0), "depth", "m",
                "horizon:t");
            gm::HorizonGrid base = gm::build_horizon_from_grid(
                3, 3, 0, 0, 10, 10, std::vector<double>(9, 1.0), "twt", "m",
                "horizon:b");
            expect_raises(cs, c, [&] { gm::thickness_at(0.0, 0.0, top, base); });
            return;
        }
        if (id == "err_plane_two_points") {
            expect_raises(cs, c, [&] {
                gm::plane_orientation({{0, 0, 0}, {1, 1, 1}}, "EPSG:32650");
            });
            return;
        }
        if (id == "thickness_outside_grid_raises") {
            gm::HorizonGrid top = gm::build_horizon_from_grid(
                4, 4, 0, 0, 10, 10, std::vector<double>(16, 0.0), "depth", "m",
                "horizon:t");
            std::vector<double> bz(16, 50.0);
            bz[0] = std::numeric_limits<double>::quiet_NaN();
            gm::HorizonGrid base = gm::build_horizon_from_grid(
                4, 4, 0, 0, 10, 10, bz, "depth", "m", "horizon:b");
            expect_raises(cs, c, [&] { gm::thickness_at(100.0, 15.0, top, base); });
            return;
        }
        if (id == "err_nonfinite") {
            expect_raises(cs, c, [&] {
                const double nan = std::numeric_limits<double>::quiet_NaN();
                gm::distance({0, 0, nan}, {1, 1, 1}, "EPSG:32650");
            });
            return;
        }
        if (id == "err_polyline_single_point") {
            expect_raises(cs, c, [&] {
                gm::polyline_length({{0, 0, 0}}, "EPSG:32650");
            });
            return;
        }
        cs.check(false, "unhandled measure error case " + id);
        return;
    }

    gm::MeasurementResult m;
    if (kind == "distance") {
        m = gm::distance({0, 0, 0}, {3, 4, 0}, "EPSG:32650");
    } else if (kind == "polyline") {
        m = gm::polyline_length({{0, 0, 0}, {1, 0, 0}, {1, 1, 0}}, "EPSG:32650");
        cs.check(m.legs == c["legs"].get<int>(), "legs");
    } else if (kind == "vertical_difference") {
        m = id == "vertical_negative"
                ? gm::vertical_difference({0, 0, 10}, {1, 1, -5}, "EPSG:32650")
                : gm::vertical_difference({0, 0, 0}, {1, 1, 10}, "EPSG:32650");
        if (c.contains("dz")) {
            cs.check(num_eq(*m.result, num(c["result"]), tol), "result");
        }
    } else if (kind == "thickness") {
        // grid inputs frozen under the same keys used by the generator
        if (id == "thickness_center" || id == "thickness_edge_clamp" ||
            id == "thickness_ft_unit") {
            std::vector<double> tz(16, 0.0);
            std::vector<double> bz(16, 50.0);
            if (id == "thickness_center" || id == "thickness_ft_unit") {
                bz[0] = std::numeric_limits<double>::quiet_NaN();
            }
            gm::HorizonGrid top = gm::build_horizon_from_grid(
                4, 4, 0, 0, 10, 10, tz, "depth", "m", "horizon:t");
            gm::HorizonGrid base = gm::build_horizon_from_grid(
                4, 4, 0, 0, 10, 10, bz, "depth", "m", "horizon:b");
            m = id == "thickness_ft_unit"
                    ? gm::thickness_at(15.0, 15.0, top, base, "", "ft")
                    : gm::thickness_at(id == "thickness_edge_clamp" ? 30.0 : 15.0,
                                       id == "thickness_edge_clamp" ? 20.0 : 15.0,
                                       top, base);
        } else if (id.rfind("thickness_single_column_x", 0) == 0) {
            const double px = std::stod(
                id.substr(std::strlen("thickness_single_column_x")));
            gm::HorizonGrid top = gm::build_horizon_from_grid(
                3, 1, 0, 0, 10, 1, {10.0, 20.0, 30.0}, "depth", "m",
                "horizon:t1");
            gm::HorizonGrid base = gm::build_horizon_from_grid(
                3, 1, 0, 0, 10, 1, {15.0, 25.0, 35.0}, "depth", "m",
                "horizon:b1");
            m = gm::thickness_at(px, 15.0, top, base);
        }
    } else if (kind == "plane_orientation") {
        if (id == "plane_tilted") {
            m = gm::plane_orientation(
                {{0, 0, 0}, {10, 0, 0}, {0, 10, 1}, {10, 10, 1}},
                "EPSG:32650");
        } else if (id == "plane_zero_scatter") {
            m = gm::plane_orientation({{5, 5, 5}, {5, 5, 5}, {5, 5, 5}},
                                      "EPSG:32650");
        } else {
            m = gm::plane_orientation(
                {{0, 0, 0}, {10, 0, 0}, {0, 10, 0}, {10, 10, 0}},
                "EPSG:32650");
        }
        cs.check(num_eq(m.dip_deg, num(c["dip"]), tol), "dip");
        cs.check(num_eq(m.strike_deg, num(c["strike"]), tol), "strike");
        cs.check(num_eq(m.planarity_ratio, num(c["planarity"]), tol),
                 "planarity");
        if (c.contains("result")) {
            cs.check(num_eq(*m.result, num(c["result"]), tol), "result");
        }
    } else if (kind == "point") {
        m = gm::point_coordinate({5, 6, -100}, "EPSG:32650");
        cs.check(num_eq(m.extra_z, num(c["extra_z"]), 0.0), "extra_z");
    }
    if (c.contains("result")) {
        cs.check(num_eq(m.result.value_or(0.0), num(c["result"]), tol),
                 "result");
    }
    if (c.contains("signed")) {
        cs.check(num_eq(m.signed_dz, num(c["signed"]), tol), "signed");
    }
    if (c.contains("points")) {
        expect_verts(cs, m.points, c["points"], 0.0, "points");
    }
    cs.check(gm::format_result(m) == c["formatted"].get<std::string>(),
             "formatted\n     got: " + gm::format_result(m) +
                 "\n    want: " + c["formatted"].get<std::string>());
}

void run_section(Case& cs, const Json& c) {
    const std::string id = c["id"].get<std::string>();
    const double tol = c.value("tol", 0.0);
    if (c.contains("raises")) {
        if (id == "err_bad_axis") {
            expect_raises(cs, c, [&] { gm::axis_plane("w", 0.0); });
            return;
        }
        if (id == "err_zero_normal") {
            expect_raises(cs, c, [&] { gm::Plane({0, 0, 0}, 1.0); });
            return;
        }
        cs.check(false, "unhandled section error " + id);
        return;
    }

    if (id == "plane_normalized" || id == "axis_plane_clip" ||
        id == "plane_from_normal_point") {
        const bool normalized = id == "plane_normalized";
        const bool axis = id == "axis_plane_clip";
        const gm::Plane p = normalized ? gm::Plane({0, 0, 2}, -300.0)
                            : axis     ? gm::axis_plane("z", -150.0)
                                       : gm::plane_from_normal_point(
                                             {1, 1, 0}, {5, 5, -7});
        std::vector<double> n = {p.n[0], p.n[1], p.n[2]};
        expect_array(cs, n, c["normal"], 0.0, "normal");
        cs.check(num_eq(p.d, num(c["d"]), 0.0), "d");
        if (c.contains("signed")) {
            // frozen signed distances correspond to (0,0,-150) and (0,0,-50)
            const double d0 = p.signed_distance({0, 0, -150});
            const double d1 = p.signed_distance({0, 0, -50});
            cs.check(num_eq(d0, num(c["signed"][0]), 0.0), "signed[0]");
            cs.check(num_eq(d1, num(c["signed"][1]), 0.0), "signed[1]");
        }
        if (c.contains("clip_eq")) {
            const auto eq = p.as_clip_equation(false);
            for (int k = 0; k < 4; ++k) {
                cs.check(num_eq(eq[k], num(c["clip_eq"][k]), 0.0), "clip_eq");
            }
            const auto eqi = p.as_clip_equation(true);
            for (int k = 0; k < 4; ++k) {
                cs.check(num_eq(eqi[k], num(c["clip_eq_invert"][k]), 0.0),
                         "clip_eq_invert");
            }
        }
        return;
    }
    if (id == "box_clip_six") {
        const auto eqs = gm::clip_planes_for_box({0, 0, 0}, {10, 20, 30});
        cs.check(eqs.size() == c["eqs"].size(), "eq count");
        for (std::size_t i = 0; i < eqs.size() && i < c["eqs"].size(); ++i) {
            for (int k = 0; k < 4; ++k) {
                cs.check(num_eq(eqs[i][k], num(c["eqs"][i][k]), 0.0),
                         "eqs[" + std::to_string(i) + "]");
            }
        }
        return;
    }
    if (id == "horizon_z_section_single" || id == "horizon_nan_splits_curve") {
        const gm::HorizonGrid grid = grid_of(c, "grid");
        const auto curves = gm::horizon_plane_intersection(
            gm::axis_plane(c["axis"].get<std::string>(),
                           c["value"].get<double>()),
            grid);
        cs.check(curves.size() == c["curves"].size(), "curve count");
        for (std::size_t i = 0;
             i < curves.size() && i < c["curves"].size(); ++i) {
            expect_verts(cs, curves[i], c["curves"][i], tol,
                         "curve " + std::to_string(i));
        }
        return;
    }
    if (id == "mesh_box_section") {
        const auto verts = verts_of(c["verts"]);
        const auto faces = faces_of(c["faces"]);
        const auto curves = gm::mesh_plane_intersection(
            gm::axis_plane(c["axis"].get<std::string>(),
                           c["value"].get<double>()),
            verts, faces);
        cs.check(curves.size() == c["curves"].size(), "curve count");
        for (std::size_t i = 0;
             i < curves.size() && i < c["curves"].size(); ++i) {
            expect_verts(cs, curves[i], c["curves"][i], tol,
                         "curve " + std::to_string(i));
        }
        return;
    }
    if (id == "triangle_two_onscreen_vertices" ||
        id == "triangle_mixed_zero_vertex") {
        std::vector<gm::Vec3> tri;
        if (id == "triangle_two_onscreen_vertices") {
            tri = {{0, 0, 0}, {10, 0, 0}, {5, 10, 4}};
        } else {
            tri = {{0, 0, 0}, {10, 0, 6}, {0, 10, -4}};
        }
        const auto segs = gm::intersect_plane_with_triangles(
            gm::axis_plane("z", 0.0), tri, {{0, 1, 2}});
        cs.check(segs.size() == c["segs"].size(), "seg count");
        for (std::size_t i = 0; i < segs.size() && i < c["segs"].size(); ++i) {
            expect_verts(cs, std::vector<gm::Vec3>{segs[i].begin(), segs[i].end()},
                         c["segs"][i], tol, "seg");
        }
        return;
    }
    if (id == "well_crossing") {
        const auto stations = verts_of(c["stations"]);
        const auto hit = gm::well_plane_crossing(gm::axis_plane("z", -150.0),
                                                 stations);
        const auto miss = gm::well_plane_crossing(gm::axis_plane("z", -500.0),
                                                  stations);
        const auto on = gm::well_plane_crossing(gm::axis_plane("z", -100.0),
                                                stations);
        cs.check(hit.has_value() == c["hit"].is_array(), "hit presence");
        if (hit.has_value()) {
            expect_verts(cs, {*hit}, c["hit"], tol, "hit");
        }
        cs.check(miss.has_value() == c["miss"].is_array(), "miss presence");
        cs.check(on.has_value() == c["on_plane"].is_array(),
                 "on-plane presence");
        if (on.has_value()) {
            expect_verts(cs, {*on}, c["on_plane"], tol, "on_plane");
        }
        return;
    }
    if (id == "chain_two_segments") {
        std::vector<gm::Segment> segs;
        for (const auto& s : c["segments"]) {
            const auto pts = verts_of(s);
            segs.push_back({pts[0], pts[1]});
        }
        const auto chains = gm::chain_segments(segs);
        cs.check(chains.size() == c["chains"].size(), "chain count");
        for (std::size_t i = 0;
             i < chains.size() && i < c["chains"].size(); ++i) {
            expect_verts(cs, chains[i], c["chains"][i], tol,
                         "chain " + std::to_string(i));
        }
        return;
    }
    cs.check(false, "unhandled section case " + id);
}

void run_horizon_err(Case& cs, const Json& c) {
    const std::string id = c["id"].get<std::string>();
    if (id == "err_empty_grid") {
        expect_raises(cs, c, [&] {
            gm::build_horizon_from_grid(0, 0, 0, 0, 1, 1, {}, "depth", "m",
                                        "Bad");
        });
        return;
    }
    const double inf = std::numeric_limits<double>::infinity();
    expect_raises(cs, c, [&] {
        gm::build_horizon_from_grid(2, 2, 0, 0, 1, 1, {0.0, 1.0, inf, 0.0},
                                    "depth", "m", "horizon:bad");
    });
}

void run_meshqc(Case& cs, const Json& c) {
    const auto verts = verts_of(c["verts"]);
    const auto faces = faces_of(c["faces"]);
    const double tol = c.value("tol", 0.0);
    if (c.contains("degenerate_fraction")) {
        cs.check(num_eq(gm::tri_degenerate_fraction(verts, faces),
                        c["degenerate_fraction"].get<double>(), tol),
                 "degenerate_fraction");
    }
    if (c.contains("edge")) {
        const auto stats = gm::edge_manifold_stats(faces);
        cs.check(stats.boundary == c["edge"]["boundary"].get<std::int64_t>(),
                 "edge.boundary");
        cs.check(stats.nonmanifold == c["edge"]["nonmanifold"].get<std::int64_t>(),
                 "edge.nonmanifold");
    }
    if (c.contains("components")) {
        cs.check(gm::connected_components(verts.size(), faces) ==
                     c["components"].get<int>(),
                 "components");
    }
}

}  // namespace

int main() {
    std::ifstream stream(PWB_GEOMODEL_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open fixture\n");
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    const std::unordered_map<std::string,
                             void (*)(Case&, const Json&)>
        runners = {
            {"volume", run_volume}, {"sculpt", run_sculpt},
            {"fault", run_fault}, {"triangulate", run_triangulate},
            {"curtain", run_curtain}, {"shell", run_shell},
            {"hex", run_hex}, {"pip", run_pip}, {"dedupe", run_dedupe},
            {"measure", run_measure}, {"section", run_section},
            {"meshqc", run_meshqc}, {"horizon_err", run_horizon_err},
        };

    for (const auto& c : oracle["cases"]) {
        ++g_cases;
        Case cs{c["id"].get<std::string>(), 0};
        const auto it = runners.find(c["family"].get<std::string>());
        if (it == runners.end()) {
            std::fprintf(stderr, "FAIL unknown family %s\n",
                         c["family"].get<std::string>().c_str());
            ++g_failures;
            continue;
        }
        try {
            it->second(cs, c);
        } catch (const std::exception& e) {
            std::fprintf(stderr, "FAIL [%s] (%s) threw: %s\n", cs.id.c_str(),
                         c["family"].get<std::string>().c_str(), e.what());
            ++g_failures;
        }
    }
    std::printf("%s: %d failure(s) over %d geomodel oracle cases\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, g_cases);
    return g_failures == 0 ? 0 : 1;
}
