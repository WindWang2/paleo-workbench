// mapping_kernel.crs_units — C++ port vs the frozen Python oracle
// (crs_units_oracle.json, generated from the REAL implementations by
// tools/oracle/generate_crs_units_fixtures.py).
//
// The oracle's "kernel" section was produced with pyproj import blocked —
// exactly this kernel's dependency profile — so every value is compared:
// geometry_units (is_geographic_crs / area_unit_label / ring_area_with_unit
// / polyline_length_with_unit) and crs_contract (normalize_crs /
// crs_is_geographic / resolve_crs / panel_publish_crs /
// crs_axis_unit_metres / scale_denominator_from_pixels /
// crs_coordinate_domain / coordinate_domain_mismatch incl. describe() /
// infer_crs_from_extent). The "pyproj_env" section is recorded for humans
// only; the C++ kernel is pyproj-free and its honest-unknown rows are the
// kernel section's business.

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/crs_contract.hpp>
#include <pwb/mapping/geometry_units.hpp>

using pwb::domain::Json;
using pwb::mapping::AreaWithUnit;
using pwb::mapping::CRSInference;
using pwb::mapping::CRSResolution;
using pwb::mapping::Domain;
using pwb::mapping::DomainMismatch;
using pwb::mapping::LengthWithUnit;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

std::optional<std::string> opt_str(const Json& v) {
    if (v.is_null()) return std::nullopt;
    return v.get<std::string>();
}

std::optional<bool> opt_bool(const Json& v) {
    if (v.is_null()) return std::nullopt;
    return v.get<bool>();
}

std::string show_opt_bool(const std::optional<bool>& v) {
    if (!v.has_value()) return "null";
    return *v ? "true" : "false";
}

std::string show_opt_str(const std::optional<std::string>& v) {
    if (!v.has_value()) return "null";
    return *v;
}

std::string show_opt_domain(const std::optional<Domain>& v) {
    if (!v.has_value()) return "null";
    return "[" + std::to_string((*v)[0]) + " " + std::to_string((*v)[1]) +
           " " + std::to_string((*v)[2]) + " " + std::to_string((*v)[3]) +
           "]";
}

// libm ulp noise on cos/hypot/scaled products: relative 1e-9 (contouring
// oracle convention).
void check_close(double got, double want, const std::string& what) {
    check(std::fabs(got - want) <= 1e-9 * std::max(1.0, std::fabs(want)),
          what + " got=" + std::to_string(got) +
              " want=" + std::to_string(want));
}

void check_exact_array(const std::array<double, 4>& got, const Json& want,
                       const std::string& what) {
    for (int i = 0; i < 4; ++i) {
        check(got[i] == want[i].get<double>(),
              what + " [" + std::to_string(i) + "] got=" +
                  std::to_string(got[i]) + " want=" +
                  std::to_string(want[i].get<double>()));
    }
}

Domain domain_from_json(const Json& v) {
    return {v[0].get<double>(), v[1].get<double>(), v[2].get<double>(),
            v[3].get<double>()};
}

std::optional<Domain> opt_domain_from_json(const Json& v) {
    if (v.is_null()) return std::nullopt;
    return domain_from_json(v);
}

std::optional<std::array<double, 4>> opt_extent_from_json(const Json& v) {
    if (v.is_null()) return std::nullopt;
    return domain_from_json(v);
}

pwb::mapping::Ring ring_from_json(const Json& v) {
    pwb::mapping::Ring ring;
    ring.reserve(v.size());
    for (const auto& pt : v) {
        ring.push_back({pt[0].get<double>(), pt[1].get<double>()});
    }
    return ring;
}

void check_warning(const std::optional<std::string>& got, const Json& want,
                   const std::string& what) {
    const auto want_warning = opt_str(want);
    check(got == want_warning,
          what + " warning got=[" + show_opt_str(got) + "] want=[" +
              show_opt_str(want_warning) + "]");
}

