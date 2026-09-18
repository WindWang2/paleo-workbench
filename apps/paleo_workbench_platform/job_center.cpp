// CONV-30 — JobCenter implementation (see job_center.hpp).

#include "job_center.hpp"

namespace pwb::app {

JobCenter::JobCenter() {
    scheduler_ = std::make_shared<pwb::job::JobScheduler>(
        pwb::job::JobScheduler::Options{.max_workers = 1,
                                        .interactive_workers = 1});
    // App quit must never die with live jobs: bounded drain on aboutToQuit
    // (the shared_ptr capture keeps the scheduler reachable even if the
    // window died first).
    pwb::job::qtbridge::install_quit_drain(scheduler_, 5000);
}

JobCenter::~JobCenter() {
    // Ordered teardown: stop job bodies at their next safe point, then
    // bounded-drain the scheduler. Owners' queued GUI deliveries are
    // already suppressed by the owners' released flags.
    alive_->store(false);
    for (const auto& owner : owners_) {
        if (owner->is_running()) owner->shutdown(0);
    }
    scheduler_->shutdown(true, 2.0);
}

pwb::job::qtbridge::JobOwner& JobCenter::make_owner(QObject* parent) {
    owners_.push_back(std::make_unique<pwb::job::qtbridge::JobOwner>(parent));
    return *owners_.back();
}

void JobCenter::shutdown_workers(int wait_ms) {
    for (const auto& owner : owners_) {
        if (owner->is_running()) {
            owner->shutdown(wait_ms);
        }
    }
}

}  // namespace pwb::app
