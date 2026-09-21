// job_runtime.governor_oracle — CONV-34 replay of the frozen Python
// resource-governance oracle (governor_oracle.json, generated from the
// REAL paleo_workbench/runtime implementation by
// tools/oracle/generate_governor_oracle.py).
//
// Covered: budget derived fields, with_pressure_scale (banker's rounding),
// PALEO_* env overrides, pressure classification, rate-limited sampling,
// relief dispatch, governor admission/defer/release/metrics across
// scripted pressure sequences, and TaskRequest::from_kind defaults.
//
// Machine-dependent cells (auto-detected core counts when no explicit
// logical_cores is configured) are skipped — the generator ran on the
// freezing host, so those cells are documented host-dependent, not bugs.

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <map>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/job_runtime/governance.hpp>
#include <pwb/job_runtime/memory_pressure.hpp>
#include <pwb/job_runtime/resource_budget.hpp>
#include <pwb/job_runtime/resource_governor.hpp>

#include "job_test.hpp"

using pwb::domain::Json;
using namespace pwb::job;

#ifndef PWB_GOVERNOR_ORACLE
#error "PWB_GOVERNOR_ORACLE must point at governor_oracle.json"
#endif

namespace {

Json load_oracle() {
    std::ifstream in(PWB_GOVERNOR_ORACLE);
    if (!in) {
        std::fprintf(stderr, "cannot open oracle: %s\n", PWB_GOVERNOR_ORACLE);
        std::exit(2);
    }
    std::stringstream buffer;
    buffer << in.rdbuf();
    return Json::parse(buffer.str());
}

bool near(double a, double b) { return std::abs(a - b) <= 1e-9; }

void check_near(double actual, double expected, const char* expr,
                const char* file, int line) {
    if (!near(actual, expected)) {
        ++pwb_test::failure_count();
        std::fprintf(stderr, "FAIL %s:%d: %s — actual %g, expected %g\n",
                     file, line, expr, actual, expected);
    }
}
#define PWB_CHECK_NEAR(actual, expected)                                       \
    check_near((actual), (expected), #actual, __FILE__, __LINE__)

// ---------------------------------------------------------------- env ---

void set_env(const char* name, const char* value) {
#ifdef _WIN32
    _putenv_s(name, value);
#else
    ::setenv(name, value, 1);
#endif
}
void unset_env(const char* name) {
#ifdef _WIN32
    _putenv_s(name, "");
#else
    ::unsetenv(name);
#endif
}

constexpr const char* kEnvKeys[] = {
    "PALEO_BUDGET_RAM_GB", "PALEO_BUDGET_CORES", "PALEO_IO_SLOTS",
    "PALEO_BACKGROUND_NICE"};

// ------------------------------------------------------------ clocks ----

class ScriptedClock {
public:
    explicit ScriptedClock(std::vector<double> times)
        : times_(std::move(times)) {}
    double operator()() {
        const double t = times_[std::min(index_, times_.size() - 1)];
        ++index_;
        return t;
    }

private:
    std::vector<double> times_;
    std::size_t index_ = 0;
};

MemorySampler scripted_sampler(const Json& samples) {
    auto state = std::make_shared<std::pair<std::vector<MemorySample>,
                                            std::size_t>>();
    for (const auto& row : samples) {
        state->first.push_back(MemorySample{
            row[0].get<double>(), row[1].get<std::int64_t>(),
            row[2].get<std::int64_t>()});
    }
    return [state](const ResourceBudget&) -> MemorySample {
        const MemorySample s =
            state->first[std::min(state->second, state->first.size() - 1)];
        ++state->second;
        return s;
    };
}

// ----------------------------------------------------------- budgets ----

void replay_budgets(const Json& oracle) {
    for (const auto& row : oracle["budgets"]) {
        const std::string name = row["name"].get<std::string>();
        ResourceBudget budget;
        bool built = false;
        if (name.rfind("for_total_ram:", 0) == 0) {
            budget = ResourceBudget::for_total_ram_gb(
                std::stod(name.substr(14)));
            built = true;
        } else {
            // "cores:N[,ceiling:M|,reserve:R]"
            for (std::size_t pos = 0; pos <= name.size();) {
                const std::size_t comma = name.find(',', pos);
                const std::string seg = name.substr(
                    pos, comma == std::string::npos ? comma : comma - pos);
                const std::size_t colon = seg.find(':');
                const std::string key = seg.substr(0, colon);
                const int value = std::stoi(seg.substr(colon + 1));
                if (key == "cores") budget.logical_cores = value;
                if (key == "ceiling") budget.background_core_ceiling = value;
                if (key == "reserve") budget.interactive_reserve_cores = value;
                pos = comma == std::string::npos ? name.size() + 1 : comma + 1;
            }
            built = true;
        }
        PWB_CHECK(built);
        const Json& e = row["expected"];
        const bool auto_cores = e["logical_cores"].get<int>() == 0;
        PWB_CHECK_NEAR(budget.total_ram_gb, e["total_ram_gb"].get<double>());
        PWB_CHECK_NEAR(budget.os_reserve_gb, e["os_reserve_gb"].get<double>());
        PWB_CHECK_NEAR(budget.python_reserve_gb,
                       e["python_reserve_gb"].get<double>());
        PWB_CHECK(budget.l1_slice_cache_bytes ==
                  e["l1_slice_cache_bytes"].get<std::int64_t>());
        PWB_CHECK(budget.streaming_buffer_bytes ==
                  e["streaming_buffer_bytes"].get<std::int64_t>());
        PWB_CHECK(budget.vram_budget_mb == e["vram_budget_mb"].get<int>());
        PWB_CHECK(budget.logical_cores == e["logical_cores"].get<int>());
        PWB_CHECK(budget.interactive_reserve_cores ==
                  e["interactive_reserve_cores"].get<int>());
        PWB_CHECK(budget.background_core_ceiling ==
                  e["background_core_ceiling"].get<int>());
        PWB_CHECK_NEAR(budget.io_slots, e["io_slots"].get<double>());
        PWB_CHECK(budget.background_nice == e["background_nice"].get<int>());
        PWB_CHECK_NEAR(budget.ram_pressure_frac,
                       e["ram_pressure_frac"].get<double>());
        PWB_CHECK_NEAR(budget.ram_critical_frac,
                       e["ram_critical_frac"].get<double>());
        PWB_CHECK_NEAR(budget.page_cache_floor_gb(),
                       e["page_cache_floor_gb"].get<double>());
        if (!auto_cores) {
            // Host-dependent when logical_cores==0 (auto-detect) — the
            // freeze ran on the generating host.
            PWB_CHECK(budget.detected_logical_cores() ==
                      e["logical_cores"].get<int>());
            PWB_CHECK(budget.background_cores() ==
                      e["background_cores"].get<int>());
            PWB_CHECK(budget.heavy_task_core_allowance() ==
                      e["heavy_task_core_allowance"].get<int>());
        }
    }
}

void replay_pressure_scale(const Json& oracle) {
    for (const auto& row : oracle["pressure_scale"]) {
        const Json& in = row["input"];
        ResourceBudget budget;
        budget.logical_cores = in["logical_cores"].get<int>();
        budget.background_core_ceiling =
            in["background_core_ceiling"].get<int>();
        budget.io_slots = in["io_slots"].get<double>();
        const ResourceBudget scaled =
            budget.with_pressure_scale(in["factor"].get<double>());
        const Json& e = row["expected"];
        PWB_CHECK(scaled.background_core_ceiling ==
                  e["background_core_ceiling"].get<int>());
        PWB_CHECK(scaled.background_cores() ==
                  e["background_cores"].get<int>());
        PWB_CHECK_NEAR(scaled.io_slots, e["io_slots"].get<double>());
    }
}

void replay_env_overrides(const Json& oracle) {
    for (const auto& row : oracle["env_overrides"]) {
        for (const char* key : kEnvKeys) unset_env(key);
        for (const auto& [key, value] : row["env"].items()) {
            set_env(key.c_str(), value.get<std::string>().c_str());
        }
        reset_active_budget();
        const ResourceBudget budget = active_budget();
        const Json& e = row["expected"];
        PWB_CHECK(budget.logical_cores == e["logical_cores"].get<int>());
        PWB_CHECK_NEAR(budget.io_slots, e["io_slots"].get<double>());
        PWB_CHECK(budget.background_nice == e["background_nice"].get<int>());
        PWB_CHECK_NEAR(budget.total_ram_gb, e["total_ram_gb"].get<double>());
        if (budget.logical_cores > 0) {
            PWB_CHECK(budget.background_cores() ==
                      e["background_cores"].get<int>());
        }
        for (const char* key : kEnvKeys) unset_env(key);
        reset_active_budget();
    }
}

// ------------------------------------------------------------ monitor ---

void replay_monitor(const Json& oracle) {
    for (const auto& row : oracle["monitor"]) {
        if (row["name"] == "classify_grid") {
            for (const auto& cell : row["grid"]) {
                const PressureState state = classify_pressure(
                    cell["used_frac"].get<double>(),
                    cell["pressure_frac"].get<double>(),
                    cell["critical_frac"].get<double>());
                PWB_CHECK_EQ_STR(pressure_state_id(state),
                                 cell["state"].get<std::string>());
            }
            continue;
        }
        const Json& in = row["input"];
        std::vector<double> times;
        for (const auto& t : in["clock"]) times.push_back(t.get<double>());
        auto clock = std::make_shared<ScriptedClock>(std::move(times));
        MemoryPressureMonitor monitor(
            ResourceBudget{.logical_cores = 8}, in["interval"].get<double>(),
            [clock] { return (*clock)(); },
            scripted_sampler(in["samples"]));
        for (const auto& [name, freed] : in["evictables"].items()) {
            if (freed.is_string()) {  // "raise" sentinel
                monitor.register_evictable(name, []() -> std::int64_t {
                    throw std::runtime_error("evictable exploded");
                });
            } else {
                monitor.register_evictable(
                    name, [f = freed.get<std::int64_t>()] { return f; });
            }
        }
        std::vector<std::string> states;
        const int rebind_at = in["rebind_at"].is_null()
                                  ? -1
                                  : in["rebind_at"].get<int>();
        for (std::size_t i = 0; i < in["ops"].size(); ++i) {
            if (static_cast<int>(i) == rebind_at) {
                ResourceBudget rebound{.logical_cores = 8};
                for (const auto& [key, value] : in["rebind"].items()) {
                    if (key == "ram_pressure_frac")
                        rebound.ram_pressure_frac = value.get<double>();
                    if (key == "ram_critical_frac")
                        rebound.ram_critical_frac = value.get<double>();
                }
                monitor.rebind_budget(rebound);
            }
            const bool refresh = in["ops"][i] == "refresh";
            states.push_back(pressure_state_id(monitor.state(refresh)));
        }
        const Json& e = row["expected"];
        const std::size_t want = e["states"].size();
        PWB_CHECK(states.size() == want);
        for (std::size_t i = 0; i < std::min(states.size(), want); ++i) {
            PWB_CHECK_EQ_STR(states[i], e["states"][i].get<std::string>());
        }
        const MemoryPressureSnapshot snap = monitor.snapshot();
        PWB_CHECK(snap.relief_runs == e["relief_runs"].get<std::int64_t>());
        PWB_CHECK(snap.relief_freed_bytes ==
                  e["relief_freed_bytes"].get<std::int64_t>());
        std::vector<std::string> want_evictables;
        for (const auto& n : e["evictables"])
            want_evictables.push_back(n.get<std::string>());
        PWB_CHECK(snap.evictables == want_evictables);
    }
}

// ----------------------------------------------------------- governor ---

JobCategory category_from_wire(const std::string& id) {
    for (int i = 0; i <= static_cast<int>(JobCategory::maintenance); ++i) {
        const auto category = static_cast<JobCategory>(i);
        if (id == category_id(category)) return category;
    }
    return JobCategory::background_io;
}

void replay_governor(const Json& oracle) {
    for (const auto& row : oracle["governor"]) {
        if (row["name"] == "from_kind_defaults") {
            for (const auto& req : row["requests"]) {
                const TaskRequest request =
                    TaskRequest::from_kind(req["kind"].get<std::string>());
                PWB_CHECK_EQ_STR(category_id(request.category),
                                 req["category"].get<std::string>());
                PWB_CHECK(request.effective_priority() ==
                          req["effective_priority"].get<int>());
                PWB_CHECK_NEAR(request.effective_io_weight(),
                               req["effective_io_weight"].get<double>());
            }
            continue;
        }
        const Json& in = row["input"];
        auto monitor_clock = std::make_shared<ScriptedClock>(
            std::vector<double>(1024, 0.0));
        auto governor_clock = std::make_shared<ScriptedClock>(
            std::vector<double>(2048, 0.0));
        MemoryPressureMonitor monitor(
            ResourceBudget{.logical_cores = in["cores"].get<int>()}, 0.0,
            [monitor_clock] { return (*monitor_clock)(); },
            scripted_sampler(in["pressure_samples"]));
        ResourceBudget budget;
        budget.logical_cores = in["cores"].get<int>();
        budget.background_core_ceiling = in["ceiling"].get<int>();
        budget.io_slots = in["io_slots"].get<double>();
        budget.total_ram_gb = in["ram_gb"].get<double>();
        budget.vram_budget_mb = in["vram_mb"].get<int>();
        ResourceGovernor governor(budget, &monitor,
                                  [governor_clock] { return (*governor_clock)(); });

        std::vector<std::unique_ptr<ResourceLease>> leases;
        const Json& ops = row["ops"];
        for (std::size_t i = 0; i < ops.size(); ++i) {
            const Json& op = ops[i];
            const Json& expected = row["steps"][i];
            const std::string kind = op[0].get<std::string>();
            if (kind == "admit" || kind == "try") {
                const Json& kw = op[2];
                const double cpu = kw.contains("estimated_cpu_cores")
                                       ? kw["estimated_cpu_cores"].get<double>()
                                       : 1.0;
                const std::int64_t ram =
                    kw.contains("estimated_ram_bytes")
                        ? kw["estimated_ram_bytes"].get<std::int64_t>()
                        : 0;
                const std::int64_t vram =
                    kw.contains("estimated_vram_bytes")
                        ? kw["estimated_vram_bytes"].get<std::int64_t>()
                        : 0;
                TaskRequest request =
                    TaskRequest::from_kind(op[1].get<std::string>(), {}, "",
                                           cpu, ram, vram, "");
                if (kind == "admit") {
                    try {
                        leases.push_back(governor.admit(request));
                        PWB_CHECK_EQ_STR("lease",
                                         expected["result"].get<std::string>());
                    } catch (const ResourceExhausted& err) {
                        PWB_CHECK_EQ_STR("raise",
                                         expected["result"].get<std::string>());
                        PWB_CHECK_EQ_STR(err.reason(),
                                         expected["reason"].get<std::string>());
                        PWB_CHECK(err.retryable() ==
                                  expected["retryable"].get<bool>());
                        PWB_CHECK_EQ_STR(err.pressure(),
                                         expected["pressure"].get<std::string>());
                    }
                } else {
                    std::unique_ptr<ResourceLease> lease =
                        governor.try_admit(request);
                    const char* result = lease ? "lease" : "defer";
                    if (lease) leases.push_back(std::move(lease));
                    PWB_CHECK_EQ_STR(result,
                                     expected["result"].get<std::string>());
                }
            } else if (kind == "release") {
                const std::size_t idx = op[1].get<std::size_t>();
                if (idx < leases.size() && leases[idx]) {
                    leases[idx]->release();
                    leases[idx].reset();
                }
            } else if (kind == "allowance") {
                const std::optional<int> requested =
                    op[2].is_null()
                        ? std::nullopt
                        : std::optional<int>(op[2].get<int>());
                PWB_CHECK(governor.cpu_allowance(
                              category_from_wire(op[1].get<std::string>()),
                              requested) == expected["value"].get<int>());
            } else if (kind == "io_slots") {
                PWB_CHECK_NEAR(governor.io_slots(),
                               expected["value"].get<double>());
            } else if (kind == "onnx") {
                PWB_CHECK(governor.onnx_thread_allowance() ==
                          expected["value"].get<int>());
            } else if (kind == "pressure") {
                PWB_CHECK_EQ_STR(pressure_state_id(governor.pressure_state()),
                                 expected["value"].get<std::string>());
            } else if (kind == "status") {
                const GovernorStatus status = governor.runtime_status();
                const Json& reserved = expected["reserved"];
                PWB_CHECK_NEAR(status.reserved_cores,
                               reserved["cores"].get<double>());
                PWB_CHECK(status.reserved_ram_bytes ==
                          reserved["ram_bytes"].get<std::int64_t>());
                PWB_CHECK(status.reserved_vram_bytes ==
                          reserved["vram_bytes"].get<std::int64_t>());
                PWB_CHECK_NEAR(status.reserved_io_weight,
                               reserved["io_weight"].get<double>());
                PWB_CHECK(status.active_leases ==
                          reserved["active_leases"].get<std::int64_t>());
                PWB_CHECK(status.background_cores_effective ==
                          expected["bg_effective"].get<int>());
                PWB_CHECK_NEAR(status.io_slots_effective,
                               expected["io_effective"].get<double>());
            } else {
                PWB_CHECK(false);  // unknown op — fixture/test drift
            }
        }
        leases.clear();  // release everything like the generator does
        const GovernorStatus status = governor.runtime_status();
        const Json& m = row["metrics"];
        PWB_CHECK(status.metrics.admitted == m["admitted"].get<std::int64_t>());
        PWB_CHECK(status.metrics.deferred == m["deferred"].get<std::int64_t>());
        PWB_CHECK(status.metrics.rejected == m["rejected"].get<std::int64_t>());
        PWB_CHECK(status.metrics.released == m["released"].get<std::int64_t>());
        PWB_CHECK(status.metrics.pressure_rejections ==
                  m["pressure_rejections"].get<std::int64_t>());
        PWB_CHECK(status.active_leases ==
                  m["active_leases"].get<std::int64_t>());
    }
}

}  // namespace

TEST(governor_oracle_replay) {
    const Json oracle = load_oracle();
    PWB_CHECK(oracle["schema"] == "pwb.governor_oracle/1");
    replay_budgets(oracle);
    replay_pressure_scale(oracle);
    replay_env_overrides(oracle);
    replay_monitor(oracle);
    replay_governor(oracle);
}

int main() { return pwb_test_main(); }
