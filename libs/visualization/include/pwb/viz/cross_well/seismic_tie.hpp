#pragma once

// VIZ-B — depth/TWT checkshot tie tables.
// Verbatim port of geoviz_cross_well/seismic_tie.py. Interpolation is
// np.interp semantics via viz::well_tie::WellTieCalibration (clamp at
// table ends); each per-well table is depth-sorted ascending on load.

#include <optional>
#include <string>
#include <vector>

#include <pwb/viz/well_tie/calibration.hpp>

namespace pwb::viz::cross_well {

struct CheckshotTable {
    std::string well_name;
    std::vector<double> depths_m;  // ascending
    std::vector<double> twt_ms;

    [[nodiscard]] double interpolate_twt(double depth) const {
        return well_tie::WellTieCalibration(depths_m, twt_ms).depth_to_twt(
            depth);
    }
    [[nodiscard]] double interpolate_depth(double twt) const {
        return well_tie::WellTieCalibration(depths_m, twt_ms).twt_to_depth(
            twt);
    }
};

class SeismicTie {
  public:
    // CSV: depth,twt[,well] — skips empty/'#-prefixed rows; a row whose
    // first cell is depth_m/depth/md is a header (also detects a well
    // column by any header cell containing "well"); rows failing float
    // parse are skipped; per-well samples are depth-sorted ascending and
    // the table replaces any same-name table. Returns false when the
    // file cannot be read.
    bool load_csv(const std::string& path,
                  const std::optional<std::string>& well_name = {});

    [[nodiscard]] std::optional<double> depth_to_twt(const std::string& well,
                                                     double depth) const;
    [[nodiscard]] std::optional<double> twt_to_depth(const std::string& well,
                                                     double twt) const;
    [[nodiscard]] bool has_well(const std::string& well) const;
    [[nodiscard]] const CheckshotTable* table_for_well(
        const std::string& well) const;
    [[nodiscard]] std::vector<std::string> well_names() const;  // insertion
    void clear();

  private:
    std::vector<CheckshotTable> tables_;  // insertion order (dict parity)
};

}  // namespace pwb::viz::cross_well
