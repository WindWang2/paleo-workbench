#include <pwb/ui_canvas/vector_lod.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>

namespace pwb::ui_canvas::vector_lod {

double scale_bucket_mupp(double mupp) {
    if (mupp <= 0.0 || !std::isfinite(mupp)) return 0.0;
    return std::pow(2.0, std::floor(std::log2(mupp)));
}

double tolerance_area(double mupp, double pixel_tolerance) {
    if (mupp <= 0.0) return 0.0;
    const double edge = pixel_tolerance * mupp;
    return edge * edge;
}

namespace {

// _anchor_mask — per-part morphology anchors: endpoints, VISIBLE
// inflections (cross-sign flips where both adjacent turns have
// |cross| >= 2*tolerance), and x/y extrema (first occurrence on ties).
std::vector<bool> anchor_mask(const std::vector<double>& xs,
                              const std::vector<double>& ys,
                              const std::vector<std::size_t>& starts,
                              const std::vector<std::size_t>& ends,
                              const std::vector<bool>& is_ring,
                              double tolerance) {
    const std::size_t n = xs.size();
    std::vector<bool> anchors(n, false);
    for (std::size_t part = 0; part < starts.size(); ++part) {
        const std::size_t s = starts[part];
        const std::size_t e = ends[part];
        if (e - s < 3) {
            for (std::size_t i = s; i < e; ++i) anchors[i] = true;
            continue;
        }
        anchors[s] = true;
        anchors[e - 1] = true;
        // Closed ring: last vertex duplicates the first — the candidate
        // domain drops it (ax = px[:-1]); open parts keep all vertices.
        const std::size_t ax_len = is_ring[part] ? (e - s - 1) : (e - s);
        // local[i] <-> anchors[s+1+i] <-> ax[i+1].
        const std::size_t local_size = e - s - 2;
        if (local_size >= 3) {
            const double* ax = xs.data() + s;
            const double* ay = ys.data() + s;
            // cross[t] = turn at ax[t+1], t in 0..ax_len-3.
            if (ax_len >= 3) {
                std::vector<double> cross(ax_len - 2);
                for (std::size_t t = 0; t + 2 < ax_len; ++t) {
                    const double d1x = ax[t + 1] - ax[t];
                    const double d1y = ay[t + 1] - ay[t];
                    const double d2x = ax[t + 2] - ax[t + 1];
                    const double d2y = ay[t + 2] - ay[t + 1];
                    cross[t] = d1x * d2y - d1y * d2x;
                }
                const double threshold = 2.0 * tolerance;
                // turns[t] <-> ax[t+2] <-> local[t+1].
                for (std::size_t t = 0; t + 1 < cross.size(); ++t) {
                    const bool visible0 =
                        std::abs(cross[t]) >= threshold;
                    const bool visible1 =
                        std::abs(cross[t + 1]) >= threshold;
                    if (cross[t] * cross[t + 1] < 0.0 && visible0 &&
                        visible1) {
                        anchors[s + 1 + (t + 1)] = true;
                    }
                }
                // Coordinate extrema of arr[1:-1] — first occurrence on
                // ties (np.argmin/argmax parity).
                for (const double* arr : {ax, ay}) {
                    if (ax_len >= 2) {
                        std::size_t lo = 0, hi = 0;
                        for (std::size_t i = 1; i + 1 < ax_len; ++i) {
                            if (arr[i] < arr[lo + 1]) lo = i - 1;
                            if (arr[i] > arr[hi + 1]) hi = i - 1;
                        }
                        // lo/hi are indices into arr[1:-1]; map back:
                        // arr[1:-1][m] <-> ax[m+1] <-> local[m].
                        anchors[s + 1 + lo] = true;
                        anchors[s + 1 + hi] = true;
                    }
                }
            }
        }
    }
    return anchors;
}

}  // namespace

std::vector<bool> visvalingam_keep_mask(
    const std::vector<double>& xs, const std::vector<double>& ys,
    const std::vector<std::size_t>& starts,
    const std::vector<bool>& is_ring, double tolerance) {
    const std::size_t n = xs.size();
    if (n == 0 || tolerance <= 0.0) {
        return std::vector<bool>(n, true);
    }
    std::vector<std::size_t> ends(starts.begin() + 1, starts.end());
    ends.push_back(n);
    const std::vector<bool> anchors =
        anchor_mask(xs, ys, starts, ends, is_ring, tolerance);

    std::vector<bool> keep(n, true);
    // pending = ~anchors & interior (part boundaries are anchors anyway,
    // but the Python mask applies interior_pos explicitly).
    std::vector<bool> pending(n, false);
    std::vector<std::size_t> part_of(n, 0);
    {
        std::size_t part = 0;
        for (std::size_t i = 0; i < n; ++i) {
            while (part + 1 < starts.size() && starts[part + 1] <= i) {
                ++part;
            }
            part_of[i] = part;
            const bool interior =
                i > starts[part] && i + 1 < ends[part];
            pending[i] = !anchors[i] && interior;
        }
    }

    std::vector<std::size_t> idx(n);
    std::iota(idx.begin(), idx.end(), 0);
    std::vector<std::size_t> prev_kept(n), nxt(n);
    std::vector<double> areas(n);
    std::vector<bool> below(n), remove(n), left_below(n), right_below(n);

    for (;;) {
        bool any_pending = false;
        for (std::size_t i = 0; i < n; ++i) any_pending |= pending[i];
        if (!any_pending) break;

        // prev_kept[i] = greatest kept index < i (nearest surviving
        // neighbour left); nxt[i] = smallest kept index > i.
        {
            // run_max = maximum.accumulate(where(keep, idx, -1));
            // prev_kept shifts it right with a -1 front.
            std::vector<std::size_t> run_max(n, 0);
            std::vector<bool> run_have(n, false);
            std::size_t accum = 0;
            bool have = false;
            for (std::size_t i = 0; i < n; ++i) {
                if (keep[i] && (!have || i > accum)) {
                    accum = i;
                    have = true;
                }
                run_max[i] = accum;
                run_have[i] = have;
            }
            for (std::size_t i = 0; i < n; ++i) {
                prev_kept[i] = (i > 0 && run_have[i - 1])
                                   ? run_max[i - 1]
                                   : std::numeric_limits<std::size_t>::max();
            }
            // nxt via reverse running min of kept idx, shifted left.
            std::vector<std::size_t> run_min(n, n);
            std::size_t rmin = n;
            for (std::size_t i = n; i-- > 0;) {
                if (keep[i] && i < rmin) rmin = i;
                run_min[i] = rmin;
            }
            for (std::size_t i = 0; i < n; ++i) {
                nxt[i] = (i + 1 < n) ? run_min[i + 1] : n;
            }
        }
        const std::size_t NPOS = std::numeric_limits<std::size_t>::max();
        std::vector<bool> has_both(n);
        for (std::size_t i = 0; i < n; ++i) {
            has_both[i] = (prev_kept[i] != NPOS) && (nxt[i] < n);
        }
        for (std::size_t i = 0; i < n; ++i) {
            const std::size_t pv = has_both[i] ? prev_kept[i] : i;
            const std::size_t nx = has_both[i] ? nxt[i] : i;
            const double ax_ = xs[i] - xs[pv];
            const double ay_ = ys[i] - ys[pv];
            const double bx_ = xs[nx] - xs[pv];
            const double by_ = ys[nx] - ys[pv];
            areas[i] = std::abs(ax_ * by_ - ay_ * bx_) * 0.5;
            below[i] = pending[i] && has_both[i] && areas[i] < tolerance;
        }
        bool any_below = false;
        for (std::size_t i = 0; i < n; ++i) any_below |= below[i];
        if (!any_below) {
            // Nothing removable: all remaining candidates keep.
            for (std::size_t i = 0; i < n; ++i) {
                if (pending[i]) keep[i] = true;
            }
            break;
        }
        // np.roll wraparound: rolled_left[i] = areas[(i-1+n)%n].
        std::vector<double> rolled_left(n), rolled_right(n);
        for (std::size_t i = 0; i < n; ++i) {
            rolled_left[i] = areas[(i + n - 1) % n];
            rolled_right[i] = areas[(i + 1) % n];
        }
        for (std::size_t i = 0; i < n; ++i) {
            left_below[i] = i > 0 ? below[i - 1] : false;
            right_below[i] = i + 1 < n ? below[i + 1] : false;
        }
        // Consecutive-below bands drop only strict local minima (the
        // comparisons take >= so non-minima survive the round).
        for (std::size_t i = 0; i < n; ++i) {
            remove[i] = below[i] &&
                        !(left_below[i] && areas[i] >= rolled_left[i]) &&
                        !(right_below[i] && areas[i] >= rolled_right[i]);
        }
        bool any_remove = false;
        for (std::size_t i = 0; i < n; ++i) any_remove |= remove[i];
        if (!any_remove) {
            for (std::size_t i = 0; i < n; ++i) {
                remove[i] = below[i] && !(left_below[i] || right_below[i]);
            }
        }
        any_remove = false;
        for (std::size_t i = 0; i < n; ++i) any_remove |= remove[i];
        if (!any_remove) {
            // Equal-area tie band: thin every other vertex inside each
            // consecutive below-run (O(#runs) progress per round).
            std::vector<std::size_t> below_idx;
            for (std::size_t i = 0; i < n; ++i) {
                if (below[i]) below_idx.push_back(i);
            }
            for (std::size_t k = 0; k < below_idx.size(); ++k) {
                // pos_in_run: offset from this run's start.
                std::size_t run_start = 0;
                for (std::size_t j = k; j > 0; --j) {
                    if (below_idx[j] - below_idx[j - 1] > 1) {
                        run_start = j;
                        break;
                    }
                }
                const std::size_t pos = k - run_start;
                remove[below_idx[k]] = (pos % 2 == 0);
            }
        }
        for (std::size_t i = 0; i < n; ++i) {
            if (remove[i]) {
                keep[i] = false;
                pending[i] = false;
            }
        }
    }
    return keep;
}

}  // namespace pwb::ui_canvas::vector_lod
