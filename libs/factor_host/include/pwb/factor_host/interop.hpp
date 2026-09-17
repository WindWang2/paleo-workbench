#pragma once

// pwb::factor_host — small pure leaves of
// paleo_workbench/workflow/factor_interpolation.py (CONV-08):
// method-label resolution, variogram parameter extraction, and the recorded
// (method, grid_n, power) recovery. The FactorMapTask / ProjectDocument
// orchestration around them stays on the host.
// Qt-free, Python-free, numpy-free.

#include <pwb/domain/json.hpp>

#include <string>
#include <tuple>

namespace pwb::factor_host {

using pwb::domain::Json;

inline constexpr int kDefaultGridN = 50;

// UI / registry method id → engine backend. Unknown ids throw
// std::invalid_argument with the Python message (sorted label list).
std::string resolve_engine_method(const std::string& method);

// Explicit variogram controls recorded on a task (single authority);
// empty object = auto-fit. Production interpolation AND cross-validation
// read this mapping.
Json variogram_settings_from_params(const Json& params);

// Recover (method, grid_n, power) previously recorded on a task (#919):
// task.parameters + the task's own method; Python truthiness governs the
// fallbacks (0 / "" / null / empty containers fall to the defaults).
std::tuple<std::string, int, double> interp_params_from_task(
    const Json& params, const std::string& task_method);

}  // namespace pwb::factor_host
