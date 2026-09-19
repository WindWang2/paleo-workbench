// 05 线 — viz_b 真实 LAS 数据通路实现（见头注释的转换口径）。

#include "viz_b_well_source.hpp"

#include <cmath>

#include <QObject>

#include <welllog/core/document.hpp>

namespace pwb::app {

namespace {

bool finite(double v) { return std::isfinite(v); }

}  // namespace

std::optional<pwb::viz::cross_well::WellColumnData> well_column_from_document(
    const welllog::WellLogDocument& document, const std::string& well_name) {
    pwb::viz::cross_well::WellColumnData column;
    column.name = well_name;
    for (const welllog::Curve& curve : document.curves()) {
        // 采样轴：曲线经 sampling_axis_id 引用共享轴；LAS/文档每曲线
        // 一条私有轴（host build_document 同构）。
        const welllog::SamplingAxis* axis = nullptr;
        for (const welllog::SamplingAxis& candidate : document.sampling_axes()) {
            if (candidate.id == curve.sampling_axis_id) {
                axis = &candidate;
                break;
            }
        }
        if (axis == nullptr) continue;
        const auto coords = axis->coordinates.as_single();
        const auto values = curve.values.as_single();
        const std::size_t n = std::min(coords.length(), values.length());
        pwb::viz::cross_well::WellCurve out;
        out.name = curve.mnemonic;
        for (std::size_t i = 0; i < n; ++i) {
            // 类型安全访问（stride/scalar 兼容），null 位图 = 缺测。
            const auto depth = coords.value_as_double(i);
            const auto value = values.value_as_double(i);
            if (!depth.has_value() || !value.has_value()) continue;
            if (curve.nulls.is_null(i)) continue;
            // 缺测对成对剔除（头注释口径）：连井核不接受 NaN。
            if (!finite(*depth) || !finite(*value)) continue;
            out.depths.push_back(*depth);
            out.values.push_back(*value);
        }
        if (!out.name.empty() && out.values.size() >= 2) {
            column.curves.push_back(std::move(out));
        }
    }
    if (column.curves.empty()) return std::nullopt;
    return column;
}

VizBLasSourceResult load_wells_from_las(
    const QStringList& paths, const pwb::ui_workers::WellLogLoadFn& load_fn) {
    VizBLasSourceResult result;
    if (!load_fn) {
        result.errors.append(
            QObject::tr("LAS 解析内核不可用（引擎 load seam 未接线）"));
        return result;
    }
    const std::function<bool()> never_cancelled = [] { return false; };
    for (const QString& path : paths) {
        const std::string path_std = path.toStdString();
        std::optional<pwb::ui_workers::LoadedWellLog> loaded;
        bool cancelled = false;
        try {
            loaded = load_fn(path_std, never_cancelled);
        } catch (const pwb::ui_workers::WellLogLoadCancelled&) {
            cancelled = true;
        } catch (const std::exception& exc) {
            result.errors.append(
                QObject::tr("%1：解析异常 %2")
                    .arg(path, QString::fromLocal8Bit(exc.what())));
            continue;
        }
        if (cancelled) {
            result.errors.append(QObject::tr("%1：已取消").arg(path));
            continue;
        }
        if (!loaded || !loaded->data.has_value()) {
            result.errors.append(
                QObject::tr("%1：无法解析为井数据").arg(path));
            continue;
        }
        const auto* payload =
            std::any_cast<pwb::ui_workers::WleDocumentPayload>(
                &loaded->data);
        if (payload == nullptr || payload->document == nullptr) {
            result.errors.append(QObject::tr("%1：载荷类型异常").arg(path));
            continue;
        }
        auto column = well_column_from_document(*payload->document,
                                                loaded->well_name);
        if (!column.has_value()) {
            result.errors.append(
                QObject::tr("%1：无可用曲线（全部缺测或样本不足）").arg(path));
            continue;
        }
        result.wells.push_back(std::move(*column));
    }
    return result;
}

}  // namespace pwb::app
