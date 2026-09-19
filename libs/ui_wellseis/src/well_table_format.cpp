#include <pwb/ui_wellseis/well_table_format.hpp>

#include <cmath>
#include <cstdio>
#include <unordered_map>

namespace pwb::ui_wellseis {

const std::vector<WellTableColumn> kWellTableColumns = {
    {"name", "井名"}, {"x", "X"},       {"y", "Y"},   {"z", "Z"},
    {"H_s", "Hs"},    {"H_t", "Ht"},    {"R_s", "Rs"}, {"q", "q"},
    {"b_i", "b"},     {"qc_flag", "QC"}, {"qc_z_star", "z*"},
};

namespace {

// Python "%.4g": C printf uses the same significant-digit + trailing-zero
// rules for finite values.
std::string format_g4(double value) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.4g", value);
    return buf;
}

// Python "%.4f".rstrip("0").rstrip(".").
std::string format_f4_stripped(double value) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.4f", value);
    std::string text(buf);
    while (!text.empty() && text.back() == '0') {
        text.pop_back();
    }
    if (!text.empty() && text.back() == '.') {
        text.pop_back();
    }
    return text;
}

const std::optional<double>* numeric_field(const WellTableRowSlice& row,
                                           const std::string& key) {
    static const std::unordered_map<std::string,
                                    const std::optional<double>
                                        WellTableRowSlice::*>
        fields = {
            {"x", &WellTableRowSlice::x},         {"y", &WellTableRowSlice::y},
            {"z", &WellTableRowSlice::z},         {"H_s", &WellTableRowSlice::h_s},
            {"H_t", &WellTableRowSlice::h_t},     {"R_s", &WellTableRowSlice::r_s},
            {"q", &WellTableRowSlice::q},         {"b_i", &WellTableRowSlice::b_i},
            {"qc_z_star", &WellTableRowSlice::qc_z_star},
        };
    const auto it = fields.find(key);
    if (it == fields.end()) {
        return nullptr;
    }
    return &(row.*(it->second));
}

}  // namespace

std::string well_table_fmt(std::optional<double> value,
                           const std::string& raw_when_non_numeric) {
    if (!value.has_value()) {
        return raw_when_non_numeric.empty() ? "" : raw_when_non_numeric;
    }
    const double f = *value;
    const double magnitude = std::abs(f);
    if (magnitude >= 1000.0 || (magnitude > 0.0 && magnitude < 0.001)) {
        return format_g4(f);
    }
    return format_f4_stripped(f);
}

std::optional<std::string> qc_foreground_token(const std::string& qc_flag) {
    static const std::unordered_map<std::string, std::string> tokens = {
        {"ok", "SUCCESS"},
        {"outlier", "WARNING"},
        {"invalid_ratio", "ERROR_RED"},
        {"missing", "TEXT_SECONDARY"},
    };
    const auto it = tokens.find(qc_flag);
    if (it == tokens.end()) {
        return std::nullopt;
    }
    return it->second;
}

std::string normalized_qc_flag(const std::string& qc_flag) {
    return qc_flag.empty() ? "ok" : qc_flag;
}

std::string well_table_title(const WellTableSlice& table) {
    std::string title =
        table.name.empty() ? std::string("WellTable") : table.name;
    if (!table.target_horizon.empty()) {
        title += " · " + table.target_horizon;
    }
    if (!table.factor_type.empty()) {
        title += " · " + table.factor_type;
    }
    return title;
}

std::string well_table_summary(const WellTableSlice& table) {
    static const char* order[] = {"ok", "outlier", "invalid_ratio", "missing"};
    std::unordered_map<std::string, std::size_t> counts;
    for (const WellTableRowSlice& row : table.rows) {
        ++counts[normalized_qc_flag(row.qc_flag)];
    }
    std::string text = std::to_string(table.rows.size()) + " 行";
    for (const char* flag : order) {
        const auto it = counts.find(flag);
        if (it != counts.end() && it->second > 0) {
            text += " · ";
            text += flag;
            text += ":";
            text += std::to_string(it->second);
        }
    }
    return text;
}

std::string well_table_cell(const WellTableRowSlice& row,
                            const std::string& column_key) {
    if (column_key == "name") {
        return row.name;
    }
    if (column_key == "qc_flag") {
        return normalized_qc_flag(row.qc_flag);
    }
    const std::optional<double>* numeric = numeric_field(row, column_key);
    if (numeric == nullptr) {
        return "";
    }
    const auto raw = row.raw_text.find(column_key);
    return well_table_fmt(
        *numeric, raw == row.raw_text.end() ? "" : raw->second);
}

}  // namespace pwb::ui_wellseis
