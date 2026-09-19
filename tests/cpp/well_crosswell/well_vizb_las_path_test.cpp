// 05 线 — viz_b 连井 dock 的真实 LAS 数据通路测试（转换器 + 部分
// 成功/失败聚合；dock 层生命周期见 well.dock_lifecycle）。

#include <cmath>
#include <cstdio>
#include <string>

#include "viz_b_well_source.hpp"

#include <pwb/ui_workers/wle_load.hpp>

#ifndef PWB_WELL_FIXTURE_DIR
#define PWB_WELL_FIXTURE_DIR "."
#endif

namespace {

int failures = 0;

#define CHECK(cond)                                                  \
    do {                                                             \
        if (!(cond)) {                                               \
            std::fprintf(stderr, "CHECK 失败 %s:%d: %s\n", __FILE__, \
                         __LINE__, #cond);                           \
            ++failures;                                              \
        }                                                            \
    } while (false)

}  // namespace

int main() {
    using pwb::viz::cross_well::WellColumnData;
    const auto load_fn = pwb::ui_workers::make_wle_load_fn();
    const std::string dir = PWB_WELL_FIXTURE_DIR;

    // 两个真 LAS + 一个坏文件：部分成功可见，逐文件错误聚合。
    const QStringList paths = {
        QString::fromStdString(dir + "/las/well_a_metric.las"),
        QString::fromStdString(dir + "/las/well_b_ft_reverse.las"),
        QString::fromStdString(dir + "/las/well_c_bad.las"),
    };
    const auto result = pwb::app::load_wells_from_las(paths, load_fn);
    CHECK(result.wells.size() == 2);
    CHECK(result.errors.size() == 1);
    CHECK(result.errors.front().contains("well_c_bad.las"));

    // 井 A：GR+DT 真曲线，缺测对（-999.25）成对剔除。
    const WellColumnData* well_a = nullptr;
    const WellColumnData* well_b = nullptr;
    for (const auto& well : result.wells) {
        if (well.name == "Well A") well_a = &well;
        if (well.name == "Well B") well_b = &well;
    }
    CHECK(well_a != nullptr);
    CHECK(well_a->curves.size() == 2);
    for (const auto& curve : well_a->curves) {
        CHECK(curve.depths.size() == curve.values.size());
        for (double v : curve.values) {
            // 剔除后不允许哨兵/NaN 残留（连井核契约）。
            CHECK(v != -999.25);
            CHECK(std::isfinite(v));
        }
    }
    bool gr_found = false;
    for (const auto& curve : well_a->curves) {
        if (curve.name == "GR") {
            gr_found = true;
            CHECK(curve.depths.size() == 8);  // 9 行 - 1 缺测对
        }
    }
    CHECK(gr_found);

    // 井 B：反向深度（降序）、单曲线（缺 DT）。
    CHECK(well_b != nullptr);
    CHECK(well_b->curves.size() == 1);
    if (!well_b->curves.empty()) {
        const auto& gr = well_b->curves.front();
        CHECK(gr.depths.size() == 9);
        CHECK(gr.depths.front() > gr.depths.back());  // 反向深度保持
    }

    // LAS 无井口坐标：诚实空数组（auto-arrange no-op 分支）。
    CHECK(result.coords.is_array());
    CHECK(result.coords.empty());

    // 全坏路径：零井 + 全部错误可见。
    const auto all_bad = pwb::app::load_wells_from_las(
        {QString::fromStdString(dir + "/las/well_c_bad.las")}, load_fn);
    CHECK(all_bad.wells.empty());
    CHECK(all_bad.errors.size() == 1);

    // 未接线的 seam（空 load_fn）：诚实错误，不崩溃。
    const auto no_engine = pwb::app::load_wells_from_las(paths, {});
    CHECK(no_engine.wells.empty());
    CHECK(!no_engine.errors.isEmpty());

    if (failures != 0) {
        std::fprintf(stderr, "well.vizb_las_path：%d 处失败\n", failures);
        return 1;
    }
    std::printf("well.vizb_las_path：全部通过\n");
    return 0;
}
