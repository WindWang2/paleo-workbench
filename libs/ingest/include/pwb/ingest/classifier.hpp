// Resource classification port of paleo_workbench/resources/classifier.py
// plus the io_registry tables (labels / preferred import extensions / roles).
#pragma once

#include <map>
#include <string>
#include <vector>

namespace pwb::ingest {

struct Classification {
    std::string type;
    std::string format;
    std::string status;
};

// classify_path: filename/extension heuristics only (path separator '/').
Classification classify_path(std::string_view path);

// classify_import_path: XML claims well_head / well_log from CONTENT via the
// bounded extractors; anything else (and any parse failure) falls back to
// classify_path. `content` is the file bytes for .xml paths.
Classification classify_import_path(std::string_view path, std::string_view content);

// io_registry tables (frozen from Python in the oracle constants group).
const std::map<std::string, std::string>& type_labels();
bool is_preferred_import_extension(std::string_view ext);
const std::map<std::string, std::string>& role_by_type();

}  // namespace pwb::ingest
