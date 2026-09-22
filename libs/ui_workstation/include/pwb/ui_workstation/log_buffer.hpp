#pragma once

// Port of paleo_workbench/ui/workstation/process_hub.py's buffering
// layer (UI-12): the QtLogHandler's bounded pending deque + line
// formatter, Qt-free so the widget only owns the signal hop and the
// QPlainTextEdit. Contract:
//
//  * LOG_LINE_CAP = 2000 — the widget's maximumBlockCount and the
//    memory buffer share the cap (oldest dropped first);
//  * take_pending() drains — signal + 1 s poll share one take path so
//    no line is ever appended twice;
//  * a dead/destroyed consumer must never fault the logging path —
//    the Qt shell wraps emit in try/catch; the buffer itself is plain
//    data.

#include <deque>
#include <string>
#include <vector>
#include <mutex>

namespace pwb::ui_workstation {

// Python LOG_LINE_CAP.
inline constexpr int kLogLineCap = 2000;

// "%(asctime)s %(levelname)-7s %(name)s: %(message)s" with "%H:%M:%S".
// `level` is the Python levelname (INFO/WARNING/…); padded to 7.
std::string format_log_line(const std::string& hh_mm_ss,
                            const std::string& level,
                            const std::string& logger_name,
                            const std::string& message);

// Bounded pending-line buffer (deque(maxlen=cap) parity): push drops
// the OLDEST lines over capacity; take_pending drains.
class LogBuffer {
public:
    explicit LogBuffer(int capacity = kLogLineCap)
        : capacity_(capacity < 1 ? 1 : capacity) {}

    // R2-23: the class contract says "any thread may post" while the
    // producer races the GUI poll timer's take — an unsynchronized deque
    // is UB no try/catch can intercept. Mutex-guarded (the operations are
    // tiny; contention is irrelevant at log cadence).
    void push(const std::string& line) {
        const std::lock_guard<std::mutex> lock(mutex_);
        pending_.push_back(line);
        while (static_cast<int>(pending_.size()) > capacity_) {
            pending_.pop_front();
        }
    }

    std::vector<std::string> take_pending() {
        const std::lock_guard<std::mutex> lock(mutex_);
        std::vector<std::string> out(pending_.begin(), pending_.end());
        pending_.clear();
        return out;
    }

    int pending_count() const {
        const std::lock_guard<std::mutex> lock(mutex_);
        return static_cast<int>(pending_.size());
    }
    int capacity() const { return capacity_; }

private:
    mutable std::mutex mutex_;
    std::deque<std::string> pending_;
    int capacity_;
};

}  // namespace pwb::ui_workstation
