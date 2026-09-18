#pragma once

// pwb::geomodel — domain object contract layer (CONV-22): a faithful C++
// port of paleo_workbench/viz/geomodel/domain.py plus the pure dataclass
// constructors of builders.py.
//
//   * DomainObject mirrors the six frozen dataclasses as ONE struct: the
//     Python constructors bind object_id prefix <-> class 1:1, so the kind
//     is the prefix and the per-kind payloads live in optional fields.
//   * meta()/from_meta round-trip JSON exactly (arrays stay out of meta —
//     ADR-03); geometry_stats is the shared inspector summary.
//   * ModelAssembly is the ordered, unique-id container with the same
//     mutation policy (add/replace/remove/clear/bump_version) and the
//     silent-swallow restore semantics of apply_meta.
//   * builders' pure constructors (build_well_trajectory /
//     build_simplified_vertical_well / build_fault_from_mesh / _unique_slug)
//     produce the same objects with the same DomainError text.
//
// Frozen against tools/oracle/generate_geomodel_contract_fixtures.py
// (geomodel_contract_oracle.json). Qt-free, Python-free, numpy-free.

#include <array>
#include <optional>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/geomodel/volume.hpp>  // Vec3

namespace pwb::geomodel {

using pwb::domain::Json;

// Python exception categories the contract layer raises (class names are
// part of the frozen oracle). DomainError subclasses ValueError exactly
// like Python (class DomainError(ValueError)).
struct ValueError : std::runtime_error {
    using std::runtime_error::runtime_error;
};
struct DomainError : ValueError {
    using ValueError::ValueError;
};
struct TypeError : std::runtime_error {
    using std::runtime_error::runtime_error;
};
struct KeyError : std::runtime_error {
    using std::runtime_error::runtime_error;
};
struct IndexError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// ---------------------------------------------------------------------------
// helpers with Python semantics
// ---------------------------------------------------------------------------

// domain._slugify: str(text).strip().lower(), runs of non-[a-z0-9_.-] -> '-',
// strip leading/trailing '-'/'.'; empty -> fallback.
std::string slugify(const Json& text, const std::string& fallback);

// domain._clean_ids: tuple(str(i) for i in (ids or ())) — dict iterates keys,
// truthy non-iterable raises TypeError.
std::vector<std::string> clean_ids(const Json& ids);

// str(value) for the JSON value domain (None/True/False/numbers/strings/
// containers fall back to JSON dump for exotic inputs — the oracle only
// feeds scalars here).
std::string py_str(const Json& v);

// repr(value) for error text ('...' quoting with Python escapes).
std::string py_repr(const Json& v);

// str.strip() — full CPython whitespace set (incl. U+001C-001F, U+0085).
std::string py_strip(std::string_view s);

// str.lower() via the generated table (src/lower_map.inc).
std::string py_lower(std::string_view s);

// Truthiness over the JSON domain (None/False/0/"",/[]/{} falsy).
bool py_truthy(const Json& v);

// int(v): bool -> 0/1, int -> itself, float -> trunc toward zero,
// str -> base-10 parse (else ValueError "invalid literal for int()
// with base 10: 'x'").
long long py_int(const Json& v);

// float(v): bool/int/float -> double, str -> float() parse (else
// ValueError "could not convert string to float: 'x'"), other types
// -> TypeError.
double py_float(const Json& v);

// ---------------------------------------------------------------------------
// domain objects
// ---------------------------------------------------------------------------

struct Provenance {
    std::string source_kind = "derived";  // catalog|derived|imported|demo
    std::vector<std::string> source_version_ids;
    std::string created_from;
    bool demo = false;

    Json to_meta() const;
    static Provenance from_meta(const Json& meta);  // meta or {} semantics
};

// One struct carrying every per-kind payload; which fields are meaningful is
// fixed by kind() (the object_id prefix — Python binds class<->prefix in
// __post_init__).
struct DomainObject {
    std::string object_id;
    std::string name;
    std::string crs = "unknown";
    std::string vertical_domain = "depth";  // depth|twt|tvdss
    std::string unit = "m";
    Provenance provenance;
    long long version = 1;

    // well (stations rows [md,x,y,z])
    std::vector<std::array<double, 4>> stations;
    std::string representation;  // well: measured|simplified_vertical;
                                 // fault: triangulated_3d|curtain_2p5d
    std::optional<std::string> z_unit;
    std::string well_asset_id;
    std::vector<std::pair<std::string, double>> formation_tops;

    // horizon (row-major rows x cols; NaN = hole)
    std::vector<std::vector<double>> z_grid;
    std::array<double, 2> origin{0.0, 0.0};
    std::array<double, 2> spacing{1.0, 1.0};
    std::string grid_crs;
    std::string horizon_asset_id;
    std::optional<std::vector<std::vector<double>>> confidence;
    std::vector<std::pair<std::string, std::vector<std::vector<double>>>>
        attributes;

    // fault / volume triangle meshes
    std::vector<Vec3> verts;
    std::vector<std::array<std::int64_t, 3>> faces;
    std::optional<std::vector<std::array<double, 2>>> trace_xy;
    std::optional<std::array<double, 2>> z_extent;
    std::optional<double> throw_m;
    std::optional<std::array<double, 2>> strike_dip;
    std::string fault_asset_id;
    std::vector<std::string> intersects_horizons;

