#pragma once

// 05 线 — well/time-depth presenter 安装器（05→04 合同的生产接线半）。
//
// 职责：把两类 ExternalPresenter 注册进 viz-e 的进程级注册表
//（viz_e_install.hpp 的 register_external_presenter），使 04 数据页对
// .las/.xml 井资产与时深 CSV 资产出真井曲线页/时深页：
//   * kind "well_log"：经与测井页/连井页同一的 WellLogLoadFn 生产 seam
//     加载（WLE 桥在构建中时为真解析；否则诚实诊断页）；
//   * kind "time_depth"：经 Pwb::VisualizationCrossWell 的 SeismicTie
//     读 checkshot CSV，探针绑定其 CheckshotTable 插值（权威核不重写）。
//
// install() 幂等：注册表 first-wins，重复调用返回 false（装配 bug 会
// 被 viz_e 的响亮拒绝暴露）。GUI 线程调用。

namespace pwb::app::well_presenters {

// 返回是否全部注册成功（注册表已含同名 kind 时为 false）。
bool install();

}  // namespace pwb::app::well_presenters
