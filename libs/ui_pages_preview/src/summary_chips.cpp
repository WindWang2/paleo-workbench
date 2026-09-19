#include <pwb/ui_pages_preview/summary_chips.hpp>

#include <cctype>
#include <cstdlib>

namespace pwb::ui_pages_preview {

namespace {

std::string trim_copy(const std::string& value) {
    const std::size_t first = value.find_first_not_of(" \t\n\r\f\v");
    if (first == std::string::npos) return "";
    const std::size_t last = value.find_last_not_of(" \t\n\r\f\v");
    return value.substr(first, last - first + 1);
}

}  // namespace

std::string thousands_grouped(long long value) {
    std::string digits = std::to_string(std::llabs(value));
    std::string out;
    int count = 0;
    for (auto it = digits.rbegin(); it != digits.rend(); ++it) {
        if (count && count % 3 == 0) out = "," + out;
        out = *it + out;
        ++count;
    }
    if (value < 0) out = "-" + out;
    return out;
}

SummaryChipValues summary_chip_values(
    const std::vector<std::pair<std::string, std::string>>& summary_rows) {
    SummaryChipValues chips;
    for (const auto& [k, v] : summary_rows) {
        const std::string key = trim_copy(k);
        const std::string val = trim_copy(v);
        if (key == "井名") {
            chips.well = val;
        } else if (key == "曲线数") {
            chips.curves = val + " 条";
        } else if (key == "采样点") {
            // Python int(v) parity: tolerates +/- and digit underscores.
            // Python int(v) parity: tolerates +/- and digit underscores.
            std::string cleaned;
            cleaned.reserve(val.size());
            for (std::size_t i = 0; i < val.size(); ++i) {
                if (val[i] == '_' && i > 0 && i + 1 < val.size() &&
                    std::isdigit(static_cast<unsigned char>(val[i - 1])) &&
                    std::isdigit(static_cast<unsigned char>(val[i + 1]))) {
                    continue;
                }
                cleaned += val[i];
            }
            char* end = nullptr;
            const long long parsed = std::strtoll(cleaned.c_str(), &end, 10);
            const bool is_int = end != cleaned.c_str() && *end == '\0';
            chips.samples = (is_int ? thousands_grouped(parsed) : val) + " 点";
        }
    }
    return chips;
}

}  // namespace pwb::ui_pages_preview
