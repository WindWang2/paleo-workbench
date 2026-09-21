#include "pwb/ui_widgets/core/qc_hub_core.hpp"

#include <algorithm>
#include <cmath>

namespace pwb::ui_widgets::core {

std::array<double, 4> padded_bbox(const std::vector<double>& bbox,
                                  double pad) {
    if (bbox.size() != 4) return {0.0, 0.0, 1.0, 1.0};
    const double xmin = bbox[0], ymin = bbox[1], xmax = bbox[2], ymax = bbox[3];
    const double dx =
        std::max((xmax - xmin) * (1.0 + pad), (xmax - xmin) + 2.0 * pad);
    const double dy =
        std::max((ymax - ymin) * (1.0 + pad), (ymax - ymin) + 2.0 * pad);
    const double cx = (xmin + xmax) / 2.0, cy = (ymin + ymax) / 2.0;
    return {cx - dx / 2.0, cy - dy / 2.0, cx + dx / 2.0, cy + dy / 2.0};
}

double ease_in_out(double t) {
    // PWB-V14-DATA-LINEAGE: local pi constant (M_PI is POSIX-only; the
    // _USE_MATH_DEFINES dance cannot fix an already-included <cmath>).
    constexpr double kPi = 3.14159265358979323846;
    return 0.5 - 0.5 * std::cos(kPi * std::max(0.0, std::min(1.0, t)));
}

const std::vector<QuickFixActionMeta>& quick_fix_registry() {
    static const std::vector<QuickFixActionMeta> registry = {
        {
            "sliver_merge",
            "吸附合并到相邻优势相",
            "把碎多边形并入共享边界最长的相邻相（并列取面积大者），"
            "几何取并集、属性取优势相；单一撤销命令。",
            {"sliver_polygon", "gap", "geometry_invalid"},
        },
        {
            "tangent_close",
            "沿切线自动延伸闭合",
            "未封闭边界两端沿末端切线方向延伸（步长=容差×0.5），"
            "端点进入吸附容差后闭合；超出容差×8 判不可修。",
            {"unclosed_boundary", "dangle"},
        },
    };
    return registry;
}

std::vector<QuickFixActionMeta> actions_for_rule(
    const std::string& rule, const std::vector<QuickFixActionMeta>& registry) {
    std::vector<QuickFixActionMeta> out;
    for (const QuickFixActionMeta& action : registry) {
        if (std::find(action.rules.begin(), action.rules.end(), rule) !=
            action.rules.end()) {
            out.push_back(action);
        }
    }
    return out;
}

}  // namespace pwb::ui_widgets::core
