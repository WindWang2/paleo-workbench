// closure_agent.events — ordered event stream: subscription ordering,
// sequence numbers, bounded replay, unsubscribe.
#include "test_util.hpp"

#include <pwb/closure_agent/events.hpp>

using namespace pwb::closure_agent;

int main() {
    AgentEventBus bus;
    std::vector<std::string> seen_a;
    std::vector<std::string> seen_b;
    bus.subscribe([&](const AgentEvent& event) { seen_a.push_back(event.type); });
    bus.subscribe([&](const AgentEvent& event) { seen_b.push_back(event.type); });

    AgentEvent first;
    first.type = "session.plan_created";
    AgentEvent second;
    second.type = "session.node_started";
    second.node_id = "task_data_discover";
    bus.publish(std::move(first));
    bus.publish(std::move(second));

    check(seen_a.size() == 2 && seen_b.size() == 2,
          "both subscribers saw both events");
    check(seen_a == seen_b, "subscription order preserved");
    check(bus.last_seq() == 2, "sequence numbers monotonic");

    const auto replayed = bus.replay(10);
    check(replayed.size() == 2 && replayed[0].type == "session.plan_created",
          "replay is oldest-first");
    check(replayed[0].seq == 1 && replayed[1].seq == 2, "replay carries seq");
    check(bus.replay(1).size() == 1 && bus.replay(1)[0].seq == 2,
          "bounded replay returns the newest window");

    // Bounded buffer.
    AgentEventBus small;
    small.subscribe([](const AgentEvent&) {});
    for (int i = 0; i < 300; ++i) {
        AgentEvent event;
        event.type = "e" + std::to_string(i);
        small.publish(std::move(event));
    }
    check(small.replay(1000).size() == 256, "replay buffer capped at 256");
    check(small.replay(5).size() == 5, "replay window respected");

    // Unsubscribe.
    AgentEventBus unsubscribe_bus;
    const int id = unsubscribe_bus.subscribe(
        [](const AgentEvent&) {});
    check(unsubscribe_bus.subscriber_count() == 1, "subscribe counted");
    check(unsubscribe_bus.unsubscribe(id), "unsubscribe reported");
    check(!unsubscribe_bus.unsubscribe(id), "double unsubscribe refused");
    check(unsubscribe_bus.subscriber_count() == 0, "subscriber removed");

    // Deterministic clock seam.
    AgentEventBus clocked;
    clocked.set_clock([]() { return 42.5; });
    AgentEvent timed;
    timed.type = "session.state_changed";
    clocked.publish(std::move(timed));
    check(clocked.replay(1)[0].timestamp_sec == 42.5, "clock seam honored");

    return test_exit("closure_agent.events");
}
