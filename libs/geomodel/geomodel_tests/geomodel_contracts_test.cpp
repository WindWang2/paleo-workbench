// geomodel.contracts — CONV-22 oracle conformance: replays the frozen
// Python oracle (fixtures/geomodel_contract_oracle.json) against the
// geomodel contract layer — domain objects/meta/assembly, QC ladder +
// export gate, V2 exporters + read-back validators + provenance sidecars,
// advisor rules, lithology tables, pure builders. The oracle was produced
// by the REAL paleo_workbench.viz.geomodel modules; "$FX" in case fields
// is literal text (readers echo it back in error paths), not a path marker.

#include <pwb/domain/json.hpp>
#include <pwb/geomodel/advisor_contract.hpp>
#include <pwb/geomodel/domain_contract.hpp>
#include <pwb/geomodel/export_contract.hpp>
#include <pwb/geomodel/qc_contract.hpp>

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_set>

namespace {

using pwb::domain::Json;
namespace gm = pwb::geomodel;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

// Python has one int type: oracle numbers parse as unsigned while C++
// construction writes signed — dump/parse roundtrip puts both sides on the
// same number kind (int-vs-float stays a real difference), matching the
// prediction.contracts convention.
Json norm(const Json& v) { return Json::parse(v.dump()); }

bool sem_eq(const Json& a, const Json& b) {
    return pwb::domain::json_semantically_equal(norm(a), norm(b));
}

// ---------------------------------------------------------------------------
// base64 (STL payloads freeze as {"b64": ...})
// ---------------------------------------------------------------------------

const char* kB64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                   "0123456789+/";

std::string b64_encode(std::string_view in) {
    std::string out;
    for (std::size_t i = 0; i < in.size(); i += 3) {
        const unsigned a = static_cast<unsigned char>(in[i]);
        const unsigned b =
            i + 1 < in.size() ? static_cast<unsigned char>(in[i + 1]) : 0;
        const unsigned c =
            i + 2 < in.size() ? static_cast<unsigned char>(in[i + 2]) : 0;
        out += kB64[a >> 2];
        out += kB64[((a & 3) << 4) | (b >> 4)];
        out += i + 1 < in.size() ? kB64[((b & 15) << 2) | (c >> 6)] : '=';
        out += i + 2 < in.size() ? kB64[c & 63] : '=';
    }
    return out;
}

std::string b64_decode(const std::string& in) {
    auto val = [](char ch) -> int {
        if (ch >= 'A' && ch <= 'Z') return ch - 'A';
        if (ch >= 'a' && ch <= 'z') return ch - 'a' + 26;
        if (ch >= '0' && ch <= '9') return ch - '0' + 52;
        if (ch == '+') return 62;
        if (ch == '/') return 63;
        return -1;
    };
    std::string out;
    int acc = 0, bits = 0;
    for (char ch : in) {
        const int v = val(ch);
        if (v < 0) continue;
        acc = (acc << 6) | v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out += static_cast<char>((acc >> bits) & 0xFF);
        }
    }
    return out;
}

// ---------------------------------------------------------------------------
// spec helpers
// ---------------------------------------------------------------------------

double num(const Json& v) {
    return v.is_null() ? std::numeric_limits<double>::quiet_NaN()
                       : v.get<double>();
}

// Ragged rows: malformed-width fixtures must reach the builders so the
// (N, C) DomainError fires inside the kernel, not the runner.
std::vector<std::vector<double>> rows_f(const Json& a) {
    std::vector<std::vector<double>> out;
    for (const auto& row : a) {
        std::vector<double> r;
        for (const auto& v : row) r.push_back(num(v));
        out.push_back(std::move(r));
    }
    return out;
}

std::vector<std::vector<std::int64_t>> rows_i(const Json& a) {
    std::vector<std::vector<std::int64_t>> out;
    for (const auto& row : a) {
        std::vector<std::int64_t> r;
        for (const auto& v : row) r.push_back(v.get<std::int64_t>());
        out.push_back(std::move(r));
    }
    return out;
}

std::vector<double> vec_f(const Json& a) {
    std::vector<double> out;
    for (const auto& v : a) out.push_back(num(v));
    return out;
}

gm::HorizonGrid horizon_of(const Json& spec) {
    gm::HorizonGrid g;
    g.rows = static_cast<int>(spec.at("z_grid").size());
    g.cols = g.rows ? static_cast<int>(spec.at("z_grid")[0].size()) : 0;
    g.origin_x = spec.value("origin", Json::array({0.0, 0.0}))[0].get<double>();
    g.origin_y = spec.value("origin", Json::array({0.0, 0.0}))[1].get<double>();
    const Json sp = spec.value("spacing", Json::array({1.0, 1.0}));
    g.spacing_y = sp[0].get<double>();
    g.spacing_x = sp[1].get<double>();
    g.vertical_domain = spec.value("vertical_domain", std::string("depth"));
    g.unit = spec.value("unit", std::string("m"));
    g.object_id = spec.value("object_id", std::string("horizon:_export"));
    for (const auto& row : spec.at("z_grid"))
        for (const auto& v : row) g.z.push_back(num(v));
    return g;
}

