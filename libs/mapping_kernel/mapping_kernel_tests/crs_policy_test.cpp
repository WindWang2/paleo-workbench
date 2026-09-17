// mapping_kernel.crs_policy — C++ port vs the frozen Python oracle
// (crs_policy_oracle.json, generated from the REAL implementation by
// tools/oracle/generate_crs_policy_fixtures.py).
//
// builtin cases match bit-for-bit. pyproj_optional cases are recorded by
// the generator but this test only asserts C++ unknown → nullopt (no
// pyproj in the kernel).

#include <cstdio>
#include <fstream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/crs_policy.hpp>

using pwb::domain::Json;
using pwb::mapping::DistancePolicy;
using pwb::mapping::crs_is_geographic;
using pwb::mapping::resolve_distance_policy;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
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

void check_geo(const Json& rec, bool require_nullopt_unknown) {
    const std::string id = rec["id"].get<std::string>();
    const auto crs = opt_str(rec["crs"]);
    const auto got = crs_is_geographic(crs);
    if (require_nullopt_unknown) {
        check(!got.has_value(),
              id + " pyproj_optional C++ unknown → nullopt, got " +
                  show_opt_bool(got));
        return;
    }
    const auto want = opt_bool(rec["result"]);
    check(got == want, id + " crs_is_geographic got " + show_opt_bool(got) +
                           " want " + show_opt_bool(want));
}

void check_resolved(const DistancePolicy& got, const Json& want,
                    const std::string& id) {
    check(got.policy == want["policy"].get<std::string>(),
          id + " policy got=" + got.policy +
              " want=" + want["policy"].get<std::string>());
    const auto want_crs = opt_str(want["crs"]);
    check(got.crs == want_crs, id + " crs got=" + show_opt_str(got.crs) +
                                   " want=" + show_opt_str(want_crs));
    const auto want_axes = opt_bool(want["axes_known"]);
    check(got.axes_known == want_axes,
          id + " axes_known got=" + show_opt_bool(got.axes_known) +
              " want=" + show_opt_bool(want_axes));
    check(got.annotation == want["annotation"].get<std::string>(),
          id + " annotation got=[" + got.annotation + "] want=[" +
              want["annotation"].get<std::string>() + "]");
    const auto want_warning = opt_str(want["warning"]);
    check(got.warning == want_warning,
          id + " warning got=[" + show_opt_str(got.warning) + "] want=[" +
              show_opt_str(want_warning) + "]");
}

}  // namespace

int main() {
    const std::string fixture_path = PWB_CRS_POLICY_FIXTURE;
    std::ifstream stream(fixture_path, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open %s\n", fixture_path.c_str());
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    const Json& constants = oracle["constants"];
    check(std::string(pwb::mapping::kPolicyPlanar) ==
              constants["POLICY_PLANAR"].get<std::string>(),
          "POLICY_PLANAR");
    check(std::string(pwb::mapping::kPolicyPlanarDegrees) ==
              constants["POLICY_PLANAR_DEGREES"].get<std::string>(),
          "POLICY_PLANAR_DEGREES");
    check(std::string(pwb::mapping::kPolicyProjected) ==
              constants["POLICY_PROJECTED"].get<std::string>(),
          "POLICY_PROJECTED");
    check(std::string(pwb::mapping::kPolicyUndeclared) ==
              constants["POLICY_UNDECLARED"].get<std::string>(),
          "POLICY_UNDECLARED");
    {
        const auto& want = constants["DISTANCE_POLICIES"];
        check(want.size() == 3, "DISTANCE_POLICIES size");
        int i = 0;
        for (std::string_view p : pwb::mapping::kDistancePolicies) {
            check(p == want[i].get<std::string>(), "DISTANCE_POLICIES item");
            ++i;
        }
    }

    const Json& builtin = oracle["builtin"];
    int n_geo = 0;
    for (const auto& rec : builtin["crs_is_geographic"]) {
        check_geo(rec, false);
        ++n_geo;
    }

    int n_resolve = 0;
    for (const auto& rec : builtin["resolve"]) {
        const std::string id = rec["id"].get<std::string>();
        const auto crs = opt_str(rec["crs"]);
        const auto policy = opt_str(rec["distance_policy"]);
        DistancePolicy got;
        try {
            got = resolve_distance_policy(crs, policy);
        } catch (const std::exception& ex) {
            check(false, id + " unexpected throw: " + ex.what());
            ++n_resolve;
            continue;
        }
        check_resolved(got, rec["result"], id);
        ++n_resolve;
    }

    int n_errors = 0;
    for (const auto& rec : builtin["errors"]) {
        const std::string id = rec["id"].get<std::string>();
        const auto crs = opt_str(rec["crs"]);
        const auto policy = opt_str(rec["distance_policy"]);
        const std::string want = rec["error"].get<std::string>();
        try {
            (void)resolve_distance_policy(crs, policy);
            check(false, id + " expected invalid_argument");
        } catch (const std::invalid_argument& ex) {
            check(std::string(ex.what()) == want,
                  id + " error got=[" + ex.what() + "] want=[" + want + "]");
        } catch (const std::exception& ex) {
            check(false, id + " wrong exception: " + ex.what());
        }
        ++n_errors;
    }

    const Json& optional = oracle["pyproj_optional"];
    int n_skip_geo = 0;
    for (const auto& rec : optional["crs_is_geographic"]) {
        check_geo(rec, true);
        ++n_skip_geo;
    }
    // Resolve rows are recorded for humans; C++ does not compare them.
    const int n_skip_resolve =
        static_cast<int>(optional["resolve"].size());

    std::printf(
        "%s: %d failure(s); builtin geo=%d resolve=%d errors=%d; "
        "pyproj_optional skipped geo=%d resolve=%d (C++ unknown→nullopt)\n",
        g_failures == 0 ? "PASS" : "FAIL", g_failures, n_geo, n_resolve,
        n_errors, n_skip_geo, n_skip_resolve);
    return g_failures == 0 ? 0 : 1;
}
