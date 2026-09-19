#include <pwb/ui_composite/layer_decorations.hpp>

#include <map>
#include <sstream>
#include <vector>

namespace pwb::ui_composite {
namespace {

using pwb::ui_workstation::state_token;

// 装饰优先级（前者胜出；状态列只显示一个主信号，hover 显示全部）。
constexpr const char* kPriority[] = {
    "missing",  "dirty",   "editing",   "missing_input", "superseded",
    "stale",    "degraded", "frozen",   "published",     "reviewed",
};

std::optional<StateToken> token_for(const std::string& kind,
                                    const LayerPresentationState& state) {
    (void)state;
    if (kind == "missing") {
        return state_token("freshness", "missing");
    }
    if (kind == "dirty") {
        return state_token("session", "dirty");
    }
    if (kind == "editing") {
        return state_token("session", "editing");
    }
    if (kind == "missing_input") {
        return state_token("freshness", "missing_input");
    }
    if (kind == "superseded") {
        return state_token("freshness", "superseded");
    }
    if (kind == "stale") {
        return state_token("freshness", "stale");
    }
    if (kind == "degraded") {
        return state_token("backend", "fallback");
    }
    if (kind == "frozen" || kind == "published" || kind == "reviewed") {
        return state_token("maturity", kind.c_str());
    }
    return std::nullopt;
}

}  // namespace

std::optional<std::pair<std::string, StateToken>> primary_decoration(
    const LayerPresentationState& state) {
    const std::map<std::string, bool> flags = {
        {"missing", state.missing},
        {"dirty", state.dirty},
        {"editing", state.editing && !state.dirty},
        {"missing_input", state.missing_input},
        {"superseded", state.superseded},
        {"stale", state.stale},
        {"degraded", state.degraded},
        {"frozen",
         state.maturity.has_value() && *state.maturity == "frozen"},
        {"published",
         state.maturity.has_value() && *state.maturity == "published"},
        {"reviewed",
         state.maturity.has_value() && *state.maturity == "reviewed"},
    };
    for (const char* kind : kPriority) {
        auto it = flags.find(kind);
        if (it != flags.end() && it->second) {
            if (auto token = token_for(kind, state)) {
                return std::make_pair(std::string(kind), *token);
            }
        }
    }
    return std::nullopt;
}

std::optional<StateToken> decoration_token(
    const LayerPresentationState& state) {
    auto primary = primary_decoration(state);
    return primary.has_value() ? std::optional<StateToken>(primary->second)
                               : std::nullopt;
}

std::string decoration_summary_text(const LayerPresentationState& state) {
    std::vector<std::string> parts;
    if (state.missing) {
        parts.push_back("图层不在编辑注册表（缺失）");
    }
    if (state.editing && state.dirty) {
        parts.push_back(state_token("session", "dirty").label);
    } else if (state.editing) {
        parts.push_back(state_token("session", "editing").label);
    }
    if (state.missing_input) {
        parts.push_back(state_token("freshness", "missing_input").label);
    }
    if (state.superseded) {
        parts.push_back(state_token("freshness", "superseded").label);
    }
    if (state.stale) {
        parts.push_back(state_token("freshness", "stale").label);
    }
    if (state.degraded) {
        parts.push_back("数据源降级");
    }
    if (state.maturity.has_value() &&
        (*state.maturity == "raw" || *state.maturity == "frozen" ||
         *state.maturity == "published" || *state.maturity == "reviewed")) {
        parts.push_back(state_token("maturity", *state.maturity).label);
    }
    std::ostringstream out;
    for (size_t i = 0; i < parts.size(); ++i) {
        if (i > 0) {
            out << " · ";
        }
        out << parts[i];
    }
    return out.str();
}

std::string GroupPresentationSummary::summary_text() const {
    std::ostringstream out;
    out << layers << " 层";
    if (errors) {
        out << " ✕ " << errors;
    }
    if (stale) {
        out << " ↻ " << stale;
    }
    if (running) {
        out << " ▶ " << running;
    }
    if (pending) {
        out << " … " << pending;
    }
    if (frozen) {
        out << " ❄ " << frozen;
    }
    if (published) {
        out << " ◉ 已发布 " << published;
    }
    if (!(errors || stale || running || pending || frozen || published)) {
        out << " 无异常";
    }
    return out.str();
}

LayerPresentationState presentation_state(
    bool editing, int session_undo_depth,
    const std::string& freshness_status,
    const std::optional<std::string>& maturity, bool missing,
    bool degraded) {
    return LayerPresentationState{
        .editing = editing,
        .dirty = editing && session_undo_depth > 0,
        .stale = freshness_status == "stale",
        .missing_input = freshness_status == "missing_input",
        .superseded = freshness_status == "superseded",
        .degraded = degraded,
        .maturity = maturity,
        .missing = missing,
    };
}

}  // namespace pwb::ui_composite
