// XML well deliveries: bounded recognition and extraction ports of
// paleo_workbench/resources/well_log_xml.py and well_location_xml.py.
#pragma once

#include <optional>
#include <string>
#include <vector>

namespace pwb::ingest {

// well_log_xml.is_well_log_xml — true only for explicit WITSML or well-log
// SpreadsheetML XML. raw bytes of the file; malformed input -> false.
bool is_well_log_xml_bytes(std::string_view bytes);

struct XMLWellLocation {
    std::string name;
    double x = 0.0;
    double y = 0.0;
    std::optional<double> z;
    std::string uwi;
    std::string source_crs;
};

// well_location_xml.extract_well_locations_xml — explicit well-coordinate
// records from generic/SpreadsheetML XML. Malformed input yields a
// user-facing warning ("XML 井位解析失败: {ExcClass}") and no records.
struct WellLocationExtraction {
    std::vector<XMLWellLocation> records;
    std::vector<std::string> warnings;
};
WellLocationExtraction extract_well_locations_xml_bytes(std::string_view bytes);

bool is_well_location_xml_bytes(std::string_view bytes);

// bounded-parse constants + recognition table (frozen in the oracle)
size_t well_location_max_records();
size_t well_log_xml_max_elements();
const std::vector<std::string>& well_log_spreadsheet_names();

}  // namespace pwb::ingest
