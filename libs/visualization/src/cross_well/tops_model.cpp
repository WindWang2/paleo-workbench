#include <pwb/viz/cross_well/tops_model.hpp>

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <sstream>
#include <stdexcept>

#include <pwb/domain/json.hpp>

namespace pwb::viz::cross_well {

namespace {

const std::string kPalette[kFormationPaletteSize] = {
    "#d97706",  // amber
    "#dc2626",  // red
    "#059669",  // emerald
    "#7c3aed",  // violet
    "#db2777",  // pink
    "#0891b2",  // cyan
    "#65a30d",  // lime
    "#ea580c",  // orange
    "#4f46e5",  // indigo
    "#0d9488",  // teal
};

std::string strip(const std::string& value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

// Minimal CSV row splitter (Python csv.reader single-char comma parity;
// quoted fields are not produced by our writer and not consumed by the
// Python reader for these files).
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
    try {
        std::size_t pos = 0;
        out = std::stod(strip(text), &pos);
        return pos == strip(text).size() || strip(text).find_first_not_of(
                                                 " \t\r\n", pos) ==
                                             std::string::npos;
    } catch (const std::exception&) {
        return false;
    }
}

const std::string* find_color(
    const std::vector<std::pair<std::string, std::string>>& map,
    const std::string& formation) {
    for (const auto& entry : map) {
        if (entry.first == formation) return &entry.second;
    }
    return nullptr;
}

std::string assign_color(
    const std::string& formation,
    const std::vector<std::pair<std::string, std::string>>& existing) {
    if (const std::string* found = find_color(existing, formation)) {
        return *found;
    }
    for (std::size_t i = 0; i < kFormationPaletteSize; ++i) {
        const std::string& candidate = formation_palette_color(i);
        bool used = false;
        for (const auto& entry : existing) {
            if (entry.second == candidate) {
                used = true;
                break;
            }
        }
        if (!used) return candidate;
    }
    return formation_palette_color(existing.size() % kFormationPaletteSize);
}

}  // namespace

const std::string& formation_palette_color(std::size_t index) {
    return kPalette[index % kFormationPaletteSize];
}

std::string formation_color_for_name(const std::string& formation_name) {
    // sum(ord(c)) over Unicode code points — Python iterates code points.
    // UTF-8 code-point sum differs from byte sum for non-ASCII names, so
    // decode properly.
    unsigned long long total = 0;
    std::size_t i = 0;
    while (i < formation_name.size()) {
        unsigned char c = static_cast<unsigned char>(formation_name[i]);
        std::size_t len = 1;
        unsigned int cp = c;
        if ((c & 0x80u) == 0u) {
            cp = c;
        } else if ((c & 0xE0u) == 0xC0u && i + 1 < formation_name.size()) {
            cp = ((c & 0x1Fu) << 6) |
                 (static_cast<unsigned char>(formation_name[i + 1]) & 0x3Fu);
            len = 2;
        } else if ((c & 0xF0u) == 0xE0u && i + 2 < formation_name.size()) {
            cp = ((c & 0x0Fu) << 12) |
                 ((static_cast<unsigned char>(formation_name[i + 1]) & 0x3Fu)
                  << 6) |
                 (static_cast<unsigned char>(formation_name[i + 2]) & 0x3Fu);
            len = 3;
        } else if ((c & 0xF8u) == 0xF0u && i + 3 < formation_name.size()) {
            cp = ((c & 0x07u) << 18) |
                 ((static_cast<unsigned char>(formation_name[i + 1]) & 0x3Fu)
                  << 12) |
                 ((static_cast<unsigned char>(formation_name[i + 2]) & 0x3Fu)
                  << 6) |
                 (static_cast<unsigned char>(formation_name[i + 3]) & 0x3Fu);
            len = 4;
        }
        total += cp;
        i += len;
    }
    return formation_palette_color(
        static_cast<std::size_t>(total % kFormationPaletteSize));
}

bool FormationTopsModel::load_csv(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) return false;
    tops_.clear();
    color_map_.clear();
    std::string line;
    while (std::getline(file, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (strip(line).empty() || line.empty() || line[0] == '#') continue;
        const std::vector<std::string> row = split_csv_row(line);
        if (row.size() < 3) continue;
        double depth = 0.0;
        if (!parse_double(row[2], depth)) continue;  // header rows skip here
        const std::string well = strip(row[0]);
        const std::string name = strip(row[1]);
        const std::string color = assign_color(name, color_map_);
        if (!find_color(color_map_, name)) {
            color_map_.emplace_back(name, color);
        }
        FormationTop top{well, name, depth, color};
        bool found = false;
        for (auto& entry : tops_) {
            if (entry.first == well) {
                entry.second.push_back(top);
                found = true;
                break;
            }
        }
        if (!found) tops_.emplace_back(well, std::vector<FormationTop>{top});
    }
    for (auto& entry : tops_) {
        std::stable_sort(entry.second.begin(), entry.second.end(),
                         [](const FormationTop& a, const FormationTop& b) {
                             return a.depth_m < b.depth_m;
                         });
    }
    emit_changed();
    return true;
}

namespace {

// csv.writer (excel dialect) parity: quote fields containing the
// delimiter, a quote or a newline; embedded quotes are doubled.
std::string csv_field(const std::string& value) {
    const bool needs_quotes = value.find_first_of(",\"\r\n") !=
                              std::string::npos;
    if (!needs_quotes) return value;
    std::string out = "\"";
    for (char c : value) {
        if (c == '"') out.push_back('"');
        out.push_back(c);
    }
    out.push_back('"');
    return out;
}

}  // namespace

bool FormationTopsModel::save_csv(const std::string& path) const {
    std::ofstream file(path);
    if (!file.is_open()) return false;
    std::vector<std::string> wells;
    wells.reserve(tops_.size());
    for (const auto& entry : tops_) wells.push_back(entry.first);
    std::sort(wells.begin(), wells.end());
    for (const auto& well : wells) {
        for (const auto& entry : tops_) {
            if (entry.first != well) continue;
            for (const FormationTop& top : entry.second) {
                // Python csv.writer emits str(float) — shortest roundtrip
                // with a trailing ".0" on integral values; nlohmann's
                // double dump matches that contract exactly. Rows end
                // with \r\n (excel dialect).
                file << csv_field(top.well_name) << ','
                     << csv_field(top.formation_name) << ','
                     << pwb::domain::Json(top.depth_m).dump() << "\r\n";
            }
            break;
        }
    }
    return true;
}

std::vector<FormationTop> FormationTopsModel::tops_for_well(
    const std::string& well) const {
    for (const auto& entry : tops_) {
        if (entry.first == well) return entry.second;
    }
    return {};
}

std::vector<FormationTop> FormationTopsModel::all_tops() const {
    std::vector<std::string> wells = well_names();
    std::vector<FormationTop> result;
    for (const auto& well : wells) {
        for (const FormationTop& top : tops_for_well(well)) {
            result.push_back(top);
        }
    }
    return result;
}

void FormationTopsModel::add_top(FormationTop top) {
    const std::string color =
        assign_color(top.formation_name, color_map_);
    if (!find_color(color_map_, top.formation_name)) {
        color_map_.emplace_back(top.formation_name, color);
    }
    if (top.color != color) {
        top.color = color;
    }
    bool found = false;
    for (auto& entry : tops_) {
        if (entry.first == top.well_name) {
            entry.second.push_back(top);
            std::stable_sort(entry.second.begin(), entry.second.end(),
                             [](const FormationTop& a, const FormationTop& b) {
                                 return a.depth_m < b.depth_m;
                             });
            found = true;
            break;
        }
    }
    if (!found) {
        tops_.emplace_back(top.well_name,
                           std::vector<FormationTop>{top});
    }
    emit_changed();
}

void FormationTopsModel::delete_top(const std::string& well,
                                    const std::string& formation) {
    for (auto it = tops_.begin(); it != tops_.end(); ++it) {
        if (it->first != well) continue;
        std::vector<FormationTop> kept;
        kept.reserve(it->second.size());
        for (const FormationTop& top : it->second) {
            if (top.formation_name != formation) kept.push_back(top);
        }
        if (kept.empty()) {
            tops_.erase(it);
        } else {
            it->second = std::move(kept);
        }
        emit_changed();
        return;
    }
}

std::vector<std::string> FormationTopsModel::formation_names() const {
    std::vector<std::string> seen;
    for (const auto& entry : tops_) {
        for (const FormationTop& top : entry.second) {
            if (std::find(seen.begin(), seen.end(), top.formation_name) ==
                seen.end()) {
                seen.push_back(top.formation_name);
            }
        }
    }
    return seen;
}

std::vector<std::string> FormationTopsModel::well_names() const {
    std::vector<std::string> wells;
    wells.reserve(tops_.size());
    for (const auto& entry : tops_) wells.push_back(entry.first);
    std::sort(wells.begin(), wells.end());
    return wells;
}

void FormationTopsModel::clear() {
    tops_.clear();
    color_map_.clear();
    emit_changed();
}

void FormationTopsModel::emit_changed() {
    ++revision_;
    if (changed_handler_) changed_handler_();
}

}  // namespace pwb::viz::cross_well
