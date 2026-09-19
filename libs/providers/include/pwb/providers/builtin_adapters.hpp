// Adapter seam: real mapping_kernel domain objects become the typed SDK
// inputs (TYPED_REFS vocabulary) without coupling the SDK core to the
// kernel. Kept out of builtin.hpp so provider hosts that do not use the
// kernel never include it.
#pragma once

#include <pwb/mapping/extract.hpp>
#include <pwb/providers/registry.hpp>

#include <string>

namespace pwb::providers {

// A mapping_kernel FactorDataset becomes the typed "GeologicalFactorDataset"
// input the SDK vocabulary declares (payload is the dataset's JSON form).
TypedInput make_dataset_typed_input(const std::string& name,
                                    const pwb::mapping::FactorDataset& dataset);

}  // namespace pwb::providers
