#pragma once

// VIZ-B — formation tops (地层顶面) model.
// Verbatim port of geoviz_cross_well/tops_model.py (Qt-free: the Python
// QObject signal becomes a change handler + revision counter; the Python
// insertion-ordered dicts become vectors of pairs).

#include <cstdint>
#include <functional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::viz::cross_well {

// Fixed 10-colour formation palette (order is part of the contract).
inline constexpr std::size_t kFormationPaletteSize = 10;
const std::string& formation_palette_color(std::size_t index);

// sum(ord(c) for c in name) % 10 — the deterministic name hash used by
// FormationTop's default colour.
[[nodiscard]] std::string formation_color_for_name(
    const std::string& formation_name);

struct FormationTop {
    std::string well_name;
    std::string formation_name;
    double depth_m = 0.0;  // metres, MD
    std::string color;     // empty -> formation_color_for_name

    [[nodiscard]] std::string resolved_color() const {
        return color.empty() ? formation_color_for_name(formation_name)
                             : color;
    }
};

class FormationTopsModel {
  public:
    using ChangedHandler = std::function<void()>;

    // CSV rows: well,formation,depth — skips empty rows, '#' comments,
    // rows with < 3 columns and rows whose third column is not a float
    // (implicit header skip). Duplicate (well, formation) rows are kept.
    // Colours follow first-seen assignment; per-well lists end sorted by
    // depth ascending. Returns false when the file cannot be read.
    bool load_csv(const std::string& path);
    // Wells lexicographically sorted, per-well depth ascending, no header.
    bool save_csv(const std::string& path) const;

    [[nodiscard]] std::vector<FormationTop> tops_for_well(
        const std::string& well) const;
    [[nodiscard]] std::vector<FormationTop> all_tops() const;

    void add_top(FormationTop top);
    void delete_top(const std::string& well, const std::string& formation);

    // First-seen order over the per-well insertion order.
    [[nodiscard]] std::vector<std::string> formation_names() const;
    [[nodiscard]] std::vector<std::string> well_names() const;  // sorted

    void clear();

    void set_changed_handler(ChangedHandler handler) {
        changed_handler_ = std::move(handler);
    }
    [[nodiscard]] std::uint64_t revision() const { return revision_; }

  private:
    void emit_changed();

    // Insertion-ordered (Python dict parity).
    std::vector<std::pair<std::string, std::vector<FormationTop>>> tops_;
    std::vector<std::pair<std::string, std::string>> color_map_;
    ChangedHandler changed_handler_;
    std::uint64_t revision_ = 0;
};

}  // namespace pwb::viz::cross_well
