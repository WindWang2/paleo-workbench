// 05 线 — XML 井曲线的 WLE 文档装配（make_wle_load_fn 的 XML 分派后端）。
// 产物与 LAS 路径同一载荷类型 WleDocumentPayload：真 welllog::WellLogDocument
// （采样轴 + 曲线 + 区间/标记实体），消费者（dock/预览页）无差别。
//
// 事实口径（与冻结 Python 一致）：
//   * XML 井数据不声明深度单位 → 轴单位保持空（未声明状态，绝不推断）；
//   * 反向深度（自深至浅）是合法形状 → 按坐标缓冲真实方向声明；
//   * 缺测样本 = NaN 值（保留，不丢行）；坏深度行整行剔除（参考语义）；
//   * 载荷 diagnostics = 0（XML 路径无可恢复解析警告；NaN 是数据事实，
//     不是诊断）。

#include "pwb/ui_workers/wle_load.hpp"

#include <welllog/core/document.hpp>

#include "pwb/ui_workers/well_log_xml_data.hpp"

namespace pwb::ui_workers {

namespace {

welllog::IntervalSemantic interval_semantic_for(bool lithology,
                                                bool facies,
                                                bool stratigraphy) {
    if (lithology) return welllog::IntervalSemantic::lithology;
    if (facies) return welllog::IntervalSemantic::facies;
    if (stratigraphy) return welllog::IntervalSemantic::stratigraphy;
    return welllog::IntervalSemantic::custom;
}

void add_intervals(welllog::WellLogDocumentBuilder& builder,
                   const std::vector<WellLogXmlInterval>& items,
                   welllog::IntervalSemantic semantic) {
    for (const WellLogXmlInterval& item : items) {
        if (!(item.top < item.bottom)) continue;  // 实体约束：top < bottom
        welllog::Interval entity;
        entity.id = welllog::EntityId::generate();
        entity.top_reference_depth = item.top;
        entity.bottom_reference_depth = item.bottom;
        entity.semantic = semantic;
        entity.label = item.label;
        builder.add_interval(entity);
    }
}

}  // namespace

std::optional<LoadedWellLog> load_well_log_xml(std::string_view bytes,
                                               const std::string& path,
                                               const std::function<bool()>&
                                                   is_cancelled) {
    if (is_cancelled && is_cancelled()) {
        throw WellLogLoadCancelled{};
    }
    if (!is_well_log_xml_bytes(bytes)) {
        return std::nullopt;  // 非井曲线 XML：诚实不可解析（同 LAS 路径）
    }
    auto slash = path.find_last_of("/\\");
    const std::string name =
        slash == std::string::npos ? path : path.substr(slash + 1);
    WellLogXmlData data;
    try {
        data = parse_well_log_xml(bytes, name);
    } catch (const std::invalid_argument&) {
        return std::nullopt;  // Python：ValueError → load 返回 None
    }
    if (is_cancelled && is_cancelled()) {
        throw WellLogLoadCancelled{};
    }

    welllog::WellLogDocumentBuilder builder(welllog::EntityId::generate(),
                                            welllog::DocumentRevision{1});
    for (const WellLogXmlCurve& curve : data.curves) {
        auto axis_id = welllog::EntityId::generate();
        welllog::SamplingAxis axis;
        axis.id = axis_id;
        axis.coordinates = welllog::BufferView::from_vector(curve.depth);
        axis.domain = welllog::DepthDomain::measured_depth;
        axis.unit = "";  // XML 不声明深度单位——保持未声明
        if (curve.depth != nullptr && curve.depth->size() >= 2 &&
            curve.depth->back() < curve.depth->front()) {
            axis.direction = welllog::AxisDirection::decreasing;
        }
        builder.add_sampling_axis(axis);
        welllog::Curve entity;
        entity.id = welllog::EntityId::generate();
        entity.mnemonic = curve.name;
        entity.display_name = curve.name;
        entity.unit = curve.unit;
        entity.sampling_axis_id = axis_id;
        entity.values = welllog::BufferView::from_vector(curve.values);
        builder.add_curve(entity);
    }
    add_intervals(builder, data.lithology,
                  interval_semantic_for(true, false, false));
    add_intervals(builder, data.facies,
                  interval_semantic_for(false, true, false));
    add_intervals(builder, data.formation,
                  interval_semantic_for(false, false, true));
    add_intervals(builder, data.text_desc,
                  interval_semantic_for(false, false, false));
    for (const WellLogXmlInterval& horizon : data.horizons) {
        welllog::Marker entity;
        entity.id = welllog::EntityId::generate();
        entity.reference_depth = horizon.top;
        entity.semantic = welllog::MarkerSemantic::formation_top;
        entity.label = horizon.label;
        builder.add_marker(entity);
    }

    WleDocumentPayload payload;
    payload.document = std::make_shared<const welllog::WellLogDocument>(
        builder.build());
    payload.diagnostics = 0;
    LoadedWellLog loaded;
    loaded.data = std::move(payload);
    loaded.well_name = data.well_name;
    return loaded;
}

}  // namespace pwb::ui_workers
