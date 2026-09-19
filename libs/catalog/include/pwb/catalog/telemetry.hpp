// Catalog lifecycle telemetry (conv-31; catalog/telemetry.py parity, V8 M9).
//
// Append-only JSONL events under `<project>.artifacts/catalog/events.jsonl`
// — one {"event","at","detail"} object per line, written with Python
// json.dumps(ensure_ascii=False, sort_keys=True) formatting (compact keys
// order, ", "/": " separators) so lines are byte-comparable across the
// Python and C++ writers. Telemetry is best-effort by contract: a failure
// to persist never fails the maintenance operation it describes, and torn
// lines (crash mid-append) are skipped on read, never fatal.
#pragma once

#include "pwb/domain/json.hpp"

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

std::filesystem::path catalog_events_path(
    const std::filesystem::path& project_path);

// record_catalog_event parity: local-time "%Y-%m-%dT%H:%M:%S" stamp,
// best-effort append under a process-wide lock. Returns false when the
// line could not be persisted (never throws).
bool record_catalog_event(const std::filesystem::path& project_path,
                          const std::string& event,
                          const domain::Json& detail = domain::Json::object());

// read_catalog_events parity: newest last, optional event filter, optional
// tail limit; unreadable file / torn lines degrade to what is readable.
std::vector<domain::Json> read_catalog_events(
    const std::filesystem::path& project_path,
    const std::optional<std::string>& event = std::nullopt,
    std::optional<std::size_t> limit = std::nullopt);

}  // namespace pwb::catalog
