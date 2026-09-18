# CONV-28 science_service — native science service layer over the frozen
# Qt-free kernels: factor interpolation pipeline, factor layer products,
# curve operations, DTW log match, factor fusion, geomodel build/section/
# fault/export. Typed + cancelable (stage-boundary stop tokens) + resource
# guarded + provenance/fingerprint envelopes; IAlgorithm adapters run the
# services on pwb::workflow::TaskRuntime with any IResultPublisherV1.
#
# Composition only — no numeric algorithm lives here (see the reuse map in
# docs/development/cpp-science-closure/ledger.md).
add_library(pwb_science_service STATIC
    src/envelope.cpp
    src/payload.cpp
    src/factor_service.cpp
    src/facies_service.cpp
    src/well_service.cpp
    src/fusion_service.cpp
    src/geomodel_service.cpp
    src/publisher.cpp
    src/registry.cpp)
add_library(Pwb::ScienceService ALIAS pwb_science_service)
target_include_directories(pwb_science_service PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_science_service PUBLIC cxx_std_20)
# Pwb::Science  — IAlgorithm/registry/publisher SDK (add_subdirectory'd by
#                 the CONV-28 root block when science_suite didn't add it).
# Pwb::Workflow — TaskRuntime (test/E2E consumers; registry.cpp references
#                 the header only, keep PRIVATE).
# Kernel closure: MappingKernel (CONV-03/05/10/17/18 sources on), WellScience,
#                 FactorHost, FactorFusion, GeoModel (CONV-22 contracts on).
target_link_libraries(pwb_science_service
    PUBLIC
        Pwb::Science
        Pwb::MappingKernel
        Pwb::WellScience
        Pwb::FactorHost
        Pwb::FactorFusion
        Pwb::GeoModel
        Pwb::Domain
    PRIVATE
        Pwb::Workflow)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(pwb_science_service PRIVATE -Wall -Wextra)
elseif(MSVC)
    target_compile_options(pwb_science_service PRIVATE /utf-8 /W4 /permissive-)
endif()

if(BUILD_TESTING)
    add_subdirectory(science_service_tests)
endif()
