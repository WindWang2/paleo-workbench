#pragma once

// pwb::science_service — input payload vocabulary + the host-injected source
// seam (CONV-28).
//
// The pwb::science SDK request vocabulary carries catalog VersionRefs; it
// deliberately never opens the catalog. Services with structured inputs
// (well tables, curves, factor grids) resolve those refs into typed payloads
// through IPayloadSource, injected by the host:
//   * the C++ platform hosts an adapter over the data line's catalog reader;
//   * tests / workflow adapters run an in-memory source over DTO dicts.
// The seam mirrors the resolver-injection pattern frozen in
// pwb::factor_host::evaluation (engine seams) and workflow_graph evidence
// (catalog resolver seam). Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/mapping/interpolator.hpp>
#include <pwb/science/outcome.hpp>
#include <pwb/science/types.hpp>

#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace pwb::science_service {

using pwb::domain::Json;

// One resolved input. Exactly one field is populated; `kind_name` reports
// which, using the science SDK PortKind vocabulary.
struct Payload {
    enum class Kind : std::uint8_t { table, well_log, grid, bytes };
    Kind kind = Kind::table;

    // table — JSON array of record objects (well table rows, sample rows).
    Json table = Json::array();
    // well_log — depth/value curves with optional units.
    std::vector<double> depth;
    std::vector<double> values;
    std::optional<std::string> unit;         // curve value unit ("" = unitless)
    std::optional<std::string> axis_unit;    // depth axis unit (m/ft/unknown)
    // grid — mapping-kernel grid envelope (CONV-18 codec shape) pre-parsed.
    std::optional<pwb::mapping::FactorGrid> grid;
    // bytes — opaque artifact payload (e.g. an export document).
    std::string bytes;
    std::string media_type;

    [[nodiscard]] const char* kind_name() const noexcept;
};

class IPayloadSource {
public:
    virtual ~IPayloadSource() = default;
    // Resolve one catalog-like version ref. A missing/unreadable ref must
    // return an AlgorithmError (never throw, never return an empty payload
    // silently — an empty table is a legitimate payload, not a lookup miss).
    [[nodiscard]] virtual science::Result<Payload> resolve(
        const science::VersionRef& ref) = 0;
};

// In-memory source over DTO dicts: the "catalog-like input DTO" provider for
// tests, workflow adapters and the local-persistence demo path. Later
// registrations win (deterministic overwrite, no versioning here).
class InMemoryPayloadSource : public IPayloadSource {
public:
    science::Result<Payload> resolve(const science::VersionRef& ref) override;

    void put_table(const std::string& version_id, Json records);
    void put_well_log(const std::string& version_id, std::vector<double> depth,
                      std::vector<double> values,
                      std::optional<std::string> unit = std::nullopt,
                      std::optional<std::string> axis_unit = std::nullopt);
    void put_grid(const std::string& version_id, pwb::mapping::FactorGrid grid);
    void put_bytes(const std::string& version_id, std::string data,
                   std::string media_type);

private:
    std::map<std::string, Payload> payloads_;
};

// A source that always fails with one stable diagnostic — the fail-closed
// placeholder when a host wires services without catalog access.
class UnavailablePayloadSource : public IPayloadSource {
public:
    science::Result<Payload> resolve(const science::VersionRef& ref) override;
};

}  // namespace pwb::science_service
