#include "pwb/ui_workstation/log_buffer.hpp"

namespace pwb::ui_workstation {

std::string format_log_line(const std::string& hh_mm_ss,
                            const std::string& level,
                            const std::string& logger_name,
                            const std::string& message) {
    // "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    std::string lvl = level;
    if (lvl.size() < 7) lvl.append(7 - lvl.size(), ' ');
    return hh_mm_ss + " " + lvl + " " + logger_name + ": " + message;
}

}  // namespace pwb::ui_workstation
