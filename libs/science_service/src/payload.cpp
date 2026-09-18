// pwb::science_service — payload source implementations (CONV-28).

#include <pwb/science_service/payload.hpp>

#include <utility>

#include "support.hpp"

namespace pwb::science_service {

const char* Payload::kind_name() const noexcept {
    switch (kind) {
    case Kind::table:
        return "table";
    case Kind::well_log:
        return "well_log";
    case Kind::grid:
        return "grid";
    case Kind::bytes:
        return "bytes";
    }
    return "?";
}

science::Result<Payload> InMemoryPayloadSource::resolve(
    const science::VersionRef& ref) {
    const auto it = payloads_.find(ref.version_id);
    if (it == payloads_.end()) {
        return detail::make_error(
            "payload.unresolved",
            "no payload registered for version_id '" + ref.version_id + "'");
    }
    return it->second;
}

void InMemoryPayloadSource::put_table(const std::string& version_id,
                                      Json records) {
    Payload p;
    p.kind = Payload::Kind::table;
    p.table = std::move(records);
    payloads_[version_id] = std::move(p);
}

void InMemoryPayloadSource::put_well_log(const std::string& version_id,
                                         std::vector<double> depth,
                                         std::vector<double> values,
                                         std::optional<std::string> unit,
                                         std::optional<std::string> axis_unit) {
    Payload p;
    p.kind = Payload::Kind::well_log;
    p.depth = std::move(depth);
    p.values = std::move(values);
    p.unit = std::move(unit);
    p.axis_unit = std::move(axis_unit);
    payloads_[version_id] = std::move(p);
}

void InMemoryPayloadSource::put_grid(const std::string& version_id,
                                     pwb::mapping::FactorGrid grid) {
    Payload p;
    p.kind = Payload::Kind::grid;
    p.grid = std::move(grid);
    payloads_[version_id] = std::move(p);
}

void InMemoryPayloadSource::put_bytes(const std::string& version_id,
                                      std::string data, std::string media_type) {
    Payload p;
    p.kind = Payload::Kind::bytes;
    p.bytes = std::move(data);
    p.media_type = std::move(media_type);
    payloads_[version_id] = std::move(p);
}

science::Result<Payload> UnavailablePayloadSource::resolve(
    const science::VersionRef& ref) {
    return detail::make_error(
        "payload.source_unavailable",
        "no payload source is wired on this host; cannot resolve version_id '"
            + ref.version_id + "'");
}

}  // namespace pwb::science_service
