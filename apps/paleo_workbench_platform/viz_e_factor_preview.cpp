#include "viz_e_factor_preview.hpp"

#include <pwb/viz_charts/axes.hpp>
#include <pwb/viz_charts/marching_squares.hpp>

#include <pwb/job_runtime/job_contract.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <sstream>

namespace pwb::viz_e {

std::vector<double> preview_levels(double vmin, double vmax, int count) {
    std::vector<double> levels;
    if (!(std::isfinite(vmin) && std::isfinite(vmax)) || vmax <= vmin ||
        count < 2) {
        return levels;
    }
    levels.reserve(static_cast<std::size_t>(count));
    for (int i = 0; i < count; ++i) {
        levels.push_back(vmin + (vmax - vmin) * i / (count - 1));
    }
    return levels;
}

FactorPreviewOutcome compute_factor_preview(const FactorPreviewRequest& request,
                                            pwb::job::JobContext& ctx) {
    FactorPreviewOutcome outcome;
    outcome.generation = 0;
    if (request.samples.empty()) {
        outcome.error = QStringLiteral("没有可用于插值的样本点");
        return outcome;
    }
    ctx.report_progress(0.1, 1.0, QStringLiteral("插值计算").toStdString());

    pwb::mapping::InterpolateOptions options;
    options.method = request.method;
    options.grid_n = request.grid_n;
    options.crs = request.crs;  // empty → undeclared; never guessed
    try {
        const pwb::mapping::FactorGrid grid =
            pwb::mapping::interpolate_factor(request.samples, options);
        ctx.check_cancelled();
        ctx.report_progress(0.6, 1.0, QStringLiteral("生成等值线").toStdString());

        // Finite-value range (NaN = nodata cells excluded).
        double vmin = std::numeric_limits<double>::infinity();
        double vmax = -std::numeric_limits<double>::infinity();
        for (const float v : grid.grid_z) {
            if (std::isfinite(static_cast<double>(v))) {
                vmin = std::min(vmin, static_cast<double>(v));
                vmax = std::max(vmax, static_cast<double>(v));
            }
        }
        if (!std::isfinite(vmin)) {
            outcome.error = QStringLiteral("插值结果没有有效格点值");
            return outcome;
        }

        const std::vector<double> levels = preview_levels(vmin, vmax);
        auto lines = pwb::viz_charts::extract_contour_lines(
            grid.grid_x, grid.grid_y,
            std::vector<double>(grid.grid_z.begin(), grid.grid_z.end()),
            levels);
        ctx.check_cancelled();
        ctx.report_progress(0.9, 1.0, QStringLiteral("组装呈现").toStdString());

        SurfaceHost::SurfaceData data;
        data.grid_x = grid.grid_x;
        data.grid_y = grid.grid_y;
        data.grid_z = grid.grid_z;
        data.levels = levels;
        data.title =
            QString::fromStdString(request.factor_name + " — 曲面预览");

        std::ostringstream provenance;
        provenance << "因子: " << request.factor_name << "\n"
                   << "方法: " << grid.method << " (mapping_kernel C++)\n"
                   << "单位: "
                   << (request.unit.empty() ? "未声明" : request.unit) << "\n"
                   << "CRS: "
                   << (request.crs.empty() ? "未声明" : request.crs) << "\n"
                   << "网格: " << grid.grid_x.size() << " × "
                   << grid.grid_y.size() << "\n"
                   << "样本: " << request.samples.size() << "\n"
                   << "范围: " << vmin << " ~ " << vmax << "\n"
                   << "来源: " << request.asset_path;
        data.provenance = QString::fromStdString(provenance.str());

        outcome.ok = true;
        outcome.data = std::move(data);
        outcome.statistics = grid.statistics;
        if (lines.has_value()) {
            outcome.contour_lines = std::move(*lines);
        }
        return outcome;
    } catch (const pwb::job::JobCancelled&) {
        throw;  // cancellation propagates to the runtime's cancel path
    } catch (const std::exception& error) {
        outcome.error =
            QStringLiteral("插值失败: %1").arg(QString::fromUtf8(error.what()));
        return outcome;
    }
}

SurfaceHost::SurfaceData surface_data_from_factor_task(
    const std::vector<double>& grid_x, const std::vector<double>& grid_y,
    const std::vector<double>& grid_z, const std::string& factor_name,
    const std::string& method, const std::string& crs,
    const std::string& unit, const std::string& source_identity) {
    SurfaceHost::SurfaceData data;
    data.grid_x = grid_x;
    data.grid_y = grid_y;
    // Worker grids are row-major (ny × nx) with NaN nodata — the surface
    // widget consumes the same layout.
    data.grid_z.assign(grid_z.begin(), grid_z.end());
    double vmin = std::numeric_limits<double>::infinity();
    double vmax = -std::numeric_limits<double>::infinity();
    for (const double v : grid_z) {
        if (std::isfinite(v)) {
            vmin = std::min(vmin, v);
            vmax = std::max(vmax, v);
        }
    }
    data.levels = preview_levels(vmin, vmax);
    data.title = QString::fromStdString(factor_name + " — 因子任务曲面");
    std::ostringstream provenance;
    provenance << "因子: " << factor_name << "\n"
               << "方法: " << (method.empty() ? "未声明" : method) << "\n"
               << "单位: " << (unit.empty() ? "未声明" : unit) << "\n"
               << "CRS: " << (crs.empty() ? "未声明" : crs) << "\n"
               << "网格: " << grid_x.size() << " × " << grid_y.size() << "\n"
               << "来源: " << source_identity;
    data.provenance = QString::fromStdString(provenance.str());
    return data;
}

}  // namespace pwb::viz_e
