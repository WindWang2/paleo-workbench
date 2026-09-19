#include <pwb/ui_pages_preview/media_time.hpp>

#include <cstdio>

namespace pwb::ui_pages_preview {

namespace {

// Python // and % are floor semantics; C++ / % truncate toward zero. A
// negative position must reproduce e.g. _ms(-500) == "-1:59".
long long floor_div(long long a, long long b) {
    const long long q = a / b;
    return (a % b != 0 && ((a < 0) != (b < 0))) ? q - 1 : q;
}

}  // namespace

std::string media_ms_to_mmss(long long ms) {
    const long long s = floor_div(ms, 1000);
    const long long m = floor_div(s, 60);
    const long long sec = s - m * 60;  // Python s % 60, always in [0, 59]
    char buf[16];
    std::snprintf(buf, sizeof(buf), "%02lld:%02lld", m, sec);
    return buf;
}

std::string media_time_label(long long position_ms, long long duration_ms) {
    return media_ms_to_mmss(position_ms) + " / " + media_ms_to_mmss(duration_ms);
}

}  // namespace pwb::ui_pages_preview
