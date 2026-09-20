#pragma once

// VIZ-D slice export core — Qt-free writers for the two data formats of the
// frozen Python export (geo-viz-engine@08851951, seismic_view.py:1880
// _export_slice):
//   * .npy — np.save(path, data): numpy format 1.0, '<f4' little-endian
//     float32, C order (fortran_order False), 64-byte aligned header dict.
//   * .csv — np.savetxt(path, data, delimiter=",", fmt="%.6f"): comma
//     separated, "%.6f" values, NO header row, "\n" line endings.
// The third frozen format (png, the profile widget grab) is the widget's
// export_slice — a real display render, not a data writer (see
// seismic_slice_widget.hpp).
//
// Orientation contract: callers pass the plane in DISPLAY orientation —
// rows = vertical image axis (the sample axis on section views), cols =
// horizontal image axis — so what was exported is what was on screen. The
// widget maps its canonical plane through plane_flat_index before calling.
//
// Nothing here touches Qt.

#include <cstdint>
#include <span>
#include <string>

namespace pwb::seismic_viewer::slice_export {

// NumPy 1.0 .npy: \x93NUMPY\x01\x00 + uint16 LE header length + space-padded
// dict `{'descr': '<f4', 'fortran_order': False, 'shape': (rows, cols), }`
// terminated by '\n', total preamble padded to a multiple of 64 bytes
// (np.save layout), then rows*cols little-endian float32 row-major.
[[nodiscard]] bool write_npy(const std::string& path, std::span<const float> data,
                             std::int64_t rows, std::int64_t cols, std::string& error);

// np.savetxt parity: "%.6f", comma delimiter, no header, '\n' endings.
[[nodiscard]] bool write_csv(const std::string& path, std::span<const float> data,
                             std::int64_t rows, std::int64_t cols, std::string& error);

} // namespace pwb::seismic_viewer::slice_export