Json export_result(const gm::ExportWritten& w, bool binary) {
    Json r;
    r["file"] = binary ? Json{{"b64", b64_encode(w.file)}} : Json(w.file);
    r["sidecar_name"] = w.sidecar_name;
    r["sidecar"] = w.sidecar;
    return r;
}

// bytes input may be text or {"b64": ...}
std::string file_bytes(const Json& v) {
    if (v.is_object() && v.contains("b64"))
        return b64_decode(v["b64"].get<std::string>());
    return v.get<std::string>();
}

std::string raise_class(const std::exception& e);

Json assembly_replay(const Json& ops) {
    Json out = Json::array();
    gm::ModelAssembly asm_;
    for (const auto& op : ops) {
        const std::string k = op.at("op").get<std::string>();
        try {
            if (k == "add") {
                out.push_back(Json{{"ok", asm_.add(gm::object_from_spec(op.at("spec"))).object_id}});
            } else if (k == "replace") {
                out.push_back(Json{{"ok", asm_.replace(gm::object_from_spec(op.at("spec"))).object_id}});
            } else if (k == "remove") {
                out.push_back(Json{{"ok", asm_.remove(op.at("object_id").get<std::string>())}});
            } else if (k == "clear") {
                out.push_back(Json{{"ok", asm_.clear(
                    op.contains("kind") && !op["kind"].is_null()
                        ? std::optional<std::string>(op["kind"].get<std::string>())
                        : std::nullopt)}});
            } else if (k == "ids") {
                Json ids = Json::array();
                for (const auto& i : asm_.ids(
                         op.contains("kind") && !op["kind"].is_null()
                             ? std::optional<std::string>(op["kind"].get<std::string>())
                             : std::nullopt))
                    ids.push_back(i);
                out.push_back(Json{{"ok", std::move(ids)}});
            } else if (k == "bump_version") {
                out.push_back(Json{{"ok", asm_.bump_version(op.at("object_id").get<std::string>()).version}});
            } else if (k == "to_meta") {
                out.push_back(Json{{"ok", asm_.to_meta()}});
            } else if (k == "apply_meta") {
                Json ids = Json::array();
                for (const auto& i : asm_.apply_meta(op.at("meta")))
                    ids.push_back(i);
                out.push_back(Json{{"ok", std::move(ids)}});
            } else {
                out.push_back(Json{{"ok", Json(nullptr)}});
            }
        } catch (const std::exception& e) {
            out.push_back(Json{{"raises", raise_class(e)},
                               {"message", e.what()}});
        }
    }
    return out;
}

std::string raise_class(const std::exception& e) {
    if (dynamic_cast<const gm::QCBlockerError*>(&e)) return "QCBlockerError";
    if (dynamic_cast<const gm::ExportError*>(&e)) return "ExportError";
    if (dynamic_cast<const gm::DomainError*>(&e)) return "DomainError";
    if (dynamic_cast<const gm::KeyError*>(&e)) return "KeyError";
    if (dynamic_cast<const gm::IndexError*>(&e)) return "IndexError";
    if (dynamic_cast<const gm::ValueError*>(&e)) return "ValueError";
    if (dynamic_cast<const gm::TypeError*>(&e)) return "TypeError";
    return "std::exception";
}

