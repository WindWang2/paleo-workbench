#include <pwb/ui_composite/roles.hpp>

#include <algorithm>
#include <cctype>
#include <map>
#include <stdexcept>

namespace pwb::ui_composite {
namespace {

std::string normalize(const std::string& value) {
    std::string text;
    text.reserve(value.size());
    for (char c : value) {
        text.push_back(static_cast<char>(std::tolower(
            static_cast<unsigned char>(c))));
    }
    const auto first = text.find_first_not_of(" \t\n\r");
    const auto last = text.find_last_not_of(" \t\n\r");
    if (first == std::string::npos) {
        return {};
    }
    return text.substr(first, last - first + 1);
}

const std::map<std::string, std::string>& role_labels() {
    static const std::map<std::string, std::string> labels = {
        {std::string(layer_role::kBaseReference), "基础与参考"},
        {std::string(layer_role::kInitialFaciesSource),
         "初始沉积相（原始）"},
        {std::string(layer_role::kInitialFaciesDraft),
         "沉积相解释（草稿）"},
        {std::string(layer_role::kWellFaciesPrediction), "测井预测相"},
        {std::string(layer_role::kWellFaciesConfidence), "测井预测置信度"},
        {std::string(layer_role::kSeismicFaciesPrediction), "地震预测相"},
        {std::string(layer_role::kSeismicFaciesConfidence),
         "地震预测置信度"},
        {std::string(layer_role::kInterpretationAnnotation), "解释注记"},
        {std::string(layer_role::kPendingReviewArea), "待确认区域"},
        {std::string(layer_role::kProvenanceDirection), "物源方向"},
        {std::string(layer_role::kProvenanceLine), "物源线"},
        {std::string(layer_role::kDistributionLine), "沉积体系展布线"},
        {std::string(layer_role::kPaleoShoreline), "古岸线"},
        {std::string(layer_role::kFaciesBoundary), "相带边界"},
        {std::string(layer_role::kFaultConstraint), "断层约束"},
        {std::string(layer_role::kInterpolationBoundary), "插值限制边界"},
        {std::string(layer_role::kMaskBoundary), "掩膜/排除区"},
        {std::string(layer_role::kFactorInput), "单因素输入井点"},
        {std::string(layer_role::kFactorGrid), "单因素插值栅格"},
        {std::string(layer_role::kFactorContour), "单因素等值线"},
        {std::string(layer_role::kFactorClassification), "单因素分级区"},
        {std::string(layer_role::kFactorUncertainty), "单因素不确定性"},
        {std::string(layer_role::kFactorQc), "单因素 QC"},
        {std::string(layer_role::kAnalysisAid), "分析辅助"},
        {std::string(layer_role::kIntegratedFacies), "综合沉积相"},
        {std::string(layer_role::kIntegratedBoundary), "综合相带边界"},
        {std::string(layer_role::kMapAnnotation), "地图注记"},
        {std::string(layer_role::kMapSymbol), "地图符号"},
        {std::string(layer_role::kMapReference), "编图参考"},
        {std::string(layer_role::kQcWarning), "QC 提醒"},
        {std::string(layer_role::kQcConflict), "QC 冲突"},
        {std::string(layer_role::kUserGeneral), "用户图层"},
        {std::string(layer_role::kLegacyUnclassified), "未分类（旧工程）"},
    };
    return labels;
}

const std::map<std::string, std::string>& kind_labels() {
    static const std::map<std::string, std::string> labels = {
        {std::string(constraint_kind::kSourceDirection), "物源方向"},
        {std::string(constraint_kind::kProvenanceLine), "物源线"},
        {std::string(constraint_kind::kDistributionLine), "沉积体系展布线"},
        {std::string(constraint_kind::kPaleoShoreline), "古岸线"},
        {std::string(constraint_kind::kFaciesBoundary), "相带控制线"},
        {std::string(constraint_kind::kFault), "断层"},
        {std::string(constraint_kind::kInterpolationBoundary),
         "插值限制边界"},
        {std::string(constraint_kind::kMask), "掩膜"},
        {std::string(constraint_kind::kExclusionArea), "排除区"},
        {std::string(constraint_kind::kTrendLine), "趋势线"},
    };
    return labels;
}

}  // namespace

std::string role_label(const std::string& role_value) {
    const auto& labels = role_labels();
    auto it = labels.find(role_value);
    return it == labels.end() ? role_value : it->second;
}

std::string constraint_kind_label(const std::string& kind_value) {
    const auto& labels = kind_labels();
    auto it = labels.find(kind_value);
    if (it == labels.end()) {
        throw std::out_of_range("unknown ConstraintKind " + kind_value);
    }
    return it->second;
}

const std::set<std::string>& role_editable_set() {
    static const std::set<std::string> set = {
        std::string(layer_role::kInitialFaciesDraft),
        std::string(layer_role::kProvenanceDirection),
        std::string(layer_role::kProvenanceLine),
        std::string(layer_role::kDistributionLine),
        std::string(layer_role::kPaleoShoreline),
        std::string(layer_role::kFaciesBoundary),
        std::string(layer_role::kFaultConstraint),
        std::string(layer_role::kInterpolationBoundary),
        std::string(layer_role::kMaskBoundary),
        std::string(layer_role::kIntegratedFacies),
        std::string(layer_role::kIntegratedBoundary),
        std::string(layer_role::kInterpretationAnnotation),
        std::string(layer_role::kUserGeneral),
    };
    return set;
}

const std::set<std::string>& role_raw_protected_set() {
    static const std::set<std::string> set = {
        std::string(layer_role::kInitialFaciesSource),
        std::string(layer_role::kWellFaciesPrediction),
        std::string(layer_role::kWellFaciesConfidence),
        std::string(layer_role::kSeismicFaciesPrediction),
        std::string(layer_role::kSeismicFaciesConfidence),
        std::string(layer_role::kFactorGrid),
        std::string(layer_role::kFactorClassification),
    };
    return set;
}

const std::set<std::string>& facies_family_roles() {
    static const std::set<std::string> set = {
        std::string(layer_role::kInitialFaciesSource),
        std::string(layer_role::kInitialFaciesDraft),
        std::string(layer_role::kWellFaciesPrediction),
        std::string(layer_role::kSeismicFaciesPrediction),
        std::string(layer_role::kIntegratedFacies),
    };
    return set;
}

bool role_is_editable(const std::string& role_value) {
    return role_editable_set().count(role_value) != 0;
}

bool role_is_raw_protected(const std::string& role_value) {
    return role_raw_protected_set().count(role_value) != 0;
}

bool role_is_prediction(const std::string& role_value) {
    static const std::set<std::string> set = {
        std::string(layer_role::kWellFaciesPrediction),
        std::string(layer_role::kWellFaciesConfidence),
        std::string(layer_role::kSeismicFaciesPrediction),
        std::string(layer_role::kSeismicFaciesConfidence),
    };
    return set.count(role_value) != 0;
}

bool is_facies_family_role(const std::string& role_value) {
    auto parsed = layer_role_from_value(role_value);
    return parsed.has_value() && facies_family_roles().count(*parsed) != 0;
}

const std::vector<std::string>& all_layer_roles() {
    static const std::vector<std::string> roles = [] {
        std::vector<std::string> out;
        out.reserve(role_labels().size());
        for (const auto& [value, label] : role_labels()) {
            (void)label;
            out.push_back(value);
        }
        return out;
    }();
    return roles;
}

std::optional<std::string> layer_role_from_value(const std::string& value) {
    const std::string text = normalize(value);
    if (text.empty()) {
        return std::nullopt;
    }
    if (role_labels().count(text)) {
        return text;
    }
    return std::nullopt;
}

std::optional<std::string> constraint_kind_from_value(
    const std::string& value) {
    const std::string text = normalize(value);
    if (text.empty()) {
        return std::nullopt;
    }
    if (kind_labels().count(text)) {
        return text;
    }
    return std::nullopt;
}

std::string constraint_kind_geometry_kind(const std::string& kind_value) {
    if (kind_value == constraint_kind::kMask ||
        kind_value == constraint_kind::kExclusionArea) {
        return "polygon";
    }
    return "line";
}

std::optional<std::string> constraint_kind_layer_role(
    const std::string& kind_value) {
    static const std::map<std::string, std::string> map = {
        {std::string(constraint_kind::kSourceDirection),
         std::string(layer_role::kProvenanceDirection)},
        {std::string(constraint_kind::kProvenanceLine),
         std::string(layer_role::kProvenanceLine)},
        {std::string(constraint_kind::kDistributionLine),
         std::string(layer_role::kDistributionLine)},
        {std::string(constraint_kind::kPaleoShoreline),
         std::string(layer_role::kPaleoShoreline)},
        {std::string(constraint_kind::kFaciesBoundary),
         std::string(layer_role::kFaciesBoundary)},
        {std::string(constraint_kind::kFault),
         std::string(layer_role::kFaultConstraint)},
        {std::string(constraint_kind::kInterpolationBoundary),
         std::string(layer_role::kInterpolationBoundary)},
        {std::string(constraint_kind::kMask),
         std::string(layer_role::kMaskBoundary)},
        {std::string(constraint_kind::kExclusionArea),
         std::string(layer_role::kMaskBoundary)},
        {std::string(constraint_kind::kTrendLine),
         std::string(layer_role::kDistributionLine)},
    };
    auto it = map.find(kind_value);
    if (it == map.end()) {
        return std::nullopt;
    }
    return it->second;
}

std::optional<std::string> constraint_interpolation_role(
    const std::string& kind_value) {
    static const std::map<std::string, std::string> map = {
        {std::string(constraint_kind::kSourceDirection), "direction"},
        {std::string(constraint_kind::kTrendLine), "direction"},
        {std::string(constraint_kind::kProvenanceLine), "direction"},
        {std::string(constraint_kind::kDistributionLine), "direction"},
        {std::string(constraint_kind::kPaleoShoreline), "boundary"},
        {std::string(constraint_kind::kFaciesBoundary), "boundary"},
        {std::string(constraint_kind::kFault), "break"},
        {std::string(constraint_kind::kInterpolationBoundary), "boundary"},
        {std::string(constraint_kind::kMask), "boundary"},
        {std::string(constraint_kind::kExclusionArea), "boundary"},
    };
    auto it = map.find(kind_value);
    if (it == map.end()) {
        return std::nullopt;
    }
    return it->second;
}

}  // namespace pwb::ui_composite
