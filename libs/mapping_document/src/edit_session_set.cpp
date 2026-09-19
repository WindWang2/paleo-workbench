#include <pwb/mapping_document/edit_session_set.hpp>

#include <algorithm>
#include <utility>

namespace pwb::mapping_document {

void EditSessionSet::open(const std::string& layer_id, const std::string& crs,
                          const void* stack) {
    layers_.assign(1, layer_id);
    frozen_crs_ = crs;
    stack_ref_ = stack;
}

std::vector<JoinDecision> EditSessionSet::request_join(
    const std::vector<std::string>& layer_ids, const Gate& gate) {
    std::vector<JoinDecision> decisions;
    decisions.reserve(layer_ids.size());
    for (const std::string& layer_id : layer_ids) {
        if (contains(layer_id)) {
            decisions.push_back({layer_id, true, ""});
            continue;
        }
        std::pair<bool, std::string> verdict{true, ""};
        if (gate) verdict = gate(layer_id);
        if (verdict.first) {
            layers_.push_back(layer_id);
            decisions.push_back({layer_id, true, ""});
        } else {
            decisions.push_back({layer_id, false,
                                 verdict.second.empty() ? "门禁拒绝"
                                                        : verdict.second});
        }
    }
    return decisions;
}

std::vector<std::string> EditSessionSet::close() {
    std::vector<std::string> was = layers_;
    layers_.clear();
    frozen_crs_.clear();
    stack_ref_ = nullptr;
    return was;
}

void EditSessionSet::discard(const std::string& layer_id) {
    std::erase(layers_, layer_id);
    if (layers_.empty()) {
        frozen_crs_.clear();
        stack_ref_ = nullptr;
    }
}

bool EditSessionSet::contains(const std::string& layer_id) const {
    return std::find(layers_.begin(), layers_.end(), layer_id) != layers_.end();
}

std::vector<std::string> EditSessionSet::active_layer_ids(
    const void* stack) const {
    if (layers_.empty() || stack_ref_ == nullptr) return {};
    if (stack_ref_ != stack) return {};
    return layers_;
}

std::pair<bool, std::string> EditSessionSet::allows_crs_change() const {
    if (is_open()) {
        return {false, "编辑会话进行中——CRS 已冻结，请先保存或回滚编辑"};
    }
    return {true, ""};
}

std::pair<bool, std::string> EditSessionSet::allows_schema_change(
    const std::string& layer_id) const {
    if (contains(layer_id)) {
        return {false, "图层「" + layer_id +
                           "」正在编辑会话中——字段结构变更被拒绝，请先保存或回滚编辑"};
    }
    return {true, ""};
}

}  // namespace pwb::mapping_document