void check_geometry_units(const Json& module_root) {
    check(module_root["constants"]["METRES_PER_DEGREE_LAT"].get<double>() ==
              pwb::mapping::kMetresPerDegreeLat,
          "METRES_PER_DEGREE_LAT");

    int n_geo = 0;
    for (const auto& rec : module_root["is_geographic_crs"]) {
        const std::string id = rec["id"].get<std::string>();
        const bool got =
            pwb::mapping::is_geographic_crs(opt_str(rec["crs"]));
        check(got == rec["result"].get<bool>(),
              id + " is_geographic_crs got=" + (got ? "true" : "false") +
                  " want=" + (rec["result"].get<bool>() ? "true" : "false"));
        ++n_geo;
    }

    int n_label = 0;
    for (const auto& rec : module_root["area_unit_label"]) {
        const std::string id = rec["id"].get<std::string>();
        const std::string got =
            pwb::mapping::area_unit_label(opt_str(rec["crs"]));
        check(got == rec["result"].get<std::string>(),
              id + " area_unit_label got=[" + got + "] want=[" +
                  rec["result"].get<std::string>() + "]");
        ++n_label;
    }

    int n_ring = 0;
    for (const auto& rec : module_root["ring_area_with_unit"]) {
        const std::string id = rec["id"].get<std::string>();
        const AreaWithUnit got = pwb::mapping::ring_area_with_unit(
            ring_from_json(rec["ring"]), opt_str(rec["crs"]));
        check_close(got.area, rec["area"].get<double>(),
                    id + " ring area");
        check(got.unit_label == rec["unit_label"].get<std::string>(),
              id + " ring unit got=[" + got.unit_label + "] want=[" +
                  rec["unit_label"].get<std::string>() + "]");
        check_warning(got.warning, rec["warning"], id + " ring");
        ++n_ring;
    }

    int n_len = 0;
    for (const auto& rec : module_root["polyline_length_with_unit"]) {
        const std::string id = rec["id"].get<std::string>();
        const LengthWithUnit got = pwb::mapping::polyline_length_with_unit(
            ring_from_json(rec["vertices"]), opt_str(rec["crs"]));
        check_close(got.length, rec["length"].get<double>(),
                    id + " length");
        check(got.unit_label == rec["unit_label"].get<std::string>(),
              id + " length unit got=[" + got.unit_label + "] want=[" +
                  rec["unit_label"].get<std::string>() + "]");
        check_warning(got.warning, rec["warning"], id + " length");
        ++n_len;
    }

    check(n_geo > 0 && n_label > 0 && n_ring > 0 && n_len > 0,
          "geometry_units sections non-empty");
}

