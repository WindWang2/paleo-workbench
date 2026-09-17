#include <pwb/geomodel/mesh_qc.hpp>

#include <algorithm>
#include <cmath>
#include <numeric>
#include <vector>

namespace pwb::geomodel {

double tri_degenerate_fraction(
    const std::vector<Vec3>& verts,
    const std::vector<std::array<std::int64_t, 3>>& faces) {
    if (faces.empty()) {
        return 0.0;
    }
    std::int64_t degenerate = 0;
    for (const auto& f : faces) {
        const Vec3& p0 = verts[static_cast<std::size_t>(f[0])];
        const Vec3& p1 = verts[static_cast<std::size_t>(f[1])];
        const Vec3& p2 = verts[static_cast<std::size_t>(f[2])];
        const double a = std::sqrt((p1[0] - p0[0]) * (p1[0] - p0[0]) +
                                   (p1[1] - p0[1]) * (p1[1] - p0[1]) +
                                   (p1[2] - p0[2]) * (p1[2] - p0[2]));
        const double b = std::sqrt((p2[0] - p1[0]) * (p2[0] - p1[0]) +
                                   (p2[1] - p1[1]) * (p2[1] - p1[1]) +
                                   (p2[2] - p1[2]) * (p2[2] - p1[2]));
        const double c = std::sqrt((p0[0] - p2[0]) * (p0[0] - p2[0]) +
                                   (p0[1] - p2[1]) * (p0[1] - p2[1]) +
                                   (p0[2] - p2[2]) * (p0[2] - p2[2]));
        const double longest = std::max({a, b, c});
        const double shortest = std::min({a, b, c});
        if (shortest <= 1e-12 * std::max(longest, 1e-12)) {
            ++degenerate;
        }
    }
    return static_cast<double>(degenerate) / static_cast<double>(faces.size());
}

EdgeManifoldStats edge_manifold_stats(
    const std::vector<std::array<std::int64_t, 3>>& faces) {
    EdgeManifoldStats stats;
    if (faces.empty()) {
        return stats;
    }
    std::int64_t max_hi = 0;
    for (const auto& f : faces) {
        max_hi = std::max({max_hi, f[0], f[1], f[2]});
    }
    std::vector<std::int64_t> keys;
    keys.reserve(faces.size() * 3);
    for (const auto& f : faces) {
        const std::int64_t tri[3] = {f[0], f[1], f[2]};
        for (int e = 0; e < 3; ++e) {
            const std::int64_t a = tri[e];
            const std::int64_t b = tri[(e + 1) % 3];
            keys.push_back(std::min(a, b) * (max_hi + 1) + std::max(a, b));
        }
    }
    std::sort(keys.begin(), keys.end());
    for (std::size_t k = 0; k < keys.size();) {
        std::size_t run = 1;
        while (k + run < keys.size() && keys[k + run] == keys[k]) {
            ++run;
        }
        if (run == 1) {
            ++stats.boundary;
        } else if (run > 2) {
            ++stats.nonmanifold;
        }
        k += run;
    }
    return stats;
}

int connected_components(std::size_t vertex_count,
                         const std::vector<std::array<std::int64_t, 3>>& faces) {
    if (faces.empty()) {
        return 0;
    }
    // scipy csgraph parity: every vertex (referenced or not) is a node of
    // the graph, so isolated vertices count as their own components.
    std::vector<std::size_t> parent(vertex_count);
    std::iota(parent.begin(), parent.end(), 0);
    std::vector<std::size_t> stack;
    auto find = [&](std::size_t x) {
        while (parent[x] != x) {
            stack.clear();
            while (parent[x] != x) {
                stack.push_back(x);
                x = parent[x];
            }
            for (const std::size_t node : stack) {
                parent[node] = x;
            }
            return x;
        }
        return x;
    };
    auto unite = [&](std::size_t a, std::size_t b) {
        const std::size_t ra = find(a);
        const std::size_t rb = find(b);
        if (ra != rb) {
            parent[rb] = ra;
        }
    };
    for (const auto& f : faces) {
        unite(static_cast<std::size_t>(f[0]), static_cast<std::size_t>(f[1]));
        unite(static_cast<std::size_t>(f[1]), static_cast<std::size_t>(f[2]));
    }
    std::vector<std::size_t> roots;
    for (std::size_t v = 0; v < vertex_count; ++v) {
        roots.push_back(find(v));
    }
    std::sort(roots.begin(), roots.end());
    return static_cast<int>(
        std::unique(roots.begin(), roots.end()) - roots.begin());
}

}  // namespace pwb::geomodel