Json run_case(const Json& c) {
    const std::string fn = c.at("fn").get<std::string>();
    const Json& input = c.at("input");

    if (fn == "slugify")
        return Json(gm::slugify(input.at("text"),
                                input.value("fallback", std::string("obj"))));
    if (fn == "clean_ids") {
        Json out = Json::array();
        for (const auto& s : gm::clean_ids(input.at("ids"))) out.push_back(s);
        return out;
    }
    if (fn == "provenance_meta") {
        gm::Provenance p;
        p.source_kind = input.value("source_kind", std::string("derived"));
        for (const auto& i : input.value("source_version_ids", Json::array()))
            p.source_version_ids.push_back(i.get<std::string>());
        p.created_from = input.value("created_from", std::string(""));
        p.demo = input.value("demo", false);
        return p.to_meta();
    }
    if (fn == "provenance_from_meta")
        return gm::Provenance::from_meta(input.at("meta")).to_meta();
    if (fn == "make_object")
        return gm::object_from_spec(input).meta();
    if (fn == "object_from_meta")
        return gm::DomainObject::from_meta(input.at("meta")).meta();
    if (fn == "geometry_stats")
        return gm::geometry_stats(gm::object_from_spec(input));
    if (fn == "assembly_ops")
        return assembly_replay(input.at("ops"));
    if (fn == "qc_object") {
        gm::DomainObject o = gm::object_from_spec(input);
        if (input.contains("_mutate")) gm::apply_mutations(o, input);
        return gm::qc_object(o).to_meta();
    }
    if (fn == "qc_assembly") {
        gm::ModelAssembly asm_;
        for (const auto& s : input.at("objects"))
            asm_.add(gm::object_from_spec(s));
        std::optional<std::unordered_set<std::string>> known;
        if (input.contains("known") && input["known"].is_array()) {
            known.emplace();
            for (const auto& i : input["known"]) known->insert(i.get<std::string>());
        }
        return gm::qc_assembly(asm_, known).to_meta();
    }
    if (fn == "assert_exportable") {
        std::vector<gm::DomainObject> objs;
        for (const auto& s : input.at("objects"))
            objs.push_back(gm::object_from_spec(s));
        std::optional<gm::QCReport> rep;
        if (input.contains("report") && input["report"] == "empty")
            rep = gm::QCReport{};
        return gm::assert_exportable(objs, rep).to_meta();
    }
    if (fn == "check_boreholes")
        return gm::check_boreholes(input.at("records"));
    if (fn == "check_coplanar_faults")
        return gm::check_coplanar_faults(input.at("records"));
    if (fn == "lithology_tables")
        return gm::lithology_tables();
    if (fn == "sample_log_values")
        return gm::sample_log_values(
            input.at("layers"), input.at("depths"),
            input.at("table").get<std::string>(),
            input.value("default", 0.0));
    if (fn == "build_well_trajectory") {
        const std::string crs = input.value("crs", std::string("unknown"));
        return gm::build_well_trajectory(
                   input.at("name").get<std::string>(),
                   rows_f(input.at("stations")), crs, "m", "depth", "",
                   {}, std::nullopt,
                   input.contains("object_id")
                       ? std::optional<std::string>(
                             input["object_id"].get<std::string>())
                       : std::nullopt)
            .meta();
    }
    if (fn == "build_simplified_vertical_well") {
        return gm::build_simplified_vertical_well(
                   input.at("name").get<std::string>(),
                   vec_f(input.at("head_xyz")),
                   input.at("total_depth").get<double>(),
                   input.value("crs", std::string("unknown")), "m",
                   input.value("vertical_domain", std::string("depth")))
            .meta();
    }
    if (fn == "build_fault_from_mesh") {
        std::optional<double> throw_m;
        if (input.contains("throw_m") && !input["throw_m"].is_null())
            throw_m = input["throw_m"].get<double>();
        std::optional<std::array<double, 2>> sd;
        if (input.contains("strike_dip") && !input["strike_dip"].is_null())
            sd = {input["strike_dip"][0].get<double>(),
                  input["strike_dip"][1].get<double>()};
        return gm::build_fault_from_mesh(
                   input.at("name").get<std::string>(),
                   rows_f(input.at("verts")), rows_i(input.at("faces")),
                   input.value("crs", std::string("unknown")), "m", "depth",
                   throw_m, sd)
            .meta();
    }
    if (fn == "export_flac3d" || fn == "export_abaqus") {
        const gm::DomainObject vol = gm::object_from_spec(input.at("spec"));
        std::optional<gm::HorizonGrid> top, base;
        if (input.contains("top_spec") && !input["top_spec"].is_null())
            top = horizon_of(input["top_spec"]);
        if (input.contains("base_spec") && !input["base_spec"].is_null())
            base = horizon_of(input["base_spec"]);
        const int n_layers = input.value("n_layers", 4);
        const std::string name = input.at("name").get<std::string>();
        gm::ExportWritten w =
            fn == "export_flac3d"
                ? gm::export_volume_flac3d(
                      vol, name, top, base, n_layers,
                      input.value("zone_name", std::string("GEOMODEL")))
                : gm::export_volume_abaqus(
                      vol, name, top, base, n_layers,
                      input.value("part_name", std::string("GEOMODEL")));
        return export_result(w, false);
    }
    if (fn == "export_obj") {
        std::optional<std::string> label;
        if (input.contains("label") && !input["label"].is_null())
            label = input["label"].get<std::string>();
        return export_result(
            gm::export_mesh_obj(gm::object_from_spec(input.at("spec")),
                                input.at("name").get<std::string>(), label),
            false);
    }
    if (fn == "export_stl")
        return export_result(
            gm::export_mesh_stl(gm::object_from_spec(input.at("spec")),
                                input.at("name").get<std::string>()),
            true);
    if (fn == "export_vtp") {
        std::vector<std::pair<std::string, std::vector<double>>> pd;
        if (input.contains("point_data") && input["point_data"].is_object())
            for (auto it = input["point_data"].begin();
                 it != input["point_data"].end(); ++it) {
                std::vector<double> vals;
                for (const auto& v : it.value()) vals.push_back(num(v));
                pd.emplace_back(it.key(), std::move(vals));
            }
        return export_result(
            gm::export_mesh_vtp(gm::object_from_spec(input.at("spec")),
                                input.at("name").get<std::string>(), pd),
            false);
    }
    if (fn == "read_flac3d_grid")
        return gm::read_flac3d_grid(input.at("text").get<std::string>(),
                                    input.at("name").get<std::string>());
    if (fn == "read_abaqus_inp")
        return gm::read_abaqus_inp(input.at("text").get<std::string>(),
                                   input.at("name").get<std::string>());
    if (fn == "read_obj")
        return gm::read_obj(input.at("text").get<std::string>(),
                            input.at("name").get<std::string>());
    if (fn == "read_stl")
        return gm::read_stl(file_bytes(input.at("b64")),
                            input.at("name").get<std::string>());
    if (fn == "read_vtp")
        return gm::read_vtp(input.at("text").get<std::string>(),
                            input.at("name").get<std::string>());
    if (fn == "validate_export")
        return gm::validate_export(input.at("name").get<std::string>(),
                                   file_bytes(input.at("file")),
                                   gm::object_from_spec(input.at("spec")));
    if (fn == "structured_grid") {
        const auto g = gm::generate_structured_grid(
            input.at("nx").get<int>(), input.at("ny").get<int>(),
            input.at("nz").get<int>(), input.at("dx").get<double>(),
            input.at("dy").get<double>(), input.at("dz").get<double>());
        Json nodes = Json::array();
        for (const auto& p : g.nodes)
            nodes.push_back(Json::array({p[0], p[1], p[2]}));
        Json elems = Json::array();
        for (const auto& e : g.elements) {
            Json row = Json::array();
            for (auto i : e) row.push_back(i);
            elems.push_back(std::move(row));
        }
        return Json{{"nodes", std::move(nodes)},
                    {"elements", std::move(elems)}};
    }
    if (fn == "export_to_flac3d")
        return Json{{"result", true},
                    {"file", gm::legacy_export_to_flac3d(
                                 input.at("nx").get<int>(),
                                 input.at("ny").get<int>(),
                                 input.at("nz").get<int>(),
                                 input.at("dx").get<double>(),
                                 input.at("dy").get<double>(),
                                 input.at("dz").get<double>())}};
    if (fn == "export_to_abaqus")
        return Json{{"result", true},
                    {"file", gm::legacy_export_to_abaqus(
                                 input.at("nx").get<int>(),
                                 input.at("ny").get<int>(),
                                 input.at("nz").get<int>(),
                                 input.at("dx").get<double>(),
                                 input.at("dy").get<double>(),
                                 input.at("dz").get<double>())}};
    throw std::runtime_error("unknown fn: " + fn);
}

}  // namespace

