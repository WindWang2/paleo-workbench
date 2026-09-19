#pragma once

// SliceController — Qt-free request scheduling core for the seismic viewer.
//
// Threading contract (v3, frozen):
//   * ISeismicVolume makes no thread-safety promise. Exactly one worker
//     thread exists per controller and it is the ONLY thread that ever calls
//     read_slice()/geometry()/lifetime() on the current source; calls are
//     strictly serialized.
//   * submit()/set_source()/request_shutdown() may be called from any thread
//     (the widget calls them on the GUI thread); they never block on I/O.
//   * The sink callback runs on the WORKER thread. Sinks must not call back
//     into the controller synchronously. Qt hosts bridge to the GUI thread
//     themselves (the widget uses QMetaObject::invokeMethod queued).
//   * After request_shutdown() completes — or the destructor is entered —
//     the sink is never invoked again.
//
// Coalescing / staleness (v3, frozen):
//   * There is at most ONE queued request and ONE in-flight request. A new
//     submit replaces a still-queued request (fast slider drags merge) and
//     supersedes an in-flight one (its result is computed but discarded).
//   * Every request carries a global monotonic generation; every set_source
//     bumps the epoch and drops the queue and the plane cache. A computed
//     result is delivered only when its epoch matches the current epoch AND
//     its generation matches the newest submitted generation — a late result
//     from an old source or an old request can never be applied.
//   * The plane cache holds raw float planes (never colored bytes) keyed by
//     (epoch, axis, index) with a small LRU cap set at construction; the
//     cache never holds more planes than that cap and never copies the
//     whole volume.
//   * Prefetch: after the worker delivers a successful inline/crossline
//     request and no newer work is queued or in flight, it opportunistically
//     warms the plane cache with the +1/-1/+2/-2 neighbour planes (the
//     Python SliceReadWorker offsets), skipping out-of-extent and
//     already-cached planes. Prefetch is worker-thread-only cache warming:
//     it never emits sink results, goes through the same LRU put path, and
//     is abandoned the moment new work (submit/set_source) or shutdown
//     arrives. Sample (time) slices are never prefetched; the pass can be
//     disabled with set_prefetch_enabled(false).

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/viz/seismic_volume.hpp>

namespace pwb::seismic_viewer {

struct SliceResult {
    pwb::viz::VolumeAxis axis{pwb::viz::VolumeAxis::inline_};
    std::int64_t index{0};
    std::uint64_t epoch{0};
    std::uint64_t generation{0};

    bool ok{false};       // plane read succeeded
    bool degenerate{false}; // frozen IndexedSlice degeneracy (constant/all-invalid)
    std::int64_t rows{0};
    std::int64_t cols{0};
    std::vector<float> values;   // owned plane, canonical row-major (rows*cols)
    std::vector<std::uint8_t> indexed; // map_slice_to_indexed8 output (worker thread)
    double value_min{0.0};       // stretch actually applied
    double value_max{0.0};
    std::string diagnostic;      // non-empty on failure/degeneracy; hosts show it
};

struct ControllerStats {
    std::uint64_t submitted{0};          // submit() calls
    std::uint64_t coalesced{0};          // queued requests replaced by a newer one
    std::uint64_t executed{0};           // read_slice attempts (cache misses)
    std::uint64_t cache_hits{0};
    std::uint64_t cache_misses{0};       // requests that executed a read
    std::uint64_t delivered{0};          // sink calls with fresh results
    std::uint64_t discarded_stale{0};    // computed but superseded/old-epoch
    std::uint64_t read_failures{0};      // read_slice returned 0
    std::uint64_t degenerate_results{0};
    std::size_t cache_planes_peak{0};    // high-water mark of cached planes
    std::uint64_t prefetch_reads{0};     // prefetch plane reads (cache warming)
    std::uint64_t prefetch_abandoned{0}; // prefetch passes cut short by new work/shutdown
};

class SliceController {
public:
    using ResultSink = std::function<void(const SliceResult&)>;

    // `source` may be nullptr (empty state). `cache_planes` must be >= 1.
    explicit SliceController(std::shared_ptr<pwb::viz::ISeismicVolume> source,
                             std::size_t cache_planes, ResultSink sink);
    ~SliceController();

    SliceController(const SliceController&) = delete;
    SliceController& operator=(const SliceController&) = delete;

    // Swaps the source: bumps the epoch, clears the queue and the plane cache.
    // Thread-safe vs submit(); never blocks on I/O (the old source is
    // released on the worker thread).
    void set_source(std::shared_ptr<pwb::viz::ISeismicVolume> source);

    // Queues a slice request (coalescing per the frozen contract). Returns
    // immediately. Requests against a null/empty source produce a failed
    // result with a diagnostic instead of blocking or throwing.
    void submit(pwb::viz::VolumeAxis axis, std::int64_t index,
                std::optional<std::pair<double, double>> value_range);

    // Stops the worker and disables the sink; idempotent. The destructor
    // calls it, so hosts normally never need to.
    void request_shutdown();

    // Toggles opportunistic neighbour prefetch (default on, mirroring the
    // Python SliceReadWorker). With prefetch off the controller behaves
    // exactly as if the prefetch pass did not exist. Thread-safe vs
    // submit(); never blocks on I/O.
    void set_prefetch_enabled(bool enabled);
    [[nodiscard]] bool prefetch_enabled() const;

    [[nodiscard]] ControllerStats stats() const;
    [[nodiscard]] std::uint64_t epoch() const;
    [[nodiscard]] std::size_t cache_size() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace pwb::seismic_viewer
