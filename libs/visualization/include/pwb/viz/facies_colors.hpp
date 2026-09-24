#pragma once

// VIZ-A — the vendored facies color table (frozen Python FACIES_COLORS,
// order significant for longest-substring tie-breaks). Lives in the core
// (Qt-free, WLE-free) visualization lib so non-WLE consumers — e.g. the
// ws2「参考」岩性图例 — read the SAME vocabulary the well-log interval
// renderer uses; single definition, no forks.

#include <string>
#include <utility>
#include <vector>

namespace pwb::viz {

const std::vector<std::pair<std::string, std::string>>& facies_colors();

}  // namespace pwb::viz
