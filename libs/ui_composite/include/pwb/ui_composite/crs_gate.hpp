#pragma once

// Port of paleo_workbench/mapping_workspace/crs_gate.py (UI-13): V11 M0
// (#1285) 可编辑层 CRS 契约——进前域校验 + 引导式修复。
//
// 已知事故形态：声明 EPSG:4326（±180/±90 地理域）+ 数据坐标 0–16000
//（本地坐标）。本模块在进入编辑前做声明的有效坐标域 vs 数据实际坐标
// 范围的失配检测，产出机器可读结果与修复选项；修复（改声明为本地 /
// 清除声明）由宿主对话框执行，同一检测在打开工程时兜底再跑一次。
//
// 纯函数、无 Qt/桥依赖（fallback 画布同样可用）；地理 CRS 识别用已知
// authid 集 + "+proj=longlat" 前缀（PROJ 字符串声明）。

#include <array>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#include <pwb/ui_data_core/map_edit_geometry.hpp>

namespace pwb::ui_composite {

using pwb::ui_data_core::MapPoint;
using Bounds = std::array<double, 4>;

// 常见地理（经纬度）CRS authid（域 ±180/±90，容差 1° 供球面溢出）。
const std::set<std::string>& geographic_authids();

// 进前域校验结果（机器可读；宿主据此阻止进入编辑并给出引导）。
struct CrsDomainCheck {
    bool ok = true;
    std::string declared_crs;
    bool geographic_declared = false;
    std::optional<Bounds> bounds;
    std::string reason;

    // 修复选项（"declare_local" 推荐 / "clear"）；ok 时为空。
    std::vector<std::string> fix_options() const {
        return ok ? std::vector<std::string>{}
                  : std::vector<std::string>{"declare_local", "clear"};
    }

    bool operator==(const CrsDomainCheck&) const = default;
};

// 声明的 CRS 是否地理（经纬度）坐标系。
bool is_geographic_declaration(const std::string& declared_crs);

// 坐标流（[x, y]）的包围盒；空 → nullopt。
std::optional<Bounds> feature_bounds(
    const std::vector<MapPoint>& coords);

// 声明的坐标域 vs 数据实际范围（进前段门禁的机器判定）。
CrsDomainCheck validate_crs_domain(
    const std::string& declared_crs,
    const std::optional<Bounds>& bounds);

// 失配原因文本（与 Python f-string 措辞一致）。
std::string crs_mismatch_reason(const std::string& declared,
                                const Bounds& bounds);

// 工程打开兜底检测：(layer_id, declared_crs, coords) 流 → 失配表。
// 一次修复永久生效（声明更正后进前门禁自然放行）。
std::map<std::string, CrsDomainCheck> collect_crs_mismatches(
    const std::vector<std::tuple<std::string, std::string,
                                 std::vector<MapPoint>>>& layers);

}  // namespace pwb::ui_composite
