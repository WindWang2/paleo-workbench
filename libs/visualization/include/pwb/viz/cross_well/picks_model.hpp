#pragma once

// VIZ-B — horizon picks (层位拾取) model with command-pattern undo.
// Verbatim port of geoviz_cross_well/picks_model.py (Qt-free: signals
// become a change handler + revision counter; insertion-ordered dicts
// become vectors of pairs). JSON schema is field-for-field identical to
// the Python to_dict()/from_dict() — pick_id/formation_name/well_depths/
// source/confidence, no version field.

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::viz::cross_well {

// 12 lowercase hex characters — same shape as uuid4().hex[:12]. The C++
// generator is seeded from random_device; identity uniqueness within a
// session is what the correlation ids rely on (Python's uuid4 is not
// reproducible either).
[[nodiscard]] std::string new_pick_id();

// Well -> DTW confidence (insertion-ordered map substitute; Python dict).
struct PickConfidence {
    std::vector<std::pair<std::string, double>> entries;
    void set(const std::string& well, double value);
    void clear() { entries.clear(); }
    [[nodiscard]] bool empty() const { return entries.empty(); }
};

struct HorizonPick {
    std::string pick_id;
    std::string formation_name;
    // (well, depth) — nullopt depth where the pick is not yet connected.
    // Order = connection order (Python list of tuples).
    std::vector<std::pair<std::string, std::optional<double>>> well_depths;
    std::string source = "manual";  // "manual" | "dtw"
    PickConfidence confidence;

    [[nodiscard]] std::optional<double> depth_for_well(
        const std::string& well) const;
    void set_depth(const std::string& well, std::optional<double> depth);
    [[nodiscard]] std::vector<std::string> connected_wells() const;
};

class HorizonPicksModel {
  public:
    using ChangedHandler = std::function<void()>;

    // Out-of-line (Command is incomplete in user TUs).
    HorizonPicksModel();
    ~HorizonPicksModel();
    HorizonPicksModel(const HorizonPicksModel&) = delete;
    HorizonPicksModel& operator=(const HorizonPicksModel&) = delete;

    [[nodiscard]] std::string add_pick(const std::string& formation,
                                       const std::string& well, double depth,
                                       const std::string& source = "manual");
    // add_pick(source="dtw") plus per-well confidences — the GUI-side
    // apply path for DTW propagation results (one call per well pair).
    [[nodiscard]] std::string add_dtw_pick(
        const std::string& formation, const std::string& well, double depth,
        const PickConfidence& confidence);
    void connect_picks(const std::string& pick_id, const std::string& well,
                       double depth);
    void delete_pick(const std::string& pick_id);
    void move_pick(const std::string& pick_id, const std::string& well,
                   double new_depth);
    // Undoable disconnect (Python pick.set_depth(well, None)).
    void disconnect_pick(const std::string& pick_id, const std::string& well);

    // accept: dtw -> manual (NOT undoable — Python parity); reject:
    // delete (undoable). Both are no-ops on non-dtw picks.
    void accept_dtw_pick(const std::string& pick_id);
    void reject_dtw_pick(const std::string& pick_id);

    [[nodiscard]] std::vector<const HorizonPick*> picks_for_well(
        const std::string& well) const;
    [[nodiscard]] std::vector<const HorizonPick*> all_picks() const;
    [[nodiscard]] const HorizonPick* get_pick(
        const std::string& pick_id) const;

    [[nodiscard]] bool undo();
    [[nodiscard]] bool redo();
    [[nodiscard]] std::size_t undo_count() const { return undo_stack_.size(); }
    [[nodiscard]] std::size_t redo_count() const { return redo_stack_.size(); }

    // Direct confidence mutation (Python mutates pick.confidence in
    // place after connecting a dtw pick). No undo recording — parity.
    void set_pick_confidence(const std::string& pick_id,
                             const PickConfidence& confidence);

    void clear();

    [[nodiscard]] pwb::domain::Json to_json() const;
    void from_json(const pwb::domain::Json& data);  // clears undo stacks

    void set_changed_handler(ChangedHandler handler) {
        changed_handler_ = std::move(handler);
    }
    [[nodiscard]] std::uint64_t revision() const { return revision_; }

  private:
    struct Command;
    void execute(std::unique_ptr<Command> cmd);
    void emit_changed();
    HorizonPick* find_pick(const std::string& pick_id);

    // Python's model stores pick OBJECTS in an insertion-ordered dict and
    // the commands hold REFERENCES to them — a pick that is undone and
    // redone re-enters with the mutations it accumulated meanwhile
    // (aliasing). shared_ptr storage reproduces that exactly.
    std::vector<std::shared_ptr<HorizonPick>> picks_;
    std::vector<std::unique_ptr<Command>> undo_stack_;
    std::vector<std::unique_ptr<Command>> redo_stack_;
    static constexpr std::size_t kMaxUndoDepth = 100;
    ChangedHandler changed_handler_;
    std::uint64_t revision_ = 0;
};

}  // namespace pwb::viz::cross_well
