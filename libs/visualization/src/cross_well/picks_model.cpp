#include <pwb/viz/cross_well/picks_model.hpp>

#include <algorithm>
#include <atomic>
#include <memory>
#include <cmath>
#include <random>
#include <sstream>

namespace pwb::viz::cross_well {

std::string new_pick_id() {
    static std::atomic<std::uint64_t> counter{0};
    static std::mt19937_64 rng{std::random_device{}()};
    const std::uint64_t seq = counter.fetch_add(1);
    const std::uint64_t v = (rng() ^ (seq * 0x9E3779B97F4A7C15ULL));
    std::ostringstream out;
    out << std::hex;
    for (int nibble = 0; nibble < 12; ++nibble) {
        out << static_cast<int>((v >> (4 * nibble)) & 0xFULL);
    }
    return out.str();
}

void PickConfidence::set(const std::string& well, double value) {
    for (auto& entry : entries) {
        if (entry.first == well) {
            entry.second = value;
            return;
        }
    }
    entries.emplace_back(well, value);
}

HorizonPicksModel::HorizonPicksModel() = default;
HorizonPicksModel::~HorizonPicksModel() = default;

std::optional<double> HorizonPick::depth_for_well(
    const std::string& well) const {
    for (const auto& [w, d] : well_depths) {
        if (w == well) return d;
    }
    return std::nullopt;
}

void HorizonPick::set_depth(const std::string& well,
                            std::optional<double> depth) {
    for (auto& [w, d] : well_depths) {
        if (w == well) {
            d = depth;
            return;
        }
    }
    well_depths.emplace_back(well, depth);
}

std::vector<std::string> HorizonPick::connected_wells() const {
    std::vector<std::string> wells;
    for (const auto& [w, d] : well_depths) {
        if (d.has_value()) wells.push_back(w);
    }
    return wells;
}

// --- command pattern (Python PickCommand hierarchy collapsed into one
// variant-like struct — execute/undo pairs are exact ports). ---

struct HorizonPicksModel::Command {
    enum class Kind { kAdd, kDelete, kMove, kConnect, kDisconnect } kind;
    // Add / Delete: shared references to the LIVE pick objects (Python
    // aliasing — the pick that re-enters via redo carries its mutations).
    std::shared_ptr<HorizonPick> added;
    std::shared_ptr<HorizonPick> snapshot;
    std::string pick_id;
    // Move/Connect/Disconnect
    std::string well;
    double new_depth = 0.0;
    std::optional<double> old_depth;
};

HorizonPick* HorizonPicksModel::find_pick(
    const std::string& pick_id) {
    for (const auto& pick : picks_) {
        if (pick->pick_id == pick_id) return pick.get();
    }
    return nullptr;
}

void HorizonPicksModel::execute(std::unique_ptr<Command> cmd) {
    switch (cmd->kind) {
        case Command::Kind::kAdd:
            picks_.push_back(cmd->added);
            break;
        case Command::Kind::kDelete: {
            cmd->snapshot.reset();
            for (auto it = picks_.begin(); it != picks_.end(); ++it) {
                if ((*it)->pick_id == cmd->pick_id) {
                    cmd->snapshot = *it;
                    picks_.erase(it);
                    break;
                }
            }
            break;
        }
        case Command::Kind::kMove:
        case Command::Kind::kConnect:
        case Command::Kind::kDisconnect: {
            HorizonPick* pick = find_pick(cmd->pick_id);
            if (pick == nullptr) break;
            cmd->old_depth = pick->depth_for_well(cmd->well);
            pick->set_depth(cmd->well, cmd->kind == Command::Kind::kDisconnect
                                            ? std::nullopt
                                            : std::optional<double>(
                                                  cmd->new_depth));
            break;
        }
    }
    undo_stack_.push_back(std::move(cmd));
    if (undo_stack_.size() > kMaxUndoDepth) {
        undo_stack_.erase(undo_stack_.begin());
    }
    redo_stack_.clear();
}

std::string HorizonPicksModel::add_pick(const std::string& formation,
                                        const std::string& well, double depth,
                                        const std::string& source) {
    auto cmd = std::make_unique<Command>();
    cmd->kind = Command::Kind::kAdd;
    cmd->added = std::make_shared<HorizonPick>();
    cmd->added->pick_id = new_pick_id();
    cmd->added->formation_name = formation;
    cmd->added->well_depths.emplace_back(well, depth);
    cmd->added->source = source;
    const std::string pick_id = cmd->added->pick_id;
    execute(std::move(cmd));
    emit_changed();
    return pick_id;
}

void HorizonPicksModel::connect_picks(const std::string& pick_id,
                                      const std::string& well, double depth) {
    auto cmd = std::make_unique<Command>();
    cmd->kind = Command::Kind::kConnect;
    cmd->pick_id = pick_id;
    cmd->well = well;
    cmd->new_depth = depth;
    execute(std::move(cmd));
    emit_changed();
}

std::string HorizonPicksModel::add_dtw_pick(
    const std::string& formation, const std::string& well, double depth,
    const PickConfidence& confidence) {
    auto cmd = std::make_unique<Command>();
    cmd->kind = Command::Kind::kAdd;
    cmd->added = std::make_shared<HorizonPick>();
    cmd->added->pick_id = new_pick_id();
    cmd->added->formation_name = formation;
    cmd->added->well_depths.emplace_back(well, depth);
    cmd->added->source = "dtw";
    cmd->added->confidence = confidence;
    const std::string pick_id = cmd->added->pick_id;
    execute(std::move(cmd));
    emit_changed();
    return pick_id;
}

void HorizonPicksModel::delete_pick(const std::string& pick_id) {
    auto cmd = std::make_unique<Command>();
    cmd->kind = Command::Kind::kDelete;
    cmd->pick_id = pick_id;
    execute(std::move(cmd));
    emit_changed();
}

void HorizonPicksModel::move_pick(const std::string& pick_id,
                                  const std::string& well, double new_depth) {
    auto cmd = std::make_unique<Command>();
    cmd->kind = Command::Kind::kMove;
    cmd->pick_id = pick_id;
    cmd->well = well;
    cmd->new_depth = new_depth;
    execute(std::move(cmd));
    emit_changed();
}

void HorizonPicksModel::disconnect_pick(const std::string& pick_id,
                                        const std::string& well) {
    auto cmd = std::make_unique<Command>();
    cmd->kind = Command::Kind::kDisconnect;
    cmd->pick_id = pick_id;
    cmd->well = well;
    execute(std::move(cmd));
    emit_changed();
}

void HorizonPicksModel::accept_dtw_pick(const std::string& pick_id) {
    HorizonPick* pick = find_pick(pick_id);
    if (pick != nullptr && pick->source == "dtw") {
        pick->source = "manual";
        pick->confidence.clear();
        emit_changed();
    }
}

void HorizonPicksModel::set_pick_confidence(const std::string& pick_id,
                                            const PickConfidence& confidence) {
    HorizonPick* pick = find_pick(pick_id);
    if (pick == nullptr) return;
    pick->confidence = confidence;
    emit_changed();
}

void HorizonPicksModel::reject_dtw_pick(const std::string& pick_id) {
    const HorizonPick* pick = get_pick(pick_id);
    if (pick != nullptr && pick->source == "dtw") {
        delete_pick(pick_id);
    }
}

std::vector<const HorizonPick*> HorizonPicksModel::picks_for_well(
    const std::string& well) const {
    std::vector<const HorizonPick*> result;
    for (const auto& pick : picks_) {
        if (pick->depth_for_well(well).has_value()) {
            result.push_back(pick.get());
        }
    }
    return result;
}

std::vector<const HorizonPick*> HorizonPicksModel::all_picks() const {
    std::vector<const HorizonPick*> result;
    result.reserve(picks_.size());
    for (const auto& pick : picks_) result.push_back(pick.get());
    return result;
}

const HorizonPick* HorizonPicksModel::get_pick(
    const std::string& pick_id) const {
    for (const auto& pick : picks_) {
        if (pick->pick_id == pick_id) return pick.get();
    }
    return nullptr;
}

bool HorizonPicksModel::undo() {
    if (undo_stack_.empty()) return false;
    std::unique_ptr<Command> cmd = std::move(undo_stack_.back());
    undo_stack_.pop_back();
    switch (cmd->kind) {
        case Command::Kind::kAdd:
            for (auto it = picks_.begin(); it != picks_.end(); ++it) {
                if ((*it)->pick_id == cmd->added->pick_id) {
                    picks_.erase(it);
                    break;
                }
            }
            break;
        case Command::Kind::kDelete:
            if (cmd->snapshot != nullptr) {
                // Python re-inserts at the same dict key; dict insertion
                // order moves it to the end — port that exactly.
                picks_.push_back(cmd->snapshot);
            }
            break;
        case Command::Kind::kMove:
        case Command::Kind::kConnect:
        case Command::Kind::kDisconnect: {
            HorizonPick* pick = find_pick(cmd->pick_id);
            if (pick != nullptr) {
                pick->set_depth(cmd->well, cmd->old_depth);
            }
            break;
        }
    }
    redo_stack_.push_back(std::move(cmd));
    emit_changed();
    return true;
}

bool HorizonPicksModel::redo() {
    if (redo_stack_.empty()) return false;
    std::unique_ptr<Command> cmd = std::move(redo_stack_.back());
    redo_stack_.pop_back();
    const Command::Kind kind = cmd->kind;
    // Re-execute without re-recording: replicate execute()'s effects.
    switch (kind) {
        case Command::Kind::kAdd:
            picks_.push_back(cmd->added);
            break;
        case Command::Kind::kDelete:
            for (auto it = picks_.begin(); it != picks_.end(); ++it) {
                if ((*it)->pick_id == cmd->pick_id) {
                    picks_.erase(it);
                    break;
                }
            }
            break;
        case Command::Kind::kMove:
        case Command::Kind::kConnect:
        case Command::Kind::kDisconnect: {
            HorizonPick* pick = find_pick(cmd->pick_id);
            if (pick != nullptr) {
                cmd->old_depth = pick->depth_for_well(cmd->well);
                pick->set_depth(cmd->well,
                                kind == Command::Kind::kDisconnect
                                    ? std::nullopt
                                    : std::optional<double>(cmd->new_depth));
            }
            break;
        }
    }
    undo_stack_.push_back(std::move(cmd));
    emit_changed();
    return true;
}

void HorizonPicksModel::clear() {
    picks_.clear();
    undo_stack_.clear();
    redo_stack_.clear();
    emit_changed();
}

pwb::domain::Json HorizonPicksModel::to_json() const {
    using pwb::domain::Json;
    Json picks = Json::array();
    for (const auto& pick : picks_) {
        Json well_depths = Json::array();
        for (const auto& [w, d] : pick->well_depths) {
            well_depths.push_back(Json::array({w, d ? Json(*d) : Json()}));
        }
        Json confidence = Json::object();
        for (const auto& [w, c] : pick->confidence.entries) {
            confidence[w] = c;
        }
        picks.push_back(Json::object({
            {"pick_id", pick->pick_id},
            {"formation_name", pick->formation_name},
            {"well_depths", std::move(well_depths)},
            {"source", pick->source},
            {"confidence", std::move(confidence)},
        }));
    }
    return Json::object({{"picks", std::move(picks)}});
}

void HorizonPicksModel::from_json(const pwb::domain::Json& data) {
    using pwb::domain::Json;
    picks_.clear();
    if (data.contains("picks") && data.at("picks").is_array()) {
        for (const Json& item : data.at("picks")) {
            if (!item.is_object()) continue;
            auto pick = std::make_shared<HorizonPick>();
            pick->pick_id = item.value("pick_id", std::string());
            pick->formation_name = item.value("formation_name", std::string());
            if (item.contains("well_depths") &&
                item.at("well_depths").is_array()) {
                for (const Json& wd : item.at("well_depths")) {
                    if (!wd.is_array() || wd.size() < 2) continue;
                    const std::string well =
                        wd.at(0).is_string() ? wd.at(0).get<std::string>()
                                             : std::string();
                    std::optional<double> depth;
                    if (!wd.at(1).is_null()) {
                        if (wd.at(1).is_number()) {
                            depth = wd.at(1).get<double>();
                        }
                    }
                    pick->well_depths.emplace_back(well, depth);
                }
            }
            pick->source = item.value("source", std::string("manual"));
            if (item.contains("confidence") &&
                item.at("confidence").is_object()) {
                for (auto it = item.at("confidence").begin();
                     it != item.at("confidence").end(); ++it) {
                    if (it.value().is_number()) {
                        pick->confidence.entries.emplace_back(
                            it.key(), it.value().get<double>());
                    }
                }
            }
            picks_.push_back(std::move(pick));
        }
    }
    undo_stack_.clear();
    redo_stack_.clear();
    emit_changed();
}

void HorizonPicksModel::emit_changed() {
    ++revision_;
    if (changed_handler_) changed_handler_();
}

}  // namespace pwb::viz::cross_well
