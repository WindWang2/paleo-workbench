#include "pwb/ui_review/relink_summary.hpp"

namespace pwb::ui_review {

std::string relink_entry_status(const catalog::MissingSource& entry) {
    if (entry.relinkable) {
        return "可重链接";
    }
    if (entry.managed) {
        return "需重新导入";
    }
    return "不支持重链接";
}

std::string relink_scan_summary(int scanned, int entries, int relinkable) {
    if (entries == 0) {
        return "共扫描 " + std::to_string(scanned) + " 个版本，未发现缺失源";
    }
    return "共扫描 " + std::to_string(scanned) + " 个版本，缺失 " +
           std::to_string(entries) + " 个，其中可重链接（外部 RAW）" +
           std::to_string(relinkable) + " 个";
}

std::string relink_result_message(const RelinkBatchResult& result) {
    std::string message =
        "成功重链接 " + std::to_string(result.ok) + " 个";
    if (!result.reasons.empty()) {
        message += "，拒绝 " + std::to_string(result.reasons.size()) +
                   " 个（身份无法证明或发生错误）\n";
        const std::size_t shown =
            result.reasons.size() < 8 ? result.reasons.size() : 8;
        for (std::size_t i = 0; i < shown; ++i) {
            message += result.reasons[i];
            if (i + 1 < shown) {
                message += "\n";
            }
        }
        if (result.reasons.size() > 8) {
            message += "\n… 共 " + std::to_string(result.reasons.size()) +
                       " 条";
        }
    }
    return message;
}

}  // namespace pwb::ui_review
