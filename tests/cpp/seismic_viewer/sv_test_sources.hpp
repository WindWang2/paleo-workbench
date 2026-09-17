#pragma once

// Test source doubles for SCHEDULING verification only: each wraps a real
// backend and delegates every read to it (real data, real bytes); the double
// only observes or delays. Pixel/numeric audits never run against a double's
// own data — they compare the real backend's planes.

#include <atomic>
#include <chrono>
#include <memory>
#include <thread>

#include <pwb/viz/seismic_volume.hpp>

namespace sv_test_sources {

// Counts read_slice calls/elements and can inject a per-call delay; delegates
// to the wrapped real backend.
class ObservingVolume final : public pwb::viz::ISeismicVolume {
public:
    explicit ObservingVolume(std::shared_ptr<pwb::viz::ISeismicVolume> real,
                             std::chrono::milliseconds delay = std::chrono::milliseconds::zero())
        : real_(std::move(real)), delay_(delay) {}

    [[nodiscard]] const pwb::viz::VolumeGeometryV1& geometry() const override {
        return real_->geometry();
    }

    std::size_t read_slice(pwb::viz::VolumeAxis axis, std::int64_t index,
                           std::span<float> out) override {
        reads_entered_.fetch_add(1);
        // Reentrancy guard: proves reads are serialized (one worker thread).
        if (concurrent_reads_.fetch_add(1) != 0) {
            overlapped_reads_.fetch_add(1);
        }
        if (delay_ > std::chrono::milliseconds::zero()) {
            std::this_thread::sleep_for(delay_);
        }
        const std::size_t written = real_->read_slice(axis, index, out);
        elements_read_.fetch_add(written);
        total_reads_.fetch_add(1);
        concurrent_reads_.fetch_sub(1);
        return written;
    }

    [[nodiscard]] std::shared_ptr<const void> lifetime() const override {
        return real_->lifetime();
    }

    [[nodiscard]] std::uint64_t reads_entered() const { return reads_entered_.load(); }
    [[nodiscard]] std::uint64_t total_reads() const { return total_reads_.load(); }
    [[nodiscard]] std::uint64_t elements_read() const { return elements_read_.load(); }
    [[nodiscard]] std::uint64_t overlapped_reads() const {
        return overlapped_reads_.load();
    }

private:
    std::shared_ptr<pwb::viz::ISeismicVolume> real_;
    std::chrono::milliseconds delay_;
    std::atomic<std::uint64_t> reads_entered_{0};
    std::atomic<std::uint64_t> total_reads_{0};
    std::atomic<std::uint64_t> elements_read_{0};
    std::atomic<std::uint32_t> concurrent_reads_{0};
    std::atomic<std::uint64_t> overlapped_reads_{0};
};

// A real backend whose read_slice fails while the failure flag is set (bounds
// are valid; the injection forces written=0 semantics observably at the
// wrapper). Used to prove visible failure states and recovery.
class FlakyVolume final : public pwb::viz::ISeismicVolume {
public:
    FlakyVolume(std::shared_ptr<pwb::viz::ISeismicVolume> real, std::atomic<bool>* fail_flag)
        : real_(std::move(real)), fail_flag_(fail_flag) {}

    [[nodiscard]] const pwb::viz::VolumeGeometryV1& geometry() const override {
        return real_->geometry();
    }

    std::size_t read_slice(pwb::viz::VolumeAxis axis, std::int64_t index,
                           std::span<float> out) override {
        if (fail_flag_ != nullptr && fail_flag_->load()) {
            return 0; // simulated backend failure: contract-preserving
        }
        return real_->read_slice(axis, index, out);
    }

    [[nodiscard]] std::shared_ptr<const void> lifetime() const override {
        return real_->lifetime();
    }

private:
    std::shared_ptr<pwb::viz::ISeismicVolume> real_;
    std::atomic<bool>* fail_flag_;
};

} // namespace sv_test_sources
