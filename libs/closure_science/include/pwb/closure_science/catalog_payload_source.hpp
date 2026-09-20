// pwb::closure_science — catalog-backed IPayloadSource for the science
// services (the CONV-28 host-injected seam, closed with the real reader).
//
// Version payload decoding follows the recorded facts on the DataVersion
// row (format + metadata.payload_kind), never guesses:
//   payload_kind "well_log"  -> {depth[], values[], unit, axis_unit} JSON
//   payload_kind "grid"      -> mapping grid JSON (mapping-kernel codec)
//   JSON array / {"records": [...]} -> table payload
//   anything else            -> bytes payload with the recorded format
// A missing version, trashed version, unreadable payload or undecodable
// document is an explicit AlgorithmError — never an empty payload (an empty
// table is a legitimate payload, a lookup miss is not).
#pragma once

#include <pwb/catalog/models.hpp>
#include <pwb/science/outcome.hpp>
#include <pwb/science_service/payload.hpp>

#include <filesystem>
#include <string>

namespace pwb::closure_science {

class CatalogPayloadSource : public pwb::science_service::IPayloadSource {
public:
    // `project_dir` joins managed version paths ("<name>.artifacts/..."
    // first segment, recorded absolute, naive project-relative — the same
    // ladder the catalog's own probe uses).
    CatalogPayloadSource(const catalog::CatalogDocument& document,
                         std::filesystem::path project_dir);

    [[nodiscard]] pwb::science::Result<pwb::science_service::Payload> resolve(
        const pwb::science::VersionRef& ref) override;

private:
    const catalog::CatalogDocument& document_;
    std::filesystem::path project_dir_;
};

}  // namespace pwb::closure_science
