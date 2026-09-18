# CONV-12 geomodel — volume / thickness / section geometric kernels ported
# from paleo_workbench/viz (formation_volume, horizon_sculpting,
# fault_displacement, viz/geomodel builders+measurements+section+qc numeric
# cores). Qt-free, Python-free, numpy-free. Frozen against the Python oracle.
add_library(pwb_geomodel STATIC
    src/volume.cpp
    src/sculpting.cpp
    src/fault_displacement.cpp
    src/builders.cpp
    src/measurements.cpp
    src/section.cpp
    src/mesh_qc.cpp)
add_library(Pwb::GeoModel ALIAS pwb_geomodel)
target_include_directories(pwb_geomodel PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_geomodel PUBLIC cxx_std_20)

# BEGIN CONV-22 — geomodel contract/writer cores: domain object contracts
# (meta/from_meta/ModelAssembly), QC ladder + export gate, the V2 exporters
# (flac3d/abaqus/OBJ/STL/VTP) + read-back validators + provenance sidecars,
# advisor rules and lithology tables. Reuses the ingest XML scanner and
# py_compat instead of duplicating CPython/expat semantics. Frozen against
# geomodel_contract_oracle.json.
if(PWB_BUILD_CONV_22)
    target_sources(pwb_geomodel PRIVATE
        src/domain_contract.cpp
        src/qc_contract.cpp
        src/export_contract.cpp
        src/advisor_contract.cpp)
    # Pwb::Domain/Pwb::Ingest are forward references: libs/geomodel is added
    # by the CONV-12 block before CONV-19's, but CMake resolves link targets
    # at generate time (the root CONV-22 block turns both on).
    # PUBLIC: the contract headers expose pwb::domain::Json types.
    target_link_libraries(pwb_geomodel PUBLIC Pwb::Domain Pwb::Ingest)
endif()
# END CONV-22

if(BUILD_TESTING)
    add_subdirectory(geomodel_tests)
endif()
