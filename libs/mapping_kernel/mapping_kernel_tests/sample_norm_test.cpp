// mapping_kernel.sample_norm — normalize_factor_samples vs Python oracle.

#include <cmath>
#include <cstdio>
#include <exception>
#include <fstream>
#include <limits>
#include <sstream>
#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/sample_normalization.hpp>

using pwb::domain::Json;
using pwb::mapping::normalize_factor_samples;
using pwb::mapping::duplicate_policy_from_params;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

Json restore_input(const Json& arr) {
    Json out = Json::array();
    for (const auto& rec : arr) {
        Json item = rec;
        for (auto it = item.begin(); it != item.end(); ++it) {
            if (it.value().is_string() && it.value().get<std::string>() == "inf") {
                it.value() = "inf";
            }
        }
        out.push_back(item);
    }
    return out;
}

bool close_num(const Json& a, const Json& b) {
    if (a.is_null() && b.is_null()) return true;
    if (!a.is_number() || !b.is_number()) return a == b;
    return std::fabs(a.get<double>() - b.get<double>()) < 1e-12;
}

bool points_match(const Json& got, const Json& want) {
    if (!got.is_array() || !want.is_array()) return false;
    if (got.size() != want.size()) return false;
    for (std::size_t i = 0; i < got.size(); ++i) {
        if (!got[i].is_object() || !want[i].is_object()) return false;
        if (got[i].size() != want[i].size()) return false;
        for (auto it = want[i].begin(); it != want[i].end(); ++it) {
            if (!got[i].contains(it.key())) return false;
            if (!close_num(got[i][it.key()], it.value())
                && got[i][it.key()] != it.value()) {
                return false;
            }
        }
    }
    return true;
}

}  // namespace

int main() {
    std::ifstream stream(PWB_SAMPLE_NORM_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open fixture\n");
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    const auto& params = oracle["params"];
    check(duplicate_policy_from_params(Json()) == params["default"].get<std::string>(),
          "params none");
    check(duplicate_policy_from_params(Json::object())
              == params["empty"].get<std::string>(),
          "params empty");
    Json errp = Json::object();
    errp["duplicate_policy"] = "error";
    check(duplicate_policy_from_params(errp) == "error", "params error");
    Json med = Json::object();
    med["duplicate_policy"] = "median";
    check(duplicate_policy_from_params(med)
              == params["median"].get<std::string>(),
          "params median fallback");

    int n = 0;
    for (const auto& c : oracle["cases"]) {
        ++n;
        const std::string id = c["id"].get<std::string>();
        const std::string policy = c["policy"].get<std::string>();
        const Json input = restore_input(c["input"]);
        if (c["ok"].get<bool>()) {
            try {
                const auto got = normalize_factor_samples(input, policy);
                check(points_match(got.first, c["points"]), id + " points");
                const auto& r = c["report"];
                check(got.second.policy == r["policy"].get<std::string>(),
                      id + " policy");
                check(got.second.n_input == r["n_input"].get<int>(),
                      id + " n_input");
                check(got.second.n_valid == r["n_valid"].get<int>(),
                      id + " n_valid");
                check(got.second.n_nonfinite_dropped
                          == r["n_nonfinite_dropped"].get<int>(),
                      id + " n_nonfinite");
                check(got.second.n_duplicate_groups
                          == r["n_duplicate_groups"].get<int>(),
                      id + " n_dup_groups");
                check(got.second.n_duplicates_merged
                          == r["n_duplicates_merged"].get<int>(),
                      id + " n_merged");
                check(got.second.n_qc_flagged == r["n_qc_flagged"].get<int>(),
                      id + " n_qc");
            } catch (const std::exception& ex) {
                check(false, id + " threw: " + ex.what());
            }
        } else {
            try {
                normalize_factor_samples(input, policy);
                check(false, id + " should throw");
            } catch (const std::invalid_argument& ex) {
                check(std::string(ex.what()) == c["error"].get<std::string>(),
                      id + " error text: " + ex.what());
            }
        }
    }
    check(n == 14, "14 sample-norm cases");
    std::printf("%s: %d failure(s) over %d sample-norm cases\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, n);
    return g_failures == 0 ? 0 : 1;
}
