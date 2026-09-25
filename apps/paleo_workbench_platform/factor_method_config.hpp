#pragma once

// ws2 插值方法/参数/等值线间距的生产状态（factor.method / factor.params /
// factor.contour_interval 三个 Ribbon 命令的真实后端）。
//
// 单一权威 = ProjectDocument：
//   root["factor_settings"]   = {"method": "...", "params": {grid_n, power,
//                                seed, variogram_model?, variogram_range?,
//                                variogram_nugget?}}
//   root["contour_settings"]  = {"interval_m": <double>}
// 写路径走 store 的文档轮次（set_document_section + save_document）——一次
// 落盘，重开工程状态一致；读路径缺省即诚实默认（绝不伪造已保存值）。
//
// 方法清单来自 factor_host method_backend_table + 本线生产内核的真实
// 支持面（idw/kriging/constrained_idw/cubic/directional 五后端全部原生）。

#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::application {
class PwbDataStore;
}

namespace pwb::app::factor_config {

struct MethodOption {
    std::string label;       // 与 FactorTaskPanel method_combo 同一词汇
    std::string backend;     // factor_host backend key
    std::string description; // 与 page_tokens tooltips 同一文案
};

// The method registry — only backends the native kernels implement.
const std::vector<MethodOption>& available_methods();

// Label → backend for the registry labels ("" for unknown). Local map so
// this module never links the factor_host kernel slice.
std::string backend_of_label(const std::string& label);

struct RunParams {
    int grid_n = 50;          // [20, 200]（插值核钳制区间；进 geometry 指纹）
    double power = 2.0;       // idw / constrained_idw（进 algorithm 指纹）
    int seed = 0;             // 合成样本种子
};

// 注：克里金的变差函数由引擎按样本自动拟合（kriging_diagnostics 记录
// nugget/sill/range），不在用户参数面 —— 换参不触发重算的参数绝不暴露。

// 校验（对话框 OK 与 compute 前同一守卫）：返回空 = 可用。
std::string validate_params(const RunParams& params,
                            const std::string& backend);

// ---- 文档读写（store 为空 → 默认值/失败，绝不写临时状态） ----------------

std::string read_method(pwb::application::PwbDataStore* store);
RunParams read_params(pwb::application::PwbDataStore* store);

// method 写入 + 落盘；store 为空 → false（"先打开工程"）。
bool write_method(pwb::application::PwbDataStore* store,
                  const std::string& method, std::string* error);
bool write_params(pwb::application::PwbDataStore* store,
                  const RunParams& params, std::string* error);

// 等值线间距（m）。read 0.0 = 未设置（等值线生成走 nice 阶梯默认）。
double read_contour_interval(pwb::application::PwbDataStore* store);
bool write_contour_interval(pwb::application::PwbDataStore* store,
                            double interval_m, std::string* error);

}  // namespace pwb::app::factor_config
