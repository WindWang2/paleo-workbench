#pragma once

// 05 线 — viz_b 连井 dock 的真实 LAS 数据通路（findings.md 缺口 2）。
//
// B 线交付时 dock 只吃 JSON 井库（header 注释明示 "LAS arrives through
// the same seam once line A's parser merges"）。本文件就是那个 seam 的
// 兑现：每个 .las 经与测井页完全相同的 WellLogLoadFn 生产实现
//（make_wle_load_fn → WLE LasSourceAdapter）解析，把真 WLE 文档曲线转成
// 连井列 WellColumnData。
//
// 转换口径（诚实声明）：
//   * 井名 = 载荷 well_name（~W 扫描 / XML 显式字段 / 文件名兜底）；
//   * 每条文档曲线 → 一条 WellCurve：depths/values 为该曲线自己的采样轴
//     与值；缺测对（值非有限或深度非有限）成对剔除——连井核心
//    （DTW/剖面/相关）不接受 NaN；JSON 井库路径（冻结 fixture 生成时
//     已去缺测）与本路径由此保持同一形状契约；
//   * LAS 不携带井口坐标 → coords 恒空数组（auto-arrange 诚实 no-op，
//     与 JSON 路径"坐标缺失"分支同一语义）；
//   * 解析失败/空井逐文件记入 errors，不拖垮其余文件（部分成功可见）。
//
// WLE 头仅本翻译单元接触；dock 侧经 load_wells_from_las 使用。

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <QString>
#include <QStringList>

#include <pwb/domain/json.hpp>
#include <pwb/ui_workers/viz_resolve.hpp>
#include <pwb/viz/cross_well/section_geometry.hpp>

namespace welllog {
class WellLogDocument;
}

namespace pwb::app {

struct VizBLasSourceResult {
    std::vector<pwb::viz::cross_well::WellColumnData> wells;
    // 恒为 JSON 数组；LAS 无坐标，保持空（诚实 no-op 语义）。
    pwb::domain::Json coords = pwb::domain::Json::array();
    // 逐文件的失败原因（路径 + 原因），加载部分成功时用户可见。
    QStringList errors;
    // 取消检查点命中（文件边界）——与失败区分，调用方按取消处理。
    bool cancelled = false;
};

// 单个已解析文档 → 连井列。无可用曲线（全部缺测/无样本）→ nullopt。
std::optional<pwb::viz::cross_well::WellColumnData> well_column_from_document(
    const welllog::WellLogDocument& document,
    const std::string& well_name);

// 批量加载：每路径经 load_fn；is_cancelled（可空）在文件间检查——解析
// 单文件本身不可中断（WLE 单调用，Python 同语义），取消发生在下一个
// 文件边界。逐文件失败记入结果，全部失败/零井 → wells 为空。
VizBLasSourceResult load_wells_from_las(
    const QStringList& paths, const pwb::ui_workers::WellLogLoadFn& load_fn,
    const std::function<bool()>& is_cancelled = {});

}  // namespace pwb::app
