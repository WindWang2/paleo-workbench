#include <pwb/geomodel/export_contract.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <set>

#include <pwb/ingest/py_compat.hpp>     // decode_utf8
#include <pwb/ingest/xml_scanner.hpp>   // XmlNode / xml_parse / XmlError

namespace pwb::geomodel {

namespace {

// f"{v:.Nf}" — printf %.*f is already round-half-even under FE_TONEAREST.
std::string fx(double v, int decimals) {
    char buf[64];
    std::snprintf(buf, sizeof buf, "%.*f", decimals, v);
    return buf;
}

std::string gx(double v) {  // f"{v:.6g}"
    char buf[64];
    std::snprintf(buf, sizeof buf, "%.6g", v);
    return buf;
}

// Path.stem — basename after the last separator, minus the last extension
// (leading dots are not extensions, like pathlib).
std::string stem_of(const std::string& name) {
    const std::size_t slash = name.find_last_of("/\\");
    const std::string base =
        slash == std::string::npos ? name : name.substr(slash + 1);
    const std::size_t dot = base.rfind('.');
    if (dot == std::string::npos || dot == 0) return base;
    return base.substr(0, dot);
}

// Path.suffix.lower()
std::string suffix_of(const std::string& name) {
    const std::size_t slash = name.find_last_of("/\\");
    const std::string base =
        slash == std::string::npos ? name : name.substr(slash + 1);
    const std::size_t dot = base.rfind('.');
    std::string s = (dot == std::string::npos || dot == 0)
                        ? ""
                        : base.substr(dot);
    for (auto& c : s)
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

// _mesh_of — only fault/volume carry triangle meshes.
const std::vector<std::array<std::int64_t, 3>>& mesh_faces(
    const DomainObject& o, std::vector<Vec3>& v_out) {
    const std::string k = o.kind();
    if (k != "fault" && k != "volume")
        throw ExportError(o.object_id +
                          ": object kind has no triangle mesh to export");
    v_out = o.verts;
    return o.faces;
}

Json mesh_info_meta(const HexMeshInfo& i) {
    return Json{{"n_cells", i.n_cells},
                {"n_layers", i.n_layers},
                {"n_hexes", i.n_hexes},
                {"skipped_crossed", i.skipped_crossed},
                {"unit", i.unit},
                {"merge", i.merge}};
}

Json sidecar_of(const DomainObject& obj, const std::string& fmt,
                const Json& extra, const QCReport* report) {
    Json s;
    s["format"] = fmt;
    s["object_id"] = obj.object_id;
    s["name"] = obj.name;
    s["crs"] = obj.crs;
    s["vertical_domain"] = obj.vertical_domain;
    s["unit"] = obj.unit;
    s["provenance"] = obj.provenance.to_meta();
    s["indexing"] = "node/element ids are 1-based in file, 0-based in numpy";
    if (extra.is_object())
        for (auto it = extra.begin(); it != extra.end(); ++it)
            s[it.key()] = it.value();
    if (report) s["qc"] = report->to_meta();
    return s;
}

// np.round(x, 9) — multiply, rint (half-even), divide.
double round9(double v) {
    return std::nearbyint(v * 1e9) / 1e9;
}

std::vector<double> unique_sorted(std::vector<double> v) {
    std::sort(v.begin(), v.end());
    v.erase(std::unique(v.begin(), v.end(),
                        [](double a, double b) { return a == b; }),
            v.end());
    return v;
}

// np.searchsorted(sorted_asc, v, side='left')
std::size_t searchsorted(const std::vector<double>& s, double v) {
    return static_cast<std::size_t>(
        std::lower_bound(s.begin(), s.end(), v) - s.begin());
}

double median(std::vector<double> v) {
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    const std::size_t n = v.size();
    if (n % 2) return v[n / 2];
    return (v[n / 2 - 1] + v[n / 2]) / 2.0;
}

// python round() — banker's via rint
long long py_round(double v) {
    return static_cast<long long>(std::nearbyint(v));
}

}  // namespace

std::pair<HorizonGrid, HorizonGrid> sheet_horizons(
    const DomainObject& volume, const std::optional<HorizonGrid>& top,
    const std::optional<HorizonGrid>& base) {
    if (top && base) return {*top, *base};

    auto regrid = [&](bool is_top) -> HorizonGrid {
        const std::size_t nh = volume.verts.size() / 2;
        const std::size_t lo = is_top ? 0 : nh;
        const std::size_t hi = is_top ? nh : volume.verts.size();
        if (volume.verts.empty())
            throw ExportError(volume.object_id + ": empty shell");
        std::vector<double> xs, ys;
        xs.reserve(hi - lo);
        ys.reserve(hi - lo);
        for (std::size_t i = lo; i < hi; ++i) {
            xs.push_back(round9(volume.verts[i][0]));
            ys.push_back(round9(volume.verts[i][1]));
        }
        const std::vector<double> ux = unique_sorted(xs);
        const std::vector<double> uy = unique_sorted(ys);
        HorizonGrid g;
        g.vertical_domain = volume.vertical_domain;
        g.unit = volume.unit;
        g.object_id = "horizon:_export_" + volume.object_id +
                      (is_top ? "_top" : "_base");
        if (ux.size() * uy.size() == hi - lo) {
            // lattice shell: z indexed by searchsorted position
            g.rows = static_cast<int>(uy.size());
            g.cols = static_cast<int>(ux.size());
            g.z.assign(static_cast<std::size_t>(g.rows) *
                           static_cast<std::size_t>(g.cols),
                       std::numeric_limits<double>::quiet_NaN());
            for (std::size_t i = lo; i < hi; ++i) {
                const std::size_t zi = searchsorted(uy, volume.verts[i][1]);
                const std::size_t zj = searchsorted(ux, volume.verts[i][0]);
                g.z[zi * static_cast<std::size_t>(g.cols) + zj] =
                    volume.verts[i][2];
            }
            g.origin_x = ux[0];
            g.origin_y = uy[0];
            g.spacing_y = uy.size() > 1 ? uy[1] - uy[0] : 1.0;
            g.spacing_x = ux.size() > 1 ? ux[1] - ux[0] : 1.0;
        } else {
            double x0 = volume.verts[lo][0], y0 = volume.verts[lo][1];
            double x1 = x0, y1 = y0;
            for (std::size_t i = lo; i < hi; ++i) {
                x0 = std::min(x0, volume.verts[i][0]);
                y0 = std::min(y0, volume.verts[i][1]);
                x1 = std::max(x1, volume.verts[i][0]);
                y1 = std::max(y1, volume.verts[i][1]);
            }
            std::vector<double> dx(ux.begin() + 1, ux.end());
            for (std::size_t i = 0; i < dx.size(); ++i) dx[i] -= ux[i];
            std::vector<double> dy(uy.begin() + 1, uy.end());
            for (std::size_t i = 0; i < dy.size(); ++i) dy[i] -= uy[i];
            const double sx = ux.size() > 1 ? median(dx) : 1.0;
            const double sy = uy.size() > 1 ? median(dy) : 1.0;
            const int nx = static_cast<int>(
                py_round((x1 - x0) / std::max(sx, 1e-12))) + 1;
            const int ny = static_cast<int>(
                py_round((y1 - y0) / std::max(sy, 1e-12))) + 1;
            g.rows = ny;
            g.cols = nx;
            g.z.assign(static_cast<std::size_t>(ny) *
                           static_cast<std::size_t>(nx),
                       std::numeric_limits<double>::quiet_NaN());
            for (std::size_t i = lo; i < hi; ++i) {
                const long long zi = py_round(
                    (volume.verts[i][1] - y0) / std::max(sy, 1e-12));
                const long long zj = py_round(
                    (volume.verts[i][0] - x0) / std::max(sx, 1e-12));
                g.z[static_cast<std::size_t>(zi) *
                        static_cast<std::size_t>(nx) +
                    static_cast<std::size_t>(zj)] = volume.verts[i][2];
            }
            g.origin_x = x0;
            g.origin_y = y0;
            g.spacing_y = sy;
            g.spacing_x = sx;
        }
        return g;
    };
    return {regrid(true), regrid(false)};
}

// ---------------------------------------------------------------------------
// V2 exporters
// ---------------------------------------------------------------------------

ExportWritten export_volume_flac3d(
    const DomainObject& volume, const std::string& out_name,
    const std::optional<HorizonGrid>& top,
    const std::optional<HorizonGrid>& base, int n_layers,
    const std::string& zone_name) {
    assert_exportable({volume});
    if (!volume.boundary)
        throw ExportError(volume.object_id +
                          ": volume has no boundary polygon");
    const auto [tg, bg] = sheet_horizons(volume, top, base);
    const HexMesh m =
        build_columnar_hex_mesh(tg, bg, *volume.boundary, n_layers);
    if (m.hexes.empty())
        throw ExportError(volume.object_id + ": no valid columns to export");

    std::string f = "* FLAC3D grid exported by PaleoWorkbench\n";
    f += "* object: " + volume.object_id + " (" + volume.name +
         ") cells=" + std::to_string(m.hexes.size()) +
         " nodes=" + std::to_string(m.nodes.size()) + "\n";
    f += "* CRS: " + volume.crs + "  unit: " + volume.unit + "\n";
    for (std::size_t i = 0; i < m.nodes.size(); ++i) {
        const Vec3& p = m.nodes[i];
        f += "G " + std::to_string(i + 1) + " " + fx(p[0], 4) + " " +
             fx(p[1], 4) + " " + fx(p[2], 4) + "\n";
    }
    for (std::size_t i = 0; i < m.hexes.size(); ++i) {
        f += "Z B8 " + std::to_string(i + 1);
        for (auto id : m.hexes[i]) f += " " + std::to_string(id + 1);
        f += "\n";
    }
    const QCReport rep = qc_object(volume);
    return {std::move(f), stem_of(out_name) + ".provenance.json",
            sidecar_of(volume, "flac3d-grid",
                       Json{{"zone_name", zone_name},
                            {"mesh", mesh_info_meta(m.info)}},
                       &rep)};
}

ExportWritten export_volume_abaqus(
    const DomainObject& volume, const std::string& out_name,
    const std::optional<HorizonGrid>& top,
    const std::optional<HorizonGrid>& base, int n_layers,
    const std::string& part_name) {
    assert_exportable({volume});
    if (!volume.boundary)
        throw ExportError(volume.object_id +
                          ": volume has no boundary polygon");
    const auto [tg, bg] = sheet_horizons(volume, top, base);
    const HexMesh m =
        build_columnar_hex_mesh(tg, bg, *volume.boundary, n_layers);
    if (m.hexes.empty())
        throw ExportError(volume.object_id + ": no valid columns to export");

    std::string f = "*HEADING\n";
    f += "** PaleoWorkbench export: " + volume.object_id + " (" +
         volume.name + ")\n";
    f += "** CRS: " + volume.crs + "  unit: " + volume.unit + "\n";
    f += "*PART, NAME=" + part_name + "\n";
    f += "*NODE\n";
    for (std::size_t i = 0; i < m.nodes.size(); ++i) {
        const Vec3& p = m.nodes[i];
        f += std::to_string(i + 1) + ", " + fx(p[0], 4) + ", " +
             fx(p[1], 4) + ", " + fx(p[2], 4) + "\n";
    }
    f += "*ELEMENT, TYPE=C3D8, ELSET=EALL\n";
    for (std::size_t i = 0; i < m.hexes.size(); ++i) {
        f += std::to_string(i + 1);
        for (auto id : m.hexes[i]) f += ", " + std::to_string(id + 1);
        f += "\n";
    }
    f += "*END PART\n";
    const QCReport rep = qc_object(volume);
    return {std::move(f), stem_of(out_name) + ".provenance.json",
            sidecar_of(volume, "abaqus-inp",
                       Json{{"part_name", part_name},
                            {"mesh", mesh_info_meta(m.info)}},
                       &rep)};
}

ExportWritten export_mesh_obj(const DomainObject& obj,
                              const std::string& out_name,
                              const std::optional<std::string>& label) {
    std::vector<Vec3> verts;
    const auto& faces = mesh_faces(obj, verts);
    assert_exportable({obj});
    if (faces.empty())
        throw ExportError(obj.object_id + ": no triangles to export");
    std::string f = "# PaleoWorkbench OBJ export: " + obj.object_id + " (" +
                    obj.name + ")\n";
    f += "# CRS: " + obj.crs + "  unit: " + obj.unit + "\n";
    f += "o " + (label ? *label : obj.name) + "\n";
    for (const Vec3& p : verts)
        f += "v " + fx(p[0], 6) + " " + fx(p[1], 6) + " " + fx(p[2], 6) +
             "\n";
    for (const auto& t : faces)
        f += "f " + std::to_string(t[0] + 1) + " " +
             std::to_string(t[1] + 1) + " " + std::to_string(t[2] + 1) +
             "\n";
    const QCReport rep = qc_object(obj);
    return {std::move(f), stem_of(out_name) + ".provenance.json",
            sidecar_of(obj, "obj",
                       Json{{"triangles",
                             static_cast<long long>(faces.size())}},
                       &rep)};
}

namespace {
void put_u32(std::string& out, std::uint32_t v) {
    char b[4] = {static_cast<char>(v & 0xFF),
                 static_cast<char>((v >> 8) & 0xFF),
                 static_cast<char>((v >> 16) & 0xFF),
                 static_cast<char>((v >> 24) & 0xFF)};
    out.append(b, 4);
}
void put_u16(std::string& out, std::uint16_t v) {
    char b[2] = {static_cast<char>(v & 0xFF),
                 static_cast<char>((v >> 8) & 0xFF)};
    out.append(b, 2);
}
void put_f32(std::string& out, float f) {
    std::uint32_t u;
    std::memcpy(&u, &f, 4);
    put_u32(out, u);
}
}  // namespace

ExportWritten export_mesh_stl(const DomainObject& obj,
                              const std::string& out_name) {
    std::vector<Vec3> verts;
    const auto& faces = mesh_faces(obj, verts);
    assert_exportable({obj});
    if (faces.empty())
        throw ExportError(obj.object_id + ": no triangles to export");

    std::string header = "PaleoWorkbench STL export: " + obj.object_id;
    std::string ascii;
    ascii.reserve(header.size());
    for (const unsigned char ch : header)
        ascii.push_back(ch < 0x80 ? static_cast<char>(ch) : '?');
    ascii.resize(80, '\0');

    std::string f = ascii;
    put_u32(f, static_cast<std::uint32_t>(faces.size()));
    for (const auto& t : faces) {
        const Vec3& a = verts[t[0]];
        const Vec3& b = verts[t[1]];
        const Vec3& c = verts[t[2]];
        const double ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
        const double vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
        double nx = uy * vz - uz * vy;
        double ny = uz * vx - ux * vz;
        double nz = ux * vy - uy * vx;
        const double len =
            std::sqrt(nx * nx + ny * ny + nz * nz);
        if (len > 0) {
            nx /= len;
            ny /= len;
            nz /= len;
        }
        put_f32(f, static_cast<float>(nx));
        put_f32(f, static_cast<float>(ny));
        put_f32(f, static_cast<float>(nz));
        for (const Vec3* p : {&a, &b, &c})
            for (int k = 0; k < 3; ++k)
                put_f32(f, static_cast<float>((*p)[k]));
        put_u16(f, 0);
    }
    const QCReport rep = qc_object(obj);
    return {std::move(f), stem_of(out_name) + ".provenance.json",
            sidecar_of(obj, "stl-binary",
                       Json{{"triangles",
                             static_cast<long long>(faces.size())}},
                       &rep)};
}

// --- tiny ElementTree-compatible emitter (what ET.write produces) ---------
namespace {

struct XmlEl {
    std::string tag;
    std::vector<std::pair<std::string, std::string>> attrs;
    std::string text;
    std::string tail;
    std::vector<XmlEl> children;
};

std::string esc_attr(const std::string& s) {
    std::string o;
    for (const char ch : s) {
        switch (ch) {
            case '&': o += "&amp;"; break;
            case '<': o += "&lt;"; break;
            case '>': o += "&gt;"; break;
            case '"': o += "&quot;"; break;
            case '\n': o += "&#10;"; break;
            case '\r': o += "&#13;"; break;
            case '\t': o += "&#9;"; break;
            default: o += ch;
        }
    }
    return o;
}

std::string esc_text(const std::string& s) {
    std::string o;
    for (const char ch : s) {
        switch (ch) {
            case '&': o += "&amp;"; break;
            case '<': o += "&lt;"; break;
            case '>': o += "&gt;"; break;
            default: o += ch;
        }
    }
    return o;
}

// ET.indent(tree, space="  ") — every element with children gets its text
// set to child_indentation; each child's tail is set to child_indentation,
// then the LAST child's tail is pulled back to the parent's level.
void indent_children(XmlEl& el, int level, const std::string& space) {
    if (el.children.empty()) return;
    const auto spaces = [&](int n) {
        std::string s;
        for (int i = 0; i < n; ++i) s += space;
        return s;
    };
    const std::string child_indent = "\n" + spaces(level + 1);
    if (el.text.empty() || el.text.find_first_not_of(" \t\n") ==
                               std::string::npos)
        el.text = child_indent;
    for (auto& ch : el.children) {
        indent_children(ch, level + 1, space);
        if (ch.tail.empty() || ch.tail.find_first_not_of(" \t\n") ==
                                   std::string::npos)
            ch.tail = child_indent;
    }
    XmlEl& last = el.children.back();
    if (last.tail.empty() || last.tail.find_first_not_of(" \t\n") ==
                                   std::string::npos)
        last.tail = "\n" + spaces(level);
}

std::string emit_el(const XmlEl& el) {
    std::string o = "<" + el.tag;
    for (const auto& [k, v] : el.attrs)
        o += " " + k + "=\"" + esc_attr(v) + "\"";
    if (el.children.empty() && el.text.empty()) return o + " />" + el.tail;
    o += ">";
    o += esc_text(el.text);
    for (const auto& ch : el.children) o += emit_el(ch);
    o += "</" + el.tag + ">" + el.tail;
    return o;
}

std::string emit_xml(const XmlEl& root) {
    return "<?xml version='1.0' encoding='utf-8'?>\n" + emit_el(root);
}

}  // namespace

ExportWritten export_mesh_vtp(
    const DomainObject& obj, const std::string& out_name,
    const std::vector<std::pair<std::string, std::vector<double>>>&
        point_data) {
    std::vector<Vec3> verts;
    const auto& faces = mesh_faces(obj, verts);
    assert_exportable({obj});
    if (faces.empty())
        throw ExportError(obj.object_id + ": no triangles to export");

    std::string pts;
    for (const Vec3& p : verts)
        for (int k = 0; k < 3; ++k) {
            if (!pts.empty()) pts += " ";
            pts += fx(p[k], 6);
        }
    std::string conn, offs;
    for (std::size_t i = 0; i < faces.size(); ++i) {
        for (int k = 0; k < 3; ++k) {
            if (!conn.empty()) conn += " ";
            conn += std::to_string(faces[i][k]);
        }
        if (!offs.empty()) offs += " ";
        offs += std::to_string(3 * (i + 1));
    }

    XmlEl root{"VTKFile",
               {{"type", "PolyData"},
                {"version", "0.1"},
                {"byte_order", "LittleEndian"}},
               "", "", {}};
    XmlEl poly{"PolyData", {}, "", "", {}};
    XmlEl piece{"Piece",
                {{"NumberOfPoints", std::to_string(verts.size())},
                 {"NumberOfPolys", std::to_string(faces.size())}},
                "", "", {}};
    XmlEl points{"Points", {}, "", "", {}};
    points.children.push_back(
        {"DataArray",
         {{"type", "Float64"}, {"Name", "Points"},
          {"NumberOfComponents", "3"}, {"format", "ascii"}},
         pts, "", {}});
    XmlEl polys{"Polys", {}, "", "", {}};
    polys.children.push_back(
        {"DataArray",
         {{"type", "Int64"}, {"Name", "connectivity"}, {"format", "ascii"}},
         conn, "", {}});
    polys.children.push_back(
        {"DataArray",
         {{"type", "Int64"}, {"Name", "offsets"}, {"format", "ascii"}},
         offs, "", {}});
    piece.children.push_back(std::move(points));
    piece.children.push_back(std::move(polys));
    Json pd_names = Json::array();
    if (!point_data.empty()) {
        XmlEl pd{"PointData", {}, "", "", {}};
        for (const auto& [name, vals] : point_data) {
            if (vals.size() != verts.size())
                throw ExportError("point_data " + py_repr(Json(name)) +
                                  " length " + std::to_string(vals.size()) +
                                  " != vertices " +
                                  std::to_string(verts.size()));
            std::string txt;
            for (double v : vals) {
                if (!txt.empty()) txt += " ";
                txt += gx(v);
            }
            pd.children.push_back(
                {"DataArray",
                 {{"type", "Float64"}, {"Name", name},
                  {"NumberOfComponents", "1"}, {"format", "ascii"}},
                 txt, "", {}});
            pd_names.push_back(name);
        }
        piece.children.push_back(std::move(pd));
    }
    poly.children.push_back(std::move(piece));
    root.children.push_back(std::move(poly));
    indent_children(root, 0, "  ");

    const QCReport rep = qc_object(obj);
    return {emit_xml(root), stem_of(out_name) + ".provenance.json",
            sidecar_of(obj, "vtk-polydata-xml",
                       Json{{"point_data", std::move(pd_names)}}, &rep)};
}

// ---------------------------------------------------------------------------
// parser validators
// ---------------------------------------------------------------------------

namespace {

// str.split() — runs of ASCII whitespace, no empty tokens.
std::vector<std::string> split_ws(std::string_view s) {
    std::vector<std::string> out;
    std::size_t i = 0;
    while (i < s.size()) {
        while (i < s.size() && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' ||
                                s[i] == '\r' || s[i] == '\v' || s[i] == '\f'))
            ++i;
        std::size_t j = i;
        while (j < s.size() && !(s[j] == ' ' || s[j] == '\t' || s[j] == '\n' ||
                                 s[j] == '\r' || s[j] == '\v' || s[j] == '\f'))
            ++j;
        if (j > i) out.emplace_back(s.substr(i, j - i));
        i = j;
    }
    return out;
}

// str.splitlines() — \n, \r\n, \r boundaries.
std::vector<std::string> split_lines(std::string_view s) {
    std::vector<std::string> out;
    std::size_t i = 0;
    while (i < s.size()) {
        std::size_t j = i;
        while (j < s.size() && s[j] != '\n' && s[j] != '\r') ++j;
        out.emplace_back(s.substr(i, j - i));
        if (j < s.size()) {
            if (s[j] == '\r' && j + 1 < s.size() && s[j + 1] == '\n') ++j;
            ++j;
        }
        i = j;
    }
    return out;
}

long long parse_int(const std::string& tok) { return py_int(Json(tok)); }
double parse_flt(const std::string& tok) { return py_float(Json(tok)); }

// np.allclose(a, b, atol=1e-4) — rtol stays at numpy's 1e-5 default.
bool allclose(const Vec3& a, const Vec3& b, double atol) {
    for (int k = 0; k < 3; ++k)
        if (std::abs(a[k] - b[k]) > atol + 1e-5 * std::abs(b[k]))
            return false;
    return true;
}

Vec3 bounds_min(const std::vector<Vec3>& v) {
    Vec3 m = v[0];
    for (const Vec3& p : v)
        for (int k = 0; k < 3; ++k) m[k] = std::min(m[k], p[k]);
    return m;
}
Vec3 bounds_max(const std::vector<Vec3>& v) {
    Vec3 m = v[0];
    for (const Vec3& p : v)
        for (int k = 0; k < 3; ++k) m[k] = std::max(m[k], p[k]);
    return m;
}

// --- ET find subset: ".//A/B[@Name='x']" -----------------------------------
const ingest::XmlNode* find_desc(const ingest::XmlNode& n,
                                 const std::string& tag) {
    for (const auto& ch : n.children) {
        if (ch->tag == tag) return ch.get();
        if (const auto* d = find_desc(*ch, tag)) return d;
    }
    return nullptr;
}

// first DataArray child (optionally Name-filtered) of the first descendant
// named `container` — piece.find(".//Polys/DataArray[@Name='x']").
const ingest::XmlNode* find_da(const ingest::XmlNode& piece,
                               const std::string& container,
                               const std::string& name) {
    const ingest::XmlNode* c = find_desc(piece, container);
    if (!c) return nullptr;
    for (const auto& ch : c->children) {
        if (ch->tag != "DataArray") continue;
        if (name.empty()) return ch.get();
        const std::string* nm = ch->attr("Name");
        if (nm && *nm == name) return ch.get();
    }
    // keep searching further containers in document order
    for (const auto& ch : piece.children) {
        if (ch.get() == c) continue;
    }
    return nullptr;
}

void collect_da(const ingest::XmlNode& n, const std::string& container,
                std::vector<const ingest::XmlNode*>& out) {
    for (const auto& ch : n.children) {
        if (ch->tag == container) {
            for (const auto& da : ch->children)
                if (da->tag == "DataArray") out.push_back(da.get());
        }
        collect_da(*ch, container, out);
    }
}

std::string node_text(const ingest::XmlNode* n) {
    return n ? n->text : std::string();
}

// expat-style "line L, column C" for the XmlError — the reported position
// is the start of the offending token (the last '<' for the malformed
// inputs expat surfaces in this grammar).
std::string expat_position(std::string_view text) {
    const std::size_t pos = text.rfind('<');
    const std::size_t p = pos == std::string_view::npos ? 0 : pos;
    long long line = 1, col = 0;
    for (std::size_t i = 0; i < p; ++i) {
        if (text[i] == '\n') { ++line; col = 0; }
        else ++col;
    }
    return "line " + std::to_string(line) + ", column " + std::to_string(col);
}

}  // namespace

Json read_flac3d_grid(std::string_view text, const std::string& name) {
    std::map<long long, Vec3> nodes;
    std::vector<std::pair<long long, std::array<long long, 8>>> zones;
    for (const std::string& line : split_lines(text)) {
        const auto parts = split_ws(line);
        if (parts.empty()) continue;
        if (parts[0] == "G" && parts.size() >= 5) {
            nodes[parse_int(parts[1])] = Vec3{parse_flt(parts[2]),
                                              parse_flt(parts[3]),
                                              parse_flt(parts[4])};
        } else if (parts[0] == "Z" && parts.size() >= 11 &&
                   parts[1] == "B8") {
            std::array<long long, 8> ids{};
            for (int k = 0; k < 8; ++k) ids[k] = parse_int(parts[3 + k]);
            zones.emplace_back(parse_int(parts[2]), ids);
        }
    }
    if (nodes.empty() || zones.empty())
        throw ExportError(name + ": no G/Z B8 records parsed");
    for (const auto& [zid, ids] : zones) {
        const auto mm = std::minmax_element(ids.begin(), ids.end());
        if (*mm.first < 1 ||
            *mm.second > static_cast<long long>(nodes.size()))
            throw ExportError(name + ": zone references missing gridpoint");
    }
    Json jn = Json::array();
    for (const auto& [id, p] : nodes)
        jn.push_back(Json::array({p[0], p[1], p[2]}));
    Json jz = Json::array();
    for (const auto& [zid, ids] : zones) {
        Json e = Json::array();
        e.push_back(zid);
        Json a = Json::array();
        for (auto i : ids) a.push_back(i);
        e.push_back(std::move(a));
        jz.push_back(std::move(e));
    }
    return Json{{"node_count", static_cast<long long>(nodes.size())},
                {"zone_count", static_cast<long long>(zones.size())},
                {"nodes", std::move(jn)},
                {"zones", std::move(jz)}};
}

Json read_abaqus_inp(std::string_view text, const std::string& name) {
    std::map<long long, Vec3> nodes;
    std::vector<std::pair<long long, std::array<long long, 8>>> elems;
    enum class Sec { None, Node, Element } sec = Sec::None;
    for (const std::string& raw : split_lines(text)) {
        const std::string line = py_strip(raw);
        std::string upper = line;
        for (auto& c : upper)
            c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
        if (upper.rfind("*NODE", 0) == 0) { sec = Sec::Node; continue; }
        if (upper.rfind("*ELEMENT", 0) == 0) {
            if (upper.find("C3D8") == std::string::npos)
                throw ExportError(name + ": unexpected element type line " +
                                  py_repr(Json(line)));
            sec = Sec::Element;
            continue;
        }
        if (!line.empty() && line[0] == '*') { sec = Sec::None; continue; }
        if (line.empty() || line.rfind("**", 0) == 0) continue;
        std::vector<std::string> parts;
        std::size_t i = 0;
        while (i <= line.size()) {
            const std::size_t comma = line.find(',', i);
            const std::string p =
                py_strip(line.substr(i, comma == std::string::npos
                                              ? std::string::npos
                                              : comma - i));
            if (!p.empty()) parts.push_back(p);
            if (comma == std::string::npos) break;
            i = comma + 1;
        }
        if (sec == Sec::Node && parts.size() == 4) {
            nodes[parse_int(parts[0])] = Vec3{parse_flt(parts[1]),
                                              parse_flt(parts[2]),
                                              parse_flt(parts[3])};
        } else if (sec == Sec::Element && parts.size() == 9) {
            std::array<long long, 8> ids{};
            for (int k = 0; k < 8; ++k) ids[k] = parse_int(parts[1 + k]);
            elems.emplace_back(parse_int(parts[0]), ids);
        }
    }
    if (nodes.empty() || elems.empty())
        throw ExportError(name + ": no C3D8 nodes/elements parsed");
    for (const auto& [eid, ids] : elems) {
        const auto mm = std::minmax_element(ids.begin(), ids.end());
        if (*mm.first < 1 ||
            *mm.second > static_cast<long long>(nodes.size()))
            throw ExportError(name + ": element references missing node");
    }
    Json jn = Json::array();
    for (const auto& [id, p] : nodes)
        jn.push_back(Json::array({p[0], p[1], p[2]}));
    Json je = Json::array();
    for (const auto& [eid, ids] : elems) {
        Json e = Json::array();
        e.push_back(eid);
        Json a = Json::array();
        for (auto i : ids) a.push_back(i);
        e.push_back(std::move(a));
        je.push_back(std::move(e));
    }
    return Json{{"node_count", static_cast<long long>(nodes.size())},
                {"element_count", static_cast<long long>(elems.size())},
                {"nodes", std::move(jn)},
                {"elements", std::move(je)}};
}

Json read_obj(std::string_view text, const std::string& name) {
    std::vector<Vec3> verts;
    std::vector<std::array<long long, 3>> faces;
    for (const std::string& line : split_lines(text)) {
        const auto parts = split_ws(line);
        if (parts.empty()) continue;
        if (parts[0] == "v" && parts.size() >= 4) {
            verts.push_back(Vec3{parse_flt(parts[1]), parse_flt(parts[2]),
                                 parse_flt(parts[3])});
        } else if (parts[0] == "f" && parts.size() >= 4) {
            std::array<long long, 3> f{};
            for (int k = 0; k < 3; ++k) {
                const std::size_t slash = parts[1 + k].find('/');
                f[k] = parse_int(parts[1 + k].substr(0, slash)) - 1;
            }
            faces.push_back(f);
        }
    }
    if (verts.empty())
        throw ExportError(name + ": no vertices parsed (empty or garbage OBJ)");
    if (!faces.empty()) {
        long long mn = faces[0][0], mx = faces[0][0];
        for (const auto& f : faces)
            for (auto i : f) { mn = std::min(mn, i); mx = std::max(mx, i); }
        if (mn < 0 || mx >= static_cast<long long>(verts.size()))
            throw ExportError(name + ": face index out of range");
    }
    Json jv = Json::array();
    for (const Vec3& p : verts)
        jv.push_back(Json::array({p[0], p[1], p[2]}));
    Json jf = Json::array();
    for (const auto& f : faces)
        jf.push_back(Json::array({f[0], f[1], f[2]}));
    return Json{{"vertex_count", static_cast<long long>(verts.size())},
                {"face_count", static_cast<long long>(faces.size())},
                {"vertices", std::move(jv)},
                {"faces", std::move(jf)}};
}

Json read_stl(std::string_view bytes, const std::string& name) {
    if (bytes.size() < 84)
        throw ExportError(name + ": truncated STL");
    const auto u32 = [&](std::size_t off) {
        return static_cast<std::uint32_t>(
            static_cast<unsigned char>(bytes[off]) |
            (static_cast<unsigned char>(bytes[off + 1]) << 8) |
            (static_cast<unsigned char>(bytes[off + 2]) << 16) |
            (static_cast<unsigned char>(bytes[off + 3]) << 24));
    };
    const auto f32 = [&](std::size_t off) {
        const std::uint32_t u = u32(off);
        float f;
        std::memcpy(&f, &u, 4);
        return static_cast<double>(f);
    };
    const std::uint32_t count = u32(80);
    const std::size_t expected = 84 + static_cast<std::size_t>(count) * 50;
    if (bytes.size() != expected)
        throw ExportError(name + ": STL size mismatch (header says " +
                          std::to_string(count) + " triangles)");
    Json tris = Json::array();
    std::size_t off = 84;
    for (std::uint32_t i = 0; i < count; ++i) {
        Json tri = Json::array();
        for (int v = 0; v < 3; ++v)
            tri.push_back(Json::array(
                {f32(off + 12 + v * 12), f32(off + 16 + v * 12),
                 f32(off + 20 + v * 12)}));
        tris.push_back(std::move(tri));
        off += 50;
    }
    return Json{{"triangle_count", static_cast<long long>(count)},
                {"triangles", std::move(tris)}};
}

Json read_vtp(std::string_view text, const std::string& name) {
    std::unique_ptr<ingest::XmlNode> root;
    try {
        root = ingest::xml_parse(text);
    } catch (const ingest::XmlError& e) {
        throw ExportError(name + ": malformed VTK XML (" +
                          std::string(e.what()) + ": " +
                          expat_position(text) + ")");
    }
    if (!root || root->tag != "VTKFile" ||
        !root->attr("type") || *root->attr("type") != "PolyData")
        throw ExportError(name + ": not a VTK PolyData XML file");
    const ingest::XmlNode* piece = find_desc(*root, "Piece");
    if (!piece) throw ExportError(name + ": no Piece element");
    const std::string* np = piece->attr("NumberOfPoints");
    const std::string* nz = piece->attr("NumberOfPolys");
    const long long n_points = np ? parse_int(*np) : 0;
    const long long n_polys = nz ? parse_int(*nz) : 0;

    const ingest::XmlNode* conn_node = find_da(*piece, "Polys", "connectivity");
    const std::string conn_text =
        conn_node ? py_strip(node_text(conn_node)) : "";
    if (conn_text.empty())
        throw ExportError(name + ": empty connectivity");
    std::vector<long long> conn;
    for (const auto& t : split_ws(conn_text)) conn.push_back(parse_int(t));

    const ingest::XmlNode* pts_node = find_da(*piece, "Points", "Points");
    const std::string pts_text =
        pts_node ? py_strip(node_text(pts_node)) : "";
    if (pts_text.empty())
        throw ExportError(name + ": empty points");
    std::vector<double> flat;
    for (const auto& t : split_ws(pts_text)) flat.push_back(parse_flt(t));
    if (flat.size() % 3)
        throw ValueError("cannot reshape array of size " +
                         std::to_string(flat.size()) +
                         " into shape (3)");
    std::vector<Vec3> pts;
    for (std::size_t i = 0; i + 2 < flat.size(); i += 3)
        pts.push_back(Vec3{flat[i], flat[i + 1], flat[i + 2]});

    if (static_cast<long long>(pts.size()) != n_points ||
        static_cast<long long>(conn.size()) != 3 * n_polys)
        throw ExportError(name + ": declared counts do not match payload");
    const auto mm = std::minmax_element(conn.begin(), conn.end());
    if (*mm.first < 0 || *mm.second >= n_points)
        throw ExportError(name + ": connectivity index out of range");

    Json pd = Json::object();
    std::vector<const ingest::XmlNode*> das;
    collect_da(*piece, "PointData", das);
    for (const auto* da : das) {
        const std::string* nm = da->attr("Name");
        const std::string key = nm ? *nm : "";
        const std::string txt = py_strip(node_text(da));
        if (txt.empty()) continue;
        Json arr = Json::array();
        for (const auto& t : split_ws(txt)) arr.push_back(parse_flt(t));
        pd[key] = std::move(arr);
    }

    Json jp = Json::array();
    for (const Vec3& p : pts)
        jp.push_back(Json::array({p[0], p[1], p[2]}));
    Json jc = Json::array();
    for (std::size_t i = 0; i + 2 < conn.size(); i += 3)
        jc.push_back(Json::array({conn[i], conn[i + 1], conn[i + 2]}));
    return Json{{"point_count", n_points},
                {"poly_count", n_polys},
                {"points", std::move(jp)},
                {"connectivity", std::move(jc)},
                {"point_data", std::move(pd)}};
}

// ---------------------------------------------------------------------------
// validate_export
// ---------------------------------------------------------------------------

Json validate_export(const std::string& name, std::string_view bytes,
                     const DomainObject& obj) {
    const std::string suffix = suffix_of(name);
    if (suffix == ".f3grid") return read_flac3d_grid(bytes, name);
    if (suffix == ".inp") return read_abaqus_inp(bytes, name);
    if (suffix == ".obj") {
        Json parsed = read_obj(bytes, name);
        std::vector<Vec3> verts;
        const auto& faces = mesh_faces(obj, verts);
        if (parsed["face_count"].get<long long>() !=
            static_cast<long long>(faces.size()))
            throw ExportError("OBJ face count mismatch");
        std::vector<Vec3> pv;
        for (const auto& row : parsed["vertices"])
            pv.push_back(Vec3{row[0].get<double>(), row[1].get<double>(),
                              row[2].get<double>()});
        if (!allclose(bounds_min(pv), bounds_min(verts), 1e-4))
            throw ExportError("OBJ bounds mismatch (min)");
        if (!allclose(bounds_max(pv), bounds_max(verts), 1e-4))
            throw ExportError("OBJ bounds mismatch (max)");
        return parsed;
    }
    if (suffix == ".stl") {
        Json parsed = read_stl(bytes, name);
        std::vector<Vec3> verts;
        const auto& faces = mesh_faces(obj, verts);
        if (parsed["triangle_count"].get<long long>() !=
            static_cast<long long>(faces.size()))
            throw ExportError("STL triangle count mismatch");
        std::vector<Vec3> flat;
        for (const auto& tri : parsed["triangles"])
            for (const auto& p : tri)
                flat.push_back(Vec3{p[0].get<double>(), p[1].get<double>(),
                                    p[2].get<double>()});
        if (!allclose(bounds_min(flat), bounds_min(verts), 1e-4))
            throw ExportError("STL bounds mismatch (min)");
        if (!allclose(bounds_max(flat), bounds_max(verts), 1e-4))
            throw ExportError("STL bounds mismatch (max)");
        return parsed;
    }
    if (suffix == ".vtp") {
        Json parsed = read_vtp(bytes, name);
        std::vector<Vec3> verts;
        const auto& faces = mesh_faces(obj, verts);
        if (parsed["poly_count"].get<long long>() !=
            static_cast<long long>(faces.size()))
            throw ExportError("VTP poly count mismatch");
        std::vector<Vec3> pv;
        for (const auto& row : parsed["points"])
            pv.push_back(Vec3{row[0].get<double>(), row[1].get<double>(),
                              row[2].get<double>()});
        if (!allclose(bounds_min(pv), bounds_min(verts), 1e-4))
            throw ExportError("VTP bounds mismatch");
        return parsed;
    }
    throw ExportError("unknown export extension " + py_repr(Json(suffix)));
}

// ---------------------------------------------------------------------------
// legacy structured-grid exports
// ---------------------------------------------------------------------------

StructuredGrid generate_structured_grid(int nx, int ny, int nz, double dx,
                                        double dy, double dz) {
    StructuredGrid g;
    for (int i = 0; i <= nx; ++i)
        for (int j = 0; j <= ny; ++j)
            for (int k = 0; k <= nz; ++k)
                g.nodes.push_back(Vec3{
                    i * dx, j * dy,
                    k * dz +
                        5.0 * (static_cast<double>(i) / std::max(nx, 1)) *
                            (static_cast<double>(j) / std::max(ny, 1))});
    const auto nid = [&](int i, int j, int k) {
        return static_cast<long long>(i) * (ny + 1) * (nz + 1) +
               static_cast<long long>(j) * (nz + 1) + k;
    };
    for (int i = 0; i < nx; ++i)
        for (int j = 0; j < ny; ++j)
            for (int k = 0; k < nz; ++k)
                g.elements.push_back({nid(i, j, k), nid(i + 1, j, k),
                                      nid(i + 1, j + 1, k), nid(i, j + 1, k),
                                      nid(i, j, k + 1), nid(i + 1, j, k + 1),
                                      nid(i + 1, j + 1, k + 1),
                                      nid(i, j + 1, k + 1)});
    return g;
}

std::string legacy_export_to_flac3d(int nx, int ny, int nz, double dx,
                                    double dy, double dz) {
    const StructuredGrid g = generate_structured_grid(nx, ny, nz, dx, dy, dz);
    std::string f = "* FLAC3D grid exported by PaleoWorkbench\n";
    f += "* LEGACY synthetic grid (GridSpec), not user geometry\n";
    f += "* Grid dimensions: " + std::to_string(nx) + " x " +
         std::to_string(ny) + " x " + std::to_string(nz) + "\n";
    for (std::size_t i = 0; i < g.nodes.size(); ++i) {
        const Vec3& p = g.nodes[i];
        f += "G " + std::to_string(i + 1) + " " + fx(p[0], 4) + " " +
             fx(p[1], 4) + " " + fx(p[2], 4) + "\n";
    }
    for (std::size_t i = 0; i < g.elements.size(); ++i) {
        f += "Z B8 " + std::to_string(i + 1);
        for (auto id : g.elements[i]) f += " " + std::to_string(id + 1);
        f += "\n";
    }
    return f;
}

std::string legacy_export_to_abaqus(int nx, int ny, int nz, double dx,
                                    double dy, double dz) {
    const StructuredGrid g = generate_structured_grid(nx, ny, nz, dx, dy, dz);
    std::string f = "*HEADING\n";
    f += "** LEGACY Abaqus synthetic grid (GridSpec), not user geometry\n";
    f += "*PART, NAME=GEOMODEL\n";
    f += "*NODE\n";
    for (std::size_t i = 0; i < g.nodes.size(); ++i) {
        const Vec3& p = g.nodes[i];
        f += std::to_string(i + 1) + ", " + fx(p[0], 4) + ", " +
             fx(p[1], 4) + ", " + fx(p[2], 4) + "\n";
    }
    f += "*ELEMENT, TYPE=C3D8, ELSET=EALL\n";
    for (std::size_t i = 0; i < g.elements.size(); ++i) {
        f += std::to_string(i + 1);
        for (auto id : g.elements[i]) f += ", " + std::to_string(id + 1);
        f += "\n";
    }
    f += "*END PART\n";
    return f;
}

}  // namespace pwb::geomodel