void check_crs_contract(const Json& module_root) {
    const Json& constants = module_root["constants"];
    check_exact_array(pwb::mapping::kGeographicDegreeDomain,
                      constants["GEOGRAPHIC_DEGREE_DOMAIN"],
                      "GEOGRAPHIC_DEGREE_DOMAIN");
    check(constants["DOMAIN_EPSILON"].get<double>() ==
              pwb::mapping::kDomainEpsilon,
          "DOMAIN_EPSILON");
    check(constants["PROJECTED_DOMAIN_SLACK"].get<double>() ==
              pwb::mapping::kProjectedDomainSlack,
          "PROJECTED_DOMAIN_SLACK");

    int n_norm = 0;
    for (const auto& rec : module_root["normalize_crs"]) {
        const std::string id = rec["id"].get<std::string>();
        const std::string got =
            pwb::mapping::normalize_crs(opt_str(rec["crs"]));
        check(got == rec["result"].get<std::string>(),
              id + " normalize_crs got=[" + got + "] want=[" +
                  rec["result"].get<std::string>() + "]");
        ++n_norm;
    }

    int n_geo = 0;
    for (const auto& rec : module_root["crs_is_geographic"]) {
        const std::string id = rec["id"].get<std::string>();
        // crs_contract.crs_is_geographic delegates to the crs_policy
        // predicate (single axis-units truth); the C++ leaf reuses it.
        const auto got = pwb::mapping::crs_is_geographic(opt_str(rec["crs"]));
        check(got == opt_bool(rec["result"]),
              id + " crs_is_geographic got=" + show_opt_bool(got) +
                  " want=" + show_opt_bool(opt_bool(rec["result"])));
        ++n_geo;
    }

    int n_resolve = 0;
    for (const auto& rec : module_root["resolve_crs"]) {
        const std::string id = rec["id"].get<std::string>();
        const CRSResolution got = pwb::mapping::resolve_crs(
            opt_str(rec["value"]), rec["purpose"].get<std::string>(),
            opt_str(rec["fallback"]));
        check(got.crs == rec["crs"].get<std::string>(),
              id + " resolve crs got=[" + got.crs + "] want=[" +
                  rec["crs"].get<std::string>() + "]");
        check(got.declared == rec["declared"].get<bool>(),
              id + " resolve declared");
        check(got.degraded_reason ==
                  rec["degraded_reason"].get<std::string>(),
              id + " resolve reason got=[" + got.degraded_reason +
                  "] want=[" + rec["degraded_reason"].get<std::string>() +
                  "]");
        check(got.ok() == rec["ok"].get<bool>(), id + " resolve ok");
        ++n_resolve;
    }

    int n_panel = 0;
    for (const auto& rec : module_root["panel_publish_crs"]) {
        const std::string id = rec["id"].get<std::string>();
        const std::string got = pwb::mapping::panel_publish_crs(
            opt_str(rec["value"]), rec["purpose"].get<std::string>());
        check(got == rec["result"].get<std::string>(),
              id + " panel_publish_crs got=[" + got + "] want=[" +
                  rec["result"].get<std::string>() + "]");
        ++n_panel;
    }

    int n_axis = 0;
    for (const auto& rec : module_root["crs_axis_unit_metres"]) {
        const std::string id = rec["id"].get<std::string>();
        const auto got =
            pwb::mapping::crs_axis_unit_metres(opt_str(rec["crs"]));
        check(got == opt_bool(rec["result"]),
              id + " crs_axis_unit_metres got=" + show_opt_bool(got) +
                  " want=" + show_opt_bool(opt_bool(rec["result"])));
        ++n_axis;
    }

    int n_scale = 0;
    for (const auto& rec : module_root["scale_denominator_from_pixels"]) {
        const std::string id = rec["id"].get<std::string>();
        const double got = pwb::mapping::scale_denominator_from_pixels(
            rec["mupp"].get<double>(), rec["ppi"].get<double>(),
            opt_str(rec["crs"]));
        check(got == rec["result"].get<double>(),
              id + " scale_denominator got=" + std::to_string(got) +
                  " want=" + std::to_string(rec["result"].get<double>()));
        ++n_scale;
    }

    int n_domain = 0;
    for (const auto& rec : module_root["crs_coordinate_domain"]) {
        const std::string id = rec["id"].get<std::string>();
        const auto got =
            pwb::mapping::crs_coordinate_domain(opt_str(rec["crs"]));
        const auto want = opt_domain_from_json(rec["result"]);
        check(got.has_value() == want.has_value(),
              id + " crs_coordinate_domain presence got=" +
                  show_opt_domain(got));
        if (got.has_value() && want.has_value()) {
            check_exact_array(*got, rec["result"], id + " crs_coordinate_domain");
        }
        ++n_domain;
    }

    int n_mismatch = 0;
    for (const auto& rec : module_root["coordinate_domain_mismatch"]) {
        const std::string id = rec["id"].get<std::string>();
        const auto got = pwb::mapping::coordinate_domain_mismatch(
            opt_str(rec["crs"]), opt_extent_from_json(rec["extent"]));
        const Json& want = rec["result"];
        check(got.has_value() == !want.is_null(),
              id + " mismatch presence");
        if (got.has_value()) {
            check(got->crs == want["crs"].get<std::string>(),
                  id + " mismatch crs got=[" + got->crs + "] want=[" +
                      want["crs"].get<std::string>() + "]");
            check_exact_array(got->extent, want["extent"],
                              id + " mismatch extent");
            check_exact_array(got->domain, want["domain"],
                              id + " mismatch domain");
            check(got->describe() == want["describe"].get<std::string>(),
                  id + " describe got=[" + got->describe() + "] want=[" +
                      want["describe"].get<std::string>() + "]");
        }
        ++n_mismatch;
    }

    int n_infer = 0;
    for (const auto& rec : module_root["infer_crs_from_extent"]) {
        const std::string id = rec["id"].get<std::string>();
        const CRSInference got = pwb::mapping::infer_crs_from_extent(
            opt_extent_from_json(rec["extent"]));
        check(got.suggested_crs == rec["suggested_crs"].get<std::string>(),
              id + " infer suggested_crs got=[" + got.suggested_crs +
                  "] want=[" + rec["suggested_crs"].get<std::string>() +
                  "]");
        check(got.basis == rec["basis"].get<std::string>(),
              id + " infer basis got=[" + got.basis + "] want=[" +
                  rec["basis"].get<std::string>() + "]");
        check(got.suggests_declaration() ==
                  !rec["suggested_crs"].get<std::string>().empty(),
              id + " infer suggests_declaration");
        ++n_infer;
    }

    check(n_norm > 0 && n_geo > 0 && n_resolve > 0 && n_panel > 0 &&
              n_axis > 0 && n_scale > 0 && n_domain > 0 && n_mismatch > 0 &&
              n_infer > 0,
          "crs_contract sections non-empty");
}

int count_rows(const Json& section) {
    int total = 0;
    for (const std::string& module : {"geometry_units", "crs_contract"}) {
        for (const auto& item : section[module].items()) {
            if (item.key() == "constants") continue;
            total += static_cast<int>(item.value().size());
        }
    }
    return total;
}

}  // namespace

int main() {
    const std::string fixture_path = PWB_CRS_UNITS_FIXTURE;
    std::ifstream stream(fixture_path, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open %s\n", fixture_path.c_str());
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    check(oracle["kernel"]["pyproj_blocked"].get<bool>(),
          "kernel section must be the pyproj-blocked freeze");

    check_geometry_units(oracle["kernel"]["geometry_units"]);
    check_crs_contract(oracle["kernel"]["crs_contract"]);

    // Recorded only (pyproj-enabled Python); never compared.
    const int n_env = count_rows(oracle["pyproj_env"]);
    check(n_env > 0, "pyproj_env section present");
    check(!oracle["pyproj_env"]["pyproj_blocked"].get<bool>(),
          "pyproj_env section must be the unblocked freeze");

    std::printf(
        "%s: %d failure(s) over %d checks; kernel cases=%d; "
        "pyproj_env cases=%d (recorded only)\n",
        g_failures == 0 ? "PASS" : "FAIL", g_failures, g_checks,
        count_rows(oracle["kernel"]), n_env);
    return g_failures == 0 ? 0 : 1;
}
