#pragma once

// Session event stream: ordered, subscribable, bounded replay buffer. The
// UI adapter (line 12 assembly) consumes this stream; the session publishes
// every state transition, plan, node outcome, receipt and checkpoint.
// Qt-free: handlers are plain functions; a Qt host marshals onto its loop.

#include <pwb/domain/json.hpp>

#include <atomic>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <vector>

namespace pwb::closure_agent {

using Json = pwb::domain::Json;

struct AgentEvent {
    long long seq = 0;          // bus-wide monotonic
    std::string type;           // e.g. "session.state_changed", "receipt.issued"
    std::string session_id;
    std::string turn_id;
    std::string node_id;        // "" when not node-scoped
    Json payload = Json::object();
    double timestamp_sec = 0.0; // injected clock seam

    Json to_json() const;
};

class AgentEventBus {
public:
    using Handler = std::function<void(const AgentEvent&)>;

    // Returns a subscription id; handlers run in publishing order (synchronous,
    // single-threaded publisher contract — like the Python Qt signal bridge).
    int subscribe(Handler handler);
    bool unsubscribe(int subscription_id);
    void publish(AgentEvent event);

    // Bounded replay of the most recent events (oldest first).
    std::vector<AgentEvent> replay(std::size_t max_events) const;

    std::size_t subscriber_count() const;
    long long last_seq() const { return seq_.load(std::memory_order_acquire); }

    void set_clock(std::function<double()> clock) { clock_ = std::move(clock); }

private:
    mutable std::mutex mutex_;
    std::vector<std::pair<int, Handler>> handlers_;
    int next_subscription_ = 1;
    std::atomic<long long> seq_{0};
    std::deque<AgentEvent> recent_;
    std::size_t recent_limit_ = 256;
    std::function<double()> clock_;
};

}  // namespace pwb::closure_agent
