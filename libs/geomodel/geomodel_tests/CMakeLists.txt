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
