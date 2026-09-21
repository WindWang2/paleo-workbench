// mapping/revision_cache.py — LatestRevisionCache parity.
//
// One cached value per subject, valid only while its revision key matches:
//   * get() hits only on an exact revision-key match — a drifted revision
//     is a miss so callers rebuild instead of serving stale data;
//   * store() REPLACES any previous revision of the same subject (bounded
//     by the active subject set, not by revision churn);
//   * latest() reads WITHOUT revision validation — diagnostics/tests only,
//     production readers must use get();
//   * prune(keep) drops subjects absent from the keep set.
// Locking/diagnostics/eviction triggers stay with callers (Python parity).
#pragma once

#include <map>
#include <set>
#include <utility>
#include <vector>

namespace pwb::ui_canvas {

template <typename Subject, typename RevisionKey, typename Value>
class LatestRevisionCache {
public:
    const Value* get(const Subject& subject,
                     const RevisionKey& key) const {
        const auto it = entries_.find(subject);
        if (it != entries_.end() && it->second.first == key) {
            return &it->second.second;
        }
        return nullptr;
    }

    const Value* latest(const Subject& subject) const {
        const auto it = entries_.find(subject);
        return it != entries_.end() ? &it->second.second : nullptr;
    }

    void store(const Subject& subject, RevisionKey key, Value value) {
        entries_[subject] = std::make_pair(std::move(key), std::move(value));
    }

    std::vector<Subject> subjects() const {
        std::vector<Subject> out;
        out.reserve(entries_.size());
        for (const auto& [subject, entry] : entries_) out.push_back(subject);
        return out;
    }

    void remove(const Subject& subject) { entries_.erase(subject); }

    template <typename Iterable>
    void prune(const Iterable& keep) {
        const std::set<Subject> keep_set(keep.begin(), keep.end());
        for (auto it = entries_.begin(); it != entries_.end();) {
            if (!keep_set.count(it->first)) {
                it = entries_.erase(it);
            } else {
                ++it;
            }
        }
    }

    void clear() { entries_.clear(); }
    std::size_t size() const { return entries_.size(); }

private:
    std::map<Subject, std::pair<RevisionKey, Value>> entries_;
};

}  // namespace pwb::ui_canvas
