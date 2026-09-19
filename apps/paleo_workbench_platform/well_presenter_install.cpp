// 05 线 — well/time-depth presenter 安装器实现（见头注释）。

#include "well_presenter_install.hpp"

#include "viz_e_install.hpp"

#include <QString>

#include <pwb/ui_pages_preview/qt/time_depth_preview_presenter.hpp>
#include <pwb/ui_pages_preview/qt/well_log_preview_presenter.hpp>
#include <pwb/ui_workers/viz_resolve.hpp>
#if defined(PWB_WELL_PRESENTERS_HAVE_TIE)
#include <pwb/viz/cross_well/seismic_tie.hpp>
#endif
#if defined(PWB_WELL_PRESENTERS_HAVE_WLE)
#include <pwb/ui_workers/wle_load.hpp>
#include <welllog/core/document.hpp>
#endif

#include <algorithm>
#include <any>
#include <functional>
#include <limits>
#include <optional>
#include <string>
#include <vector>

namespace pwb::app::well_presenters {

namespace {

using pwb::ui_pages_preview::qt::TimeDepthPreviewData;
using pwb::ui_pages_preview::qt::TimeDepthPreviewPage;
using pwb::ui_pages_preview::qt::WellLogPreviewCurve;
using pwb::ui_pages_preview::qt::WellLogPreviewData;
using pwb::ui_pages_preview::qt::WellLogPreviewPage;

#if defined(PWB_WELL_PRESENTERS_HAVE_WLE)
// 生产载荷（WLE 文档）→ 中性页面 DTO。深度取首轴（LAS/文档单井单深度
// 轴惯例，viz_a_install::to_document_input 同口径）；曲线逐条与自己的轴
// 配对，缺测值保留 NaN（页面画断口，诚实）。
WellLogPreviewData page_data_from_document(
    const welllog::WellLogDocument& document, const std::string& well_name,
    const std::string& source) {
    WellLogPreviewData data;
    data.well_name = well_name;
    data.source = source;
    const auto& axes = document.sampling_axes();
    if (!axes.empty()) {
        const auto& axis = axes.front();
        data.depth_unit = axis.unit;
        for (std::uint64_t i = 0; i < axis.coordinates.length(); ++i) {
            const auto value = axis.coordinates.value_as_double(i);
            if (!value.has_value()) continue;
            if (data.sample_count == 0) {
                data.top_depth = *value;
                data.bottom_depth = *value;
            } else {
                data.top_depth = std::min(data.top_depth, *value);
                data.bottom_depth = std::max(data.bottom_depth, *value);
            }
            ++data.sample_count;
        }
    }
    for (const welllog::Curve& curve : document.curves()) {
        const welllog::SamplingAxis* axis = nullptr;
        for (const welllog::SamplingAxis& candidate : axes) {
            if (candidate.id == curve.sampling_axis_id) {
                axis = &candidate;
                break;
            }
        }
        if (axis == nullptr) continue;
        auto depth = std::make_shared<std::vector<double>>();
        depth->reserve(static_cast<std::size_t>(axis->coordinates.length()));
        for (std::uint64_t i = 0; i < axis->coordinates.length(); ++i) {
            const auto value = axis->coordinates.value_as_double(i);
            depth->push_back(
                value.has_value()
                    ? *value
                    : std::numeric_limits<double>::quiet_NaN());
        }
        auto values = std::make_shared<std::vector<double>>();
        values->reserve(static_cast<std::size_t>(curve.values.length()));
        for (std::uint64_t i = 0; i < curve.values.length(); ++i) {
            const auto value = curve.values.value_as_double(i);
            values->push_back(
                value.has_value()
                    ? *value
                    : std::numeric_limits<double>::quiet_NaN());
        }
        WellLogPreviewCurve out;
        out.name = curve.mnemonic;
        out.unit = curve.unit;
        out.depth = std::move(depth);
        out.values = std::move(values);
        data.curves.push_back(std::move(out));
    }
    return data;
}
#endif  // PWB_WELL_PRESENTERS_HAVE_WLE

QWidget* make_well_log_page(const QString& asset_path) {
    const std::string path = asset_path.toStdString();
#if defined(PWB_WELL_PRESENTERS_HAVE_WLE)
    auto load_fn = pwb::ui_workers::make_wle_load_fn();
    const std::function<bool()> never_cancelled = [] { return false; };
    std::optional<pwb::ui_workers::LoadedWellLog> loaded;
    try {
        loaded = load_fn(path, never_cancelled);
    } catch (const pwb::ui_workers::WellLogLoadCancelled&) {
        loaded = std::nullopt;
    } catch (const std::exception&) {
        loaded = std::nullopt;
    }
    if (!loaded || !loaded->data.has_value()) {
        WellLogPreviewData data;
        data.diagnostic = "无法解析为井数据（LAS/XML 井曲线识别或解析失败）";
        data.source = path;
        return new WellLogPreviewPage(std::move(data));
    }
    const auto* payload =
        std::any_cast<pwb::ui_workers::WleDocumentPayload>(&loaded->data);
    if (payload == nullptr || payload->document == nullptr) {
        WellLogPreviewData data;
        data.diagnostic = "井数据载荷类型异常";
        data.source = path;
        return new WellLogPreviewPage(std::move(data));
    }
    return new WellLogPreviewPage(page_data_from_document(
        *payload->document, loaded->well_name, path));
#else
    // WLE 桥不在本构建：诚实诊断页（不伪造曲线）。
    WellLogPreviewData data;
    data.diagnostic = "LAS/XML 解析内核未接入本构建（WLE 桥缺失）";
    data.source = path;
    return new WellLogPreviewPage(std::move(data));
#endif
}

QWidget* make_time_depth_page(const QString& asset_path) {
#if defined(PWB_WELL_PRESENTERS_HAVE_TIE)
    pwb::viz::cross_well::SeismicTie tie;
    if (!tie.load_csv(asset_path.toStdString())) {
        TimeDepthPreviewData data;
        data.diagnostic = "无法读取时深校准表（CSV）";
        data.source = asset_path.toStdString();
        return new TimeDepthPreviewPage(std::move(data));
    }
    const std::vector<std::string> wells = tie.well_names();
    // 单井表直显；多井表显示首井并注明（其余经 dock 的标定页消费）。
    const std::string well =
        wells.empty() ? std::string() : wells.front();
    const auto* table = tie.table_for_well(well);
    TimeDepthPreviewData data;
    data.source = asset_path.toStdString();
    data.well_name = well;
    if (wells.size() > 1) {
        data.diagnostic = "";
        data.source += "（共 " + std::to_string(wells.size()) +
                       " 口井，显示首井 " + well + "）";
    }
    if (table == nullptr || table->depths_m.size() < 2) {
        data.diagnostic = "时深对不足（至少 2 对）";
        return new TimeDepthPreviewPage(std::move(data));
    }
    for (std::size_t i = 0; i < table->depths_m.size(); ++i) {
        data.pairs.emplace_back(table->depths_m[i], table->twt_ms[i]);
    }
    auto* page = new TimeDepthPreviewPage(std::move(data));
    // 探针绑定标定核（CheckshotTable → WellTieCalibration 插值）。
    page->set_probe([table](double md) { return table->interpolate_twt(md); });
    return page;
#else
    // viz-B 核不在本构建：诚实诊断页（不伪造校准数据）。
    (void)asset_path;
    TimeDepthPreviewData data;
    data.diagnostic = "时深标定核未接入本构建（viz-B 桥缺失）";
    return new TimeDepthPreviewPage(std::move(data));
#endif
}

}  // namespace

bool install() {
    bool ok = true;
    {
        pwb::viz_e::ExternalPresenter presenter;
        presenter.kind = "well_log";
        presenter.note =
            "05 线 well-log presenter（LAS/XML 生产 seam"
#if defined(PWB_WELL_PRESENTERS_HAVE_WLE)
            "：WLE 已接入）"
#else
            "：WLE 桥缺失，诚实诊断）"
#endif
            ;
        presenter.supports = [](const QString& path) {
            const std::string lower = path.toLower().toStdString();
            return lower.size() > 4 &&
                   (lower.rfind(".las") == lower.size() - 4 ||
                    lower.rfind(".xml") == lower.size() - 4);
        };
        presenter.create = [](const QString& path, QWidget* parent) {
            QWidget* page = make_well_log_page(path);
            page->setParent(parent);
            return page;
        };
        if (!pwb::viz_e::register_external_presenter(std::move(presenter))) {
            ok = false;
        }
    }
    {
        pwb::viz_e::ExternalPresenter presenter;
        presenter.kind = "time_depth";
        presenter.note = "05 线 time-depth presenter（SeismicTie CSV + 标定核探针）";
        presenter.supports = [](const QString& path) {
            return path.endsWith(QLatin1String(".csv"),
                                 Qt::CaseInsensitive);
        };
        presenter.create = [](const QString& path, QWidget* parent) {
            QWidget* page = make_time_depth_page(path);
            page->setParent(parent);
            return page;
        };
        if (!pwb::viz_e::register_external_presenter(std::move(presenter))) {
            ok = false;
        }
    }
    return ok;}

}  // namespace pwb::app::well_presenters
