#include "pwb/ui_shell/command_registry.hpp"

#include <algorithm>
#include <cctype>

#include "pwb/tool_policy/tool_availability.hpp"

namespace pwb::ui_shell {

std::string ascii_lower(const std::string& text) {
    std::string out = text;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return out;
}

int subsequence_score(const std::string& needle, const std::string& haystack) {
    std::size_t index = 0;
    int start = -1;
    for (const char ch : needle) {
        if (std::isspace(static_cast<unsigned char>(ch))) {
            continue;
        }
        const auto found = haystack.find(ch, index);
        if (found == std::string::npos) {
            return -1;
        }
        if (start < 0) {
            start = static_cast<int>(found);
        }
        index = found + 1;
    }
    return std::max(start, 0);
}

void CommandRegistry::register_command(const CommandSpec& spec) {
    // Same-id re-register replaces (Python logger.debug parity is a no-op
    // here — the qt side may log at the call site).
    specs_[spec.id] = spec;
}

void CommandRegistry::unregister(const std::string& command_id) {
    specs_.erase(command_id);
    const auto it = std::find(recent_.begin(), recent_.end(), command_id);
    if (it != recent_.end()) {
        recent_.erase(it);
    }
}

void CommandRegistry::clear(bool keep_core) {
    for (auto it = specs_.begin(); it != specs_.end();) {
        if (keep_core && it->first.rfind("core:", 0) == 0) {
            ++it;
            continue;
        }
        it = specs_.erase(it);
    }
}

std::vector<const CommandSpec*> CommandRegistry::specs() const {
    std::vector<const CommandSpec*> out;
    out.reserve(specs_.size());
    for (const auto& [id, spec] : specs_) {
        out.push_back(&spec);
    }
    std::sort(out.begin(), out.end(), [](const CommandSpec* a,
                                         const CommandSpec* b) {
        if (a->group != b->group) {
            return a->group < b->group;
        }
        return a->label < b->label;
    });
    return out;
}

const CommandSpec* CommandRegistry::get(const std::string& command_id) const {
    const auto it = specs_.find(command_id);
    return it == specs_.end() ? nullptr : &it->second;
}

CommandAvailability CommandRegistry::evaluate(
    const std::string& command_id, const CommandContext* context) const {
    const CommandSpec* spec = get(command_id);
    if (spec == nullptr) {
        return {false, "未知命令"};
    }
    if (context == nullptr) {
        return {true, ""};
    }
    if (spec->requires_write && !context->write_granted) {
        return {false, "需要写入授权（当前会话只读）"};
    }
    if (!spec->stages.empty()) {
        // Fail-closed: unknown stage (provider fault / no project) disables
        // stage-bound commands.
        if (!context->mapping_stage.has_value()) {
            return {false, "当前编图阶段未知"};
        }
        const auto& stage = *context->mapping_stage;
        if (std::find(spec->stages.begin(), spec->stages.end(), stage) ==
            spec->stages.end()) {
            return {false,
                    tool_policy::stage_whitelist_reason(spec->stages)};
        }
    }
    if (spec->applicability) {
        std::optional<std::string> reason;
        try {
            reason = spec->applicability(*context);
        } catch (...) {
            // Predicate crash -> unavailable (Python BLE001 parity).
            return {false, "无法判定可用性"};
        }
        if (reason.has_value() && !reason->empty()) {
            return {false, *reason};
        }
    }
    return {true, ""};
}

std::vector<const CommandSpec*> CommandRegistry::find(
    const std::string& query, int limit, const CommandContext* context) const {
    const std::string text = ascii_lower([&] {
        std::string q = query;
        const auto first = q.find_first_not_of(" \t\n\r\f\v");
        const auto last = q.find_last_not_of(" \t\n\r\f\v");
        return first == std::string::npos
                   ? std::string()
                   : q.substr(first, last - first + 1);
    }());

    std::vector<const CommandSpec*> pool = specs();
    if (context != nullptr) {
        std::vector<const CommandSpec*> kept;
        kept.reserve(pool.size());
        for (const CommandSpec* spec : pool) {
            if (spec->hidden_when_unavailable &&
                !evaluate(spec->id, context).enabled) {
                continue;
            }
            kept.push_back(spec);
        }
        pool = std::move(kept);
    }
    if (text.empty()) {
        if (static_cast<int>(pool.size()) > limit) {
            pool.resize(static_cast<std::size_t>(limit));
        }
        return pool;
    }

    std::vector<std::pair<int, const CommandSpec*>> scored;
    for (const CommandSpec* spec : pool) {
        const std::string label = ascii_lower(spec->label);
        std::string weak = spec->keywords;
        for (const auto& tag : spec->context_tags) {
            weak += " ";
            weak += tag;
        }
        weak += " ";
        weak += spec->hint;
        weak = ascii_lower(weak);

        int score = subsequence_score(text, label);
        if (score < 0) {
            score = subsequence_score(text, weak);
            if (score >= 0) {
                score += 10;  // weak-match demotion
            }
        }
        if (score >= 0) {
            if (label.rfind(text, 0) == 0) {
                score -= 5;  // prefix hit priority
            }
            scored.emplace_back(score, spec);
        }
    }
    std::stable_sort(scored.begin(), scored.end(),
                     [](const auto& a, const auto& b) {
                         return a.first < b.first;
                     });
    std::vector<const CommandSpec*> out;
    out.reserve(scored.size());
    for (const auto& [score, spec] : scored) {
        if (static_cast<int>(out.size()) >= limit) {
            break;
        }
        out.push_back(spec);
    }
    return out;
}

void CommandRegistry::record_recent(const std::string& command_id) {
    if (specs_.find(command_id) == specs_.end()) {
        return;
    }
    const auto it = std::find(recent_.begin(), recent_.end(), command_id);
    if (it != recent_.end()) {
        recent_.erase(it);
    }
    recent_.insert(recent_.begin(), command_id);
    if (recent_.size() > kRecentMax) {
        recent_.resize(kRecentMax);
    }
    if (sink_.save) {
        sink_.save(recent_);
    }
}

std::vector<const CommandSpec*> CommandRegistry::recent_specs() const {
    std::vector<const CommandSpec*> out;
    for (const auto& id : recent_) {
        const auto it = specs_.find(id);
        if (it != specs_.end()) {
            out.push_back(&it->second);
        }
    }
    return out;
}

void CommandRegistry::load_recent() {
    recent_.clear();
    if (!sink_.load) {
        return;
    }
    for (auto& id : sink_.load()) {
        recent_.push_back(std::move(id));
        if (recent_.size() >= kRecentMax) {
            break;
        }
    }
}

void CommandRegistry::bind_settings(RecentSettingsSink sink) {
    sink_ = std::move(sink);
}

CommandRegistry& command_registry() {
    static CommandRegistry registry;
    return registry;
}

}  // namespace pwb::ui_shell
