#include <pwb/seismic_io/segy_reader.hpp>

#include <string>
#include <vector>

#include <pwb/seismic_io/segy_layout.hpp>
#include <pwb/seismic_io/tile_read.hpp>

namespace pwb::seismic_io {

std::optional<SegyVolume> read_segy(const std::filesystem::path& file,
                                    std::string* error) {
    // Composition of the frozen pipeline: header-only inspection (grid
    // discovery, validation, dt, bin grid) followed by one full-extent
    // window gather. Error strings and their precedence are the historical
    // read_segy ones — guarded by seismic_io.segy_read.
    const std::optional<SegyLayout> layout = inspect_segy(file, error);
    if (!layout.has_value()) {
        return std::nullopt;
    }
    const VolumeDescriptor& descriptor = layout->descriptor;

    WindowSpec full;
    full.origin = {0, 0, 0};
    full.extent = {descriptor.ni, descriptor.nc, descriptor.ns};

    SegyVolume volume;
    volume.ni = descriptor.ni;
    volume.nc = descriptor.nc;
    volume.ns = descriptor.ns;
    volume.iline_start = descriptor.iline_start;
    volume.xline_start = descriptor.xline_start;
    volume.iline_step = descriptor.iline_step;
    volume.xline_step = descriptor.xline_step;
    volume.dt_ms = descriptor.sample_step;
    volume.unit = descriptor.sample_unit;
    volume.samples.resize(static_cast<std::size_t>(descriptor.elements()));

    const CancelFlag no_cancel;
    if (read_segy_window(*layout, full, volume.samples, no_cancel, error)
        != volume.samples.size()) {
        return std::nullopt;
    }
    return volume;
}

}  // namespace pwb::seismic_io