int main() {
    const std::string fixture_path = PWB_CONTRACTS_FIXTURE;
    std::ifstream in(fixture_path);
    if (!in) {
        std::fprintf(stderr, "cannot open fixture %s\n", fixture_path.c_str());
        return 2;
    }
    std::ostringstream buf;
    buf << in.rdbuf();
    const Json doc = Json::parse(buf.str());

    for (const Json& c : doc.at("cases")) {
        const std::string id = c.at("id").get<std::string>();
        const Json& expect = c.at("expect");
        try {
            const Json result = run_case(c);
            if (expect.contains("raises") && !expect.at("raises").is_null()) {
                check(false, id + " expected raise " +
                                 expect.at("raises").get<std::string>() +
                                 " but got result " +
                                 result.dump().substr(0, 200));
            } else if (!sem_eq(result, expect.at("result"))) {
                const auto diff = pwb::domain::json_semantic_diff(
                    norm(result), norm(expect.at("result")));
                check(false, id + " mismatch at " + diff.path + ": got " +
                             result.dump().substr(0, 240));
            }
        } catch (const std::exception& e) {
            const std::string cls = raise_class(e);
            if (!expect.contains("raises") || expect.at("raises").is_null()) {
                check(false, id + " unexpected raise " + cls + ": " +
                             e.what());
                continue;
            }
            check(cls == expect.at("raises").get<std::string>(),
                  id + " raise class " + cls +
                      " != " + expect.at("raises").get<std::string>());
            check(std::string(e.what()) ==
                      expect.at("message").get<std::string>(),
                  id + " message '" + std::string(e.what()) + "' != '" +
                      expect.at("message").get<std::string>() + "'");
        }
    }

    std::printf("geomodel.contracts: %d checks, %d failures\n", g_checks,
                g_failures);
    return g_failures ? 1 : 0;
}
