// SMI WellTops (.dat) 井分层 parser — faithful port of
// paleo_workbench/resources/well_tops_parser.py.
#pragma once

#include <optional>
#include <string>
#include <vector>

namespace pwb::ingest {

struct WellTop {
    std::string well_name;
    std::string top_name;
    double md = 0.0;
    std::optional<double> tvd;
};

// Parse the tolerant SMI format: '#' comment/header lines, whitespace
// separated columns `WellName Name MD X Y Z TVD Time(ms)`; blank lines,
// CRLF and short/garbage rows are skipped. Input is the decoded file text.
std::vector<WellTop> parse_well_tops_text(std::string_view text);

}  // namespace pwb::ingest
