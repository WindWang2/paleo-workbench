# CONV-12 oracle-conformance test: replays the frozen Python oracle cases
# against pwb_geomodel (single target geomodel.volume per the swarm plan).

if(NOT TARGET Pwb::Domain)
    message(FATAL_ERROR
        "geomodel.volume needs Pwb::Domain for JSON decoding "
        "(configure with -DPWB_BUILD_DATA=ON)")
endif()

add_executable(geomodel.volume geomodel_volume_test.cpp)
target_compile_features(geomodel.volume PRIVATE cxx_std_20)
target_link_libraries(geomodel.volume PRIVATE Pwb::GeoModel Pwb::Domain)
target_compile_definitions(geomodel.volume PRIVATE
    PWB_GEOMODEL_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/geomodel_volume_oracle.json")
add_test(NAME geomodel.volume COMMAND geomodel.volume)
set_tests_properties(geomodel.volume PROPERTIES TIMEOUT 120)

# BEGIN CONV-22 — geomodel contract oracle conformance: replays the frozen
# domain/QC/export/advisor/lithology/builders cases against the contract
# layer (single target geomodel.contracts).
if(PWB_BUILD_CONV_22)
    add_executable(geomodel.contracts geomodel_contracts_test.cpp)
    target_compile_features(geomodel.contracts PRIVATE cxx_std_20)
    target_link_libraries(geomodel.contracts PRIVATE Pwb::GeoModel Pwb::Domain)
    target_compile_definitions(geomodel.contracts PRIVATE
        PWB_CONTRACTS_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/geomodel_contract_oracle.json")
    add_test(NAME geomodel.contracts COMMAND geomodel.contracts)
    set_tests_properties(geomodel.contracts PROPERTIES TIMEOUT 120)
endif()
# END CONV-22