    // volume extras
    std::string top_id;
    std::string base_id;
    std::optional<std::vector<std::array<double, 2>>> boundary;
    std::string formation;
    std::optional<std::vector<std::int64_t>> facies;
    std::vector<std::pair<std::string, std::vector<double>>> properties;
    bool has_cell_mesh = false;
    Json quality = Json::object();

    // tunnel
    std::vector<Vec3> path;
    double radius = 3.0;

    // measure
    std::string measurement_kind = "distance";
    std::vector<Vec3> points;
    std::optional<double> result;
    Json extra = Json::object();

    // "well" | "horizon" | "fault" | "volume" | "tunnel" | "measure" | other
    std::string kind() const;

    // full __post_init__ validation for the object's kind (DomainError text
    // identical to the Python dataclasses).
    void validate() const;

    Json meta() const;
    // Python <cls>.from_meta(meta): str()/float()/int() coercions, missing
    // keys -> dataclass defaults, arrays stay unloaded (ADR-03).
    static DomainObject from_meta(const Json& meta);
};

// spec -> object: the oracle's JSON constructor spec ({"kind", ...kwargs}).
// Validates like the Python constructor; throws DomainError / ValueError /
// TypeError with the frozen class names.
DomainObject object_from_spec(const Json& spec);

// The oracle's mutate() helper — post-construction array edits that bypass
// __post_init__ (the frozen-by-convention bypass). spec["_mutate"] entries:
// {"field", "index": int|[i,j], "value"}; null value -> NaN, faces -> int.
void apply_mutations(DomainObject& obj, const Json& spec);

// domain.geometry_stats — isinstance dispatch by kind.
Json geometry_stats(const DomainObject& obj);

// ---------------------------------------------------------------------------
// ModelAssembly
// ---------------------------------------------------------------------------

class ModelAssembly {
public:
    explicit ModelAssembly(std::string name = "geo3d");

    std::size_t size() const;
    bool contains(const std::string& object_id) const;
    // kind=nullopt -> insertion order; else prefix filter (split(':',1)[0]).
    std::vector<DomainObject> objects(
        const std::optional<std::string>& kind = std::nullopt) const;
    const DomainObject* get(const std::string& object_id) const;
    std::vector<std::string> ids(
        const std::optional<std::string>& kind = std::nullopt) const;

    // Mutations: DomainError text identical (em-dash in "duplicate ... —
    // use replace()"); bump_version throws KeyError on unknown ids.
    DomainObject& add(DomainObject obj);
    DomainObject& replace(DomainObject obj);
    bool remove(const std::string& object_id);
    int clear(const std::optional<std::string>& kind = std::nullopt);
    DomainObject& bump_version(const std::string& object_id);

    Json to_meta() const;
    // Restores objects; returns restored ids, silently skipping unknown
    // kinds and malformed entries (DomainError/KeyError/TypeError/
    // ValueError caught, like Python).
    std::vector<std::string> apply_meta(const Json& meta);

    std::string name;
    std::string frame = "world";
    Json display = Json::object();  // object_id -> hints dict

private:
    std::unordered_map<std::string, DomainObject> objects_;
    std::vector<std::string> order_;
    mutable std::recursive_mutex lock_;
};

// ---------------------------------------------------------------------------
// builders.py pure constructors (geometry kernels live in builders.hpp)
// ---------------------------------------------------------------------------

// build_well_trajectory: DomainError text uses the display name, not the id.
// Ragged rows are accepted so the (N, 4) contract can fail like numpy's.
DomainObject build_well_trajectory(
    const std::string& name,
    const std::vector<std::vector<double>>& stations,
    const std::string& crs = "unknown", const std::string& unit = "m",
    const std::string& vertical_domain = "depth",
    const std::string& well_asset_id = "",
    const std::vector<std::pair<std::string, double>>& formation_tops = {},
    std::optional<Provenance> provenance = std::nullopt,
    const std::optional<std::string>& object_id = std::nullopt);

// build_simplified_vertical_well: 2 stations, twt -> head z stays 0.
DomainObject build_simplified_vertical_well(
    const std::string& name, const std::vector<double>& head_xyz,
    double total_depth, const std::string& crs = "unknown",
    const std::string& unit = "m",
    const std::string& vertical_domain = "depth",
    const std::string& well_asset_id = "",
    const std::vector<std::pair<std::string, double>>& formation_tops = {},
    std::optional<Provenance> provenance = std::nullopt,
    const std::optional<std::string>& object_id = std::nullopt);

// build_fault_from_mesh.
DomainObject build_fault_from_mesh(
    const std::string& name,
    const std::vector<std::vector<double>>& verts,
    const std::vector<std::vector<std::int64_t>>& faces,
    const std::string& crs = "unknown", const std::string& unit = "m",
    const std::string& vertical_domain = "depth",
    std::optional<double> throw_m = std::nullopt,
    std::optional<std::array<double, 2>> strike_dip = std::nullopt,
    const std::string& fault_asset_id = "",
    std::optional<Provenance> provenance = std::nullopt,
    const std::optional<std::string>& object_id = std::nullopt);

}  // namespace pwb::geomodel
