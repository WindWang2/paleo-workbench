#include <pwb/viz/cross_well/seismic_tie.hpp>

#include <algorithm>
#include <cctype>
#include <fstream>
#include <numeric>
#include <sstream>
#include <tuple>
#include <utility>

namespace pwb::viz::cross_well {

namespace {

std::string strip(const std::string& value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

std::string lower(const std::string& value) {
    std::string out;
    out.reserve(value.size());
    for (unsigned char c : value) {
        out.push_back(static_cast<char>(std::tolower(c)));
    }
    return out;
}

std::vector<std::string> split_csv_row(const std::string& line) {
    std::vector<std::string> cells;
    std::string current;
    std::istringstream stream(line);
    while (std::getline(stream, current, ',')) {
        cells.push_back(current);
    }
    if (!line.empty() && line.back() == ',') cells.push_back("");
    return cells;
}

bool parse_double(const std::string& text, double& out) {
    const std::string s = strip(text);
    if (s.empty()) return false;
    try {
        std::size_t pos = 0;
        out = std::stod(s, &pos);
        return pos == s.size();
    } catch (const std::exception&) {
        return false;
    }
}

}  // namespace

bool SeismicTie::load_csv(const std::string& path,
                          const std::optional<std::string>& well_name) {
    std::ifstream file(path);
    if (!file.is_open()) return false;
    // (well -> parallel depth/twt vectors), insertion ordered.
    std::vector<std::tuple<std::string, std::vector<double>,
                           std::vector<double>>>
        by_well;
    bool has_well_col = false;

    std::string line;
    while (std::getline(file, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (strip(line).empty() || line.empty() || line[0] == '#') continue;
        std::vector<std::string> cells;
        for (const std::string& cell : split_csv_row(line)) {
            cells.push_back(strip(cell));
        }
        if (cells.empty()) continue;
        // Header detection only matches BEFORE any data row (Python
        // checks each row independently but a depth_m cell in data would
        // fail float parse anyway — same effect; keep the exact
        // per-row check like Python).
        const std::string header_first = lower(cells[0]);
        if (header_first == "depth_m" || header_first == "depth" ||
            header_first == "md") {
            has_well_col = false;
            for (const std::string& cell : cells) {
                if (lower(cell).find("well") != std::string::npos) {
                    has_well_col = true;
                    break;
                }
            }
            continue;
        }
        if (cells.size() < 2) continue;
        double d = 0.0, t = 0.0;
        if (!parse_double(cells[0], d) || !parse_double(cells[1], t)) {
            continue;
        }
        std::string w;
        if (has_well_col && cells.size() >= 3 && !cells[2].empty()) {
            w = cells[2];
        } else {
            w = well_name.value_or("default");
        }
        bool found = false;
        for (auto& entry : by_well) {
            if (std::get<0>(entry) == w) {
                std::get<1>(entry).push_back(d);
                std::get<2>(entry).push_back(t);
                found = true;
                break;
            }
        }
        if (!found) {
            by_well.emplace_back(w, std::vector<double>{d},
                                 std::vector<double>{t});
        }
    }

    for (auto& [name, depths, twts] : by_well) {
        std::vector<std::size_t> order(depths.size());
        std::iota(order.begin(), order.end(), std::size_t{0});
        std::stable_sort(order.begin(), order.end(),
                         [&](std::size_t a, std::size_t b) {
                             return depths[a] < depths[b];
                         });
        std::vector<double> sorted_depths(depths.size());
        std::vector<double> sorted_twts(twts.size());
        for (std::size_t i = 0; i < order.size(); ++i) {
            sorted_depths[i] = depths[order[i]];
            sorted_twts[i] = twts[order[i]];
        }
        CheckshotTable table{name, std::move(sorted_depths),
                             std::move(sorted_twts)};
        bool replaced = false;
        for (CheckshotTable& existing : tables_) {
            if (existing.well_name == name) {
                existing = std::move(table);
                replaced = true;
                break;
            }
        }
        if (!replaced) tables_.push_back(std::move(table));
    }
    return true;
}

std::optional<double> SeismicTie::depth_to_twt(const std::string& well,
                                               double depth) const {
    const CheckshotTable* table = table_for_well(well);
    if (table == nullptr) return std::nullopt;
    return table->interpolate_twt(depth);
}

std::optional<double> SeismicTie::twt_to_depth(const std::string& well,
                                               double twt) const {
    const CheckshotTable* table = table_for_well(well);
    if (table == nullptr) return std::nullopt;
    return table->interpolate_depth(twt);
}

bool SeismicTie::has_well(const std::string& well) const {
    return table_for_well(well) != nullptr;
}

const CheckshotTable* SeismicTie::table_for_well(
    const std::string& well) const {
    for (const CheckshotTable& table : tables_) {
        if (table.well_name == well) return &table;
    }
    return nullptr;
}

std::vector<std::string> SeismicTie::well_names() const {
    std::vector<std::string> names;
    names.reserve(tables_.size());
    for (const CheckshotTable& table : tables_) {
        names.push_back(table.well_name);
    }
    return names;
}

void SeismicTie::clear() { tables_.clear(); }

}  // namespace pwb::viz::cross_well
