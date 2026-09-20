// events.cpp — ordered event bus with bounded replay.
#include <pwb/closure_agent/events.hpp>

#include <chrono>
#include <cmath>

namespace pwb::closure_agent {

Json AgentEvent::to_json() const {
    Json json = Json::object();
    json["seq"] = seq;
    json["type"] = type;
    json["session_id"] = session_id;
    json["turn_id"] = turn_id;
    json["node_id"] = node_id;
    json["payload"] = payload;
    Json timestamp = std::round(timestamp_sec * 1000.0) / 1000.0;
    json["timestamp"] = timestamp;
    return json;
}

int AgentEventBus::subscribe(Handler handler) {
    std::lock_guard<std::mutex> lock(mutex_);
    const int id = next_subscription_++;
    handlers_.emplace_back(id, std::move(handler));
    return id;
}

bool AgentEventBus::unsubscribe(int subscription_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto it = handlers_.begin(); it != handlers_.end(); ++it) {
        if (it->first == subscription_id) {
            handlers_.erase(it);
            return true;
        }
    }
    return false;
}

void AgentEventBus::publish(AgentEvent event) {
    std::vector<Handler> snapshot;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        event.seq = seq_.fetch_add(1, std::memory_order_acq_rel) + 1;
        event.timestamp_sec =
            clock_ ? clock_()
                   : std::chrono::duration<double>(
                         std::chrono::system_clock::now().time_since_epoch())
                         .count();
        recent_.push_back(event);
        while (recent_.size() > recent_limit_) recent_.pop_front();
        snapshot.reserve(handlers_.size());
        for (const auto& [id, handler] : handlers_) snapshot.push_back(handler);
    }
    // Handlers run without the lock; publishing is single-threaded by
    // contract, so ordering is the subscription order.
    for (const auto& handler : snapshot) handler(event);
}

std::vector<AgentEvent> AgentEventBus::replay(std::size_t max_events) const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<AgentEvent> events;
    const std::size_t skip =
        recent_.size() > max_events ? recent_.size() - max_events : 0;
    for (std::size_t i = skip; i < recent_.size(); ++i) events.push_back(recent_[i]);
    return events;
}

std::size_t AgentEventBus::subscriber_count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return handlers_.size();
}

}  // namespace pwb::closure_agent
