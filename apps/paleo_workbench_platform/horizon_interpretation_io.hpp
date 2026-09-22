#pragma once

#include <filesystem>
#include <pwb/domain/json.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::app::joint_analysis {
struct HorizonInterpretation {
    pwb::ui_workers::Grid2D z;
    pwb::domain::Json descriptor;
};
// Python-compatible NPZ: z float32 matrix + __descriptor__ uint8 JSON.
HorizonInterpretation read_horizon_interpretation(const std::filesystem::path& path);
void write_horizon_interpretation(const std::filesystem::path& path,
                                  const HorizonInterpretation& artifact);
}
