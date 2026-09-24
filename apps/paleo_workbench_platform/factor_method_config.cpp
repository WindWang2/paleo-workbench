// factor_method_config — see the header for the document-authority
// contract. Qt-free (the dialogs live in factor_method_dialogs.cpp).

#include "factor_method_config.hpp"

#include <cmath>

#include <pwb/application/adapters/data_store.hpp>

namespace pwb::app::factor_config {

namespace {

using pwb::domain::Json;

// The production method registry: the SAME labels the FactorTaskPanel
// combo offers, filtered to backends the native kernels implement — the
// mock entry and any unknown label never appear here.
const std::vector<MethodOption>& registry() {
    static const std::vector<MethodOption> methods = {
        {"IDW", "idw",
         "反距离加权；支持断层屏障 fault_polylines"},
        {"克里金", "kriging",
         "真实普通克里金：经验变差函数拟合 + 克里金求解（含克里金方差）"},
        {"约束IDW", "constrained_idw",
         "约束反距离加权：断层/屏障区域分割 + 方向走廊各向异性 + 井点锚定"
         "（需边界/≥3 个有效控制点）"},
        {"样条", "cubic",
         "SciPy cubic 样条插值（Clough-Tocher C1）"},
        {"方向趋势", "directional",
         "各向异性方向加权趋势面（ISS-ALG-02）"},
    };
    return methods;
}

Json read_section(pwb::application::PwbDataStore* store,
                  const char* name) {
    if (store == nullptr) return Json();
    try {
        return store->coordinator().document_section(name,
                                                     store->document());
    } catch (const std::exception&) {
        return Json();
    }
}

// write_section: one document round — mutate + save; an unsaved mutation
// is a failure, never a success.
bool write_section(pwb::application::PwbDataStore* store, const char* name,
                   const Json& section, std::string* error) {
    if (store == nullptr) {
        if (error != nullptr) *error = "先打开工程（设置随工程保存）";
        return false;
    }
    try {
        store->coordinator().set_document_section(name, section,
                                                  store->document());
        const auto save_error = store->save_document();
        if (!save_error.ok()) {
            if (error != nullptr) *error = save_error.message;
            return false;
        }
        return true;
    } catch (const std::exception& exc) {
        if (error != nullptr) *error = exc.what();
        return false;
    }
}

}  // namespace

const std::vector<MethodOption>& available_methods() { return registry(); }

std::string backend_of_label(const std::string& label) {
    for (const MethodOption& option : registry()) {
        if (option.label == label) return option.backend;
    }
    return std::string();
}

std::string validate_params(const RunParams& params,
                            const std::string& backend) {
    if (params.grid_n < 20 || params.grid_n > 200) {
        return "网格分辨率 grid_n 必须在 20–200（插值核钳制区间）";
    }
    if ((backend == "idw" || backend == "constrained_idw")
        && !(params.power >= 0.5 && params.power <= 8.0)) {
        return "IDW 幂参数必须在 0.5–8.0";
    }
    return std::string();
}

std::string read_method(pwb::application::PwbDataStore* store) {
    const Json section = read_section(store, "factor_settings");
    const auto it = section.find("method");
    if (it == section.end() || !it->is_string()) return std::string();
    const std::string method = it->get<std::string>();
    for (const auto& option : registry()) {
        if (option.label == method) return method;
    }
    return std::string();
}

RunParams read_params(pwb::application::PwbDataStore* store) {
    RunParams params;
    const Json section = read_section(store, "factor_settings");
    const auto params_it = section.find("params");
    if (params_it == section.end() || !params_it->is_object()) {
        return params;
    }
    const auto& saved = *params_it;
    if (const auto it = saved.find("grid_n");
        it != saved.end() && it->is_number_integer()) {
        params.grid_n = static_cast<int>(it->get<long long>());
    }
    if (const auto it = saved.find("power");
        it != saved.end() && it->is_number()) {
        params.power = it->get<double>();
    }
    if (const auto it = saved.find("seed");
        it != saved.end() && it->is_number_integer()) {
        params.seed = static_cast<int>(it->get<long long>());
    }
    return params;
}

bool write_method(pwb::application::PwbDataStore* store,
                  const std::string& method, std::string* error) {
    bool known = false;
    for (const auto& option : registry()) {
        if (option.label == method) known = true;
    }
    if (!known) {
        if (error != nullptr) *error = "未知插值方法：" + method;
        return false;
    }
    Json section = read_section(store, "factor_settings");
    if (!section.is_object()) section = Json::object();
    section["method"] = method;
    return write_section(store, "factor_settings", section, error);
}

bool write_params(pwb::application::PwbDataStore* store,
                  const RunParams& params, std::string* error) {
    const std::string method = read_method(store);
    const std::string backend =
        backend_of_label(method).empty() ? std::string("idw")
                                         : backend_of_label(method);
    const std::string problem = validate_params(params, backend);
    if (!problem.empty()) {
        if (error != nullptr) *error = problem;
        return false;
    }
    Json section = read_section(store, "factor_settings");
    if (!section.is_object()) section = Json::object();
    Json saved = Json::object();
    saved["grid_n"] = params.grid_n;
    saved["power"] = params.power;
    saved["seed"] = params.seed;
    section["params"] = std::move(saved);
    return write_section(store, "factor_settings", section, error);
}

double read_contour_interval(pwb::application::PwbDataStore* store) {
    const Json section = read_section(store, "contour_settings");
    const auto it = section.find("interval_m");
    if (it == section.end() || !it->is_number()) return 0.0;
    const double value = it->get<double>();
    return std::isfinite(value) && value > 0.0 ? value : 0.0;
}

bool write_contour_interval(pwb::application::PwbDataStore* store,
                            double interval_m, std::string* error) {
    if (!(std::isfinite(interval_m) && interval_m > 0.0)) {
        if (error != nullptr) *error = "等值线间距必须是正数（米）";
        return false;
    }
    Json section = Json::object();
    section["interval_m"] = interval_m;
    return write_section(store, "contour_settings", section, error);
}

}  // namespace pwb::app::factor_config
