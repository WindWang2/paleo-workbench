// UI-06 — module relationship model (module_relationship.py).
#include <pwb/ui_pages_data/module_map.hpp>
#include <pwb/ui_pages_data/vocab.hpp>

namespace pwb::ui_pages_data {

std::string_view step_tone(const std::string& status) {
    // _STATUS_TONES.get(status, "neutral").
    if (status == "complete") return "success";
    if (status == "running") return "primary";
    if (status == "pending") return "neutral";
    if (status == "warning") return "warning";
    if (status == "failed") return "error";
    return "neutral";
}

std::string_view module_status_text(const std::string& status) {
    // STATUS_TEXT.get(status, "待开始") — the default here is the literal,
    // not the status passthrough status_text() uses.
    static constexpr std::pair<std::string_view, std::string_view> kMap[] = {
        {"complete", "已完成"}, {"stale", "需更新"},   {"running", "处理中"},
        {"pending", "待开始"},  {"warning", "警告"},   {"failed", "异常"},
        {"ready", "就绪"},      {"skipped", "已跳过"}, {"mock", "Mock"},
    };
    for (const auto& [k, v] : kMap)
        if (k == status) return v;
    return "待开始";
}

std::map<std::string, ModuleCardState>
step_card_states(const std::vector<StepLike>& steps) {
    // step_map = {step.step_type: step.status} — last assignment wins.
    std::map<std::string, std::string> step_map;
    for (const auto& step : steps) step_map[step.step_type] = step.status;

    auto get = [&](const char* type) {
        const auto it = step_map.find(type);
        return it != step_map.end() ? it->second : std::string("pending");
    };
    auto state = [](const std::string& status) {
        return ModuleCardState{status, std::string(module_status_text(status)),
                               std::string(step_tone(status))};
    };
    const std::string prediction = get("prediction");
    return {
        {"data", state(get("data_check"))},
        {"sequence", state(get("factor_map"))},
        {"well", state(prediction)},
        {"seismic", state(prediction)},
        {"facies", state(get("map_compile"))},
        {"mapping", state(get("qc"))},
    };
}

std::string first_incomplete_contract(const std::vector<StepLike>& steps) {
    // home_page.update_state's step_to_contract map.
    static const std::pair<const char*, const char*> kMap[] = {
        {"data_check", "data_import"},
        {"factor_map", "factor_interpolation"},
        {"prediction", "facies_prediction"},
        {"map_compile", "paleomap_compile"},
        {"qc", "quality_control"},
        {"export", "export"},
    };
    for (const auto& step : steps) {
        for (const auto& [type, contract] : kMap) {
            if (step.step_type != type) continue;
            if (step.status == "pending" || step.status == "stale" ||
                step.status == "running" || step.status == "warning") {
                return contract;
            }
            break;  // mapped but not incomplete → keep scanning
        }
    }
    return "";
}

const std::vector<ModuleCardSpec>& module_card_specs() {
    // Construction order mirrors ModuleRelationshipCanvas.__init__.
    static const std::vector<ModuleCardSpec> kSpecs = {
        {
            .key = "sequence",
            .title = "地层格架构建",
            .items =
                {
                    "· 单井层序划分",
                    "· 井震标定",
                    "· 井震地层层序划分及岩性共拉分特征",
                    "· 资料地质编图",
                },
            .inputs = {},
            .outputs = {"地层格架方案控制单井/地震分析 and 编图的最小单元"},
            .accented = false,
            .page_index = 4,
            .sub_items = {},
            .min_width = 500,
            .grid_row = 0,
            .grid_col = 1,
            .grid_row_span = 1,
            .grid_col_span = 2,
            .align_center = true,
        },
        {
            .key = "well",
            .title = "单井相智能分析",
            .items =
                {
                    "1. 单井的岩性结果标记地震属性",
                    "2. 单井的结果校验地层结果",
                },
            .inputs =
                {
                    "地层格架",
                    "地震属性",
                    "测井曲线",
                    "岩心/岩性数据",
                    "其它辅助资料",
                },
            .outputs = {"单井相结果", "相带/相序划分"},
            .accented = false,
            .page_index = 2,
            .min_width = 220,
            .grid_row = 1,
            .grid_col = 0,
        },
        {
            .key = "seismic",
            .title = "地震相智能分析",
            .items =
                {
                    "1. 地震属性辅助无井区地砂岩性判别",
                    "2. 判断相变边界",
                },
            .inputs = {"地层格架", "地震体", "地震属性", "井点/相标定"},
            .outputs = {"地震相结果", "相变边界"},
            .accented = false,
            .page_index = 3,
            .min_width = 220,
            .grid_row = 1,
            .grid_col = 1,
        },
        {
            .key = "facies",
            .title = "岩相与沉积相分析",
            .items =
                {
                    "1. 输出解释版本管理",
                    "2. 输出编制图版成果",
                },
            .inputs = {"地震相结果", "单井相结果", "地层格架"},
            .outputs = {"相类型", "沉积相", "解释成果"},
            .accented = false,
            .page_index = 5,
            .min_width = 220,
            .grid_row = 1,
            .grid_col = 2,
        },
        {
            .key = "mapping",
            .title = "古地理图编制",
            .items =
                {
                    "· 古地理图编制",
                    "· 图件输出",
                    "· 成果发布",
                },
            .inputs = {},
            .outputs = {},
            .accented = true,
            .page_index = 8,
            .min_width = 220,
            .grid_row = 1,
            .grid_col = 3,
        },
        {
            .key = "data",
            .title = "多源数据管理",
            .items = {},
            .inputs = {},
            .outputs = {},
            .accented = false,
            .page_index = -1,
            .sub_items =
                {
                    {"数据标准化", "data.svg", 1},
                    {"质检管理", "rb-qc.svg", 9},
                    {"版本控制", "refresh-cw.svg", 1},
                },
            .min_width = 800,
            .grid_row = 2,
            .grid_col = 0,
            .grid_row_span = 1,
            .grid_col_span = 3,
            .align_center = true,
        },
    };
    return kSpecs;
}

}  // namespace pwb::ui_pages_data
