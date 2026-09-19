// 05 线 — 生产加载 seam（LAS + XML）真文件路径测试。
//
// 验收覆盖：LAS/XML 真文件、不同深度单位（m/ft）、缺曲线、反向深度、
// 取消（检查点抛 WellLogLoadCancelled）、坏文件诚实 nullopt；
// LAS 单位贯通到 WLE 轴，XML 深度单位诚实保持未声明。

#include <cstdio>
#include <cmath>
#include <string>

#include <pwb/ui_workers/wle_load.hpp>
#include <welllog/core/document.hpp>

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

std::string fixture(const char* name) {
    return std::string(PWB_WELL_FIXTURE_DIR) + "/" + name;
}

}  // namespace

int main() {
    using namespace pwb::ui_workers;
    const WellLogLoadFn load_fn = make_wle_load_fn();
    CHECK(static_cast<bool>(load_fn));
    const std::function<bool()> never = [] { return false; };

    // --- LAS：公制深度，GR+DT 两条曲线，~W 井名。 ---
    {
        auto loaded = load_fn(fixture("las/well_a_metric.las"), never);
        CHECK(loaded.has_value());
        const auto* payload =
            std::any_cast<WleDocumentPayload>(&loaded->data);
        CHECK(payload != nullptr && payload->document != nullptr);
        CHECK(loaded->well_name == "Well A");
        CHECK(payload->document->curves().size() == 2);
        CHECK(!payload->document->sampling_axes().empty());
        const auto& axis = payload->document->sampling_axes().front();
        // 深度单位贯通（~C DEPT.M → 轴单位含 m，大小写随文件头）。
        std::string unit_lower;
        for (char c : axis.unit) {
            unit_lower.push_back(
                c >= 'A' && c <= 'Z' ? static_cast<char>(c + 32) : c);
        }
        CHECK(unit_lower.find('m') != std::string::npos);
    }

    // --- LAS：英尺深度 + 反向深度（降序）；只有 GR（缺 DT 曲线）。 ---
    {
        auto loaded = load_fn(fixture("las/well_b_ft_reverse.las"), never);
        CHECK(loaded.has_value());
        const auto* payload =
            std::any_cast<WleDocumentPayload>(&loaded->data);
        CHECK(payload != nullptr && payload->document != nullptr);
        CHECK(loaded->well_name == "Well B");
        CHECK(payload->document->curves().size() == 1);  // 缺曲线诚实呈现
        const auto& axis = payload->document->sampling_axes().front();
        std::string unit_upper;
        for (char c : axis.unit) {
            unit_upper.push_back(
                c >= 'a' && c <= 'z' ? static_cast<char>(c - 32) : c);
        }
        CHECK(unit_upper.find("FT") != std::string::npos);
        const auto depth_first = axis.coordinates.value_as_double(0);
        const auto depth_last = axis.coordinates.value_as_double(
            axis.coordinates.length() - 1);
        CHECK(depth_first.has_value() && depth_last.has_value());
        CHECK(*depth_first > *depth_last);  // 反向深度方向声明与坐标一致
    }

    // --- 坏文件：诚实 nullopt（不抛、不伪造）。 ---
    {
        auto loaded = load_fn(fixture("las/well_c_bad.las"), never);
        CHECK(!loaded.has_value());
    }

    // --- 取消：解析前检查点抛 WellLogLoadCancelled。 ---
    {
        bool threw = false;
        try {
            (void)load_fn(fixture("las/well_a_metric.las"),
                          [] { return true; });
        } catch (const WellLogLoadCancelled&) {
            threw = true;
        }
        CHECK(threw);
    }

    // --- XML（WITSML 基础）：同一载荷类型，真曲线 + 井名。 ---
    {
        auto loaded = load_fn(fixture("xml/witsml_basic.xml"), never);
        CHECK(loaded.has_value());
        const auto* payload =
            std::any_cast<WleDocumentPayload>(&loaded->data);
        CHECK(payload != nullptr && payload->document != nullptr);
        CHECK(payload->diagnostics == 0);  // XML 路径无诊断（事实口径）
        CHECK(loaded->well_name == "W-1");
        CHECK(payload->document->curves().size() == 2);
        const auto& axis = payload->document->sampling_axes().front();
        CHECK(axis.unit.empty());  // XML 不声明深度单位 → 诚实未声明
    }

    // --- XML（反向深度）：轴方向按坐标声明。 ---
    {
        auto loaded = load_fn(fixture("xml/witsml_reverse.xml"), never);
        CHECK(loaded.has_value());
        const auto* payload =
            std::any_cast<WleDocumentPayload>(&loaded->data);
        CHECK(payload != nullptr && payload->document != nullptr);
        CHECK(!payload->document->sampling_axes().empty());
        CHECK(payload->document->sampling_axes().front().direction ==
              welllog::AxisDirection::decreasing);
    }

    // --- XML（缺测/缺曲线单元格）：NaN 值保留在真文档里。 ---
    {
        auto loaded = load_fn(fixture("xml/witsml_missing_cells.xml"), never);
        CHECK(loaded.has_value());
        const auto* payload =
            std::any_cast<WleDocumentPayload>(&loaded->data);
        CHECK(payload != nullptr && payload->document != nullptr);
        bool saw_nan = false;
        for (const auto& curve : payload->document->curves()) {
            for (std::uint64_t i = 0; i < curve.values.length(); ++i) {
                const auto v = curve.values.value_as_double(i);
                if (v.has_value() && std::isnan(*v)) saw_nan = true;
            }
        }
        CHECK(saw_nan);
    }

    // --- XML（SpreadsheetML 全家桶）：区间 + 标记实体进真文档。 ---
    {
        auto loaded = load_fn(fixture("xml/spreadsheet_welllog.xml"), never);
        CHECK(loaded.has_value());
        const auto* payload =
            std::any_cast<WleDocumentPayload>(&loaded->data);
        CHECK(payload != nullptr && payload->document != nullptr);
        CHECK(loaded->well_name == "W-SHEET");
        CHECK(payload->document->curves().size() == 2);
        CHECK(payload->document->intervals().size() == 4);  // 岩2+相1+地1
        CHECK(payload->document->markers().size() == 1);    // 标准层
    }

    // --- 非井 XML：诚实 nullopt（识别拒绝，绝不硬解析）。 ---
    {
        CHECK(!load_fn(fixture("xml/negative_generic_points.xml"), never)
                   .has_value());
        CHECK(!load_fn(fixture("xml/negative_incomplete_witsml.xml"), never)
                   .has_value());
    }

    // --- 非 LAS/XML 资源：诚实 nullopt（05 前语义保持）。 ---
    {
        CHECK(!load_fn(fixture("tie/checkshot.csv"), never).has_value());
    }

    if (failures != 0) {
        std::fprintf(stderr, "well.load_path：%d 处失败\n", failures);
        return 1;
    }
    std::printf("well.load_path：全部通过\n");
    return 0;
}
