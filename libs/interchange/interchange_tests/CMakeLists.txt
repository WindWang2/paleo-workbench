add_executable(interchange.preflight preflight_test.cpp)
target_compile_features(interchange.preflight PRIVATE cxx_std_20)
target_link_libraries(interchange.preflight PRIVATE
    Pwb::Interchange Pwb::Domain)
target_compile_definitions(interchange.preflight PRIVATE
    PWB_INTERCHANGE_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/interchange_oracle.json")
add_test(NAME interchange.preflight COMMAND interchange.preflight)
set_tests_properties(interchange.preflight PROPERTIES TIMEOUT 120)

# CONV-14b: native zip container, atomic publication, package runtime and
# the FLAC3D/Abaqus model adapters, replayed against the archive oracle
# frozen by tools/oracle/generate_interchange_archive_fixtures.py.
# The model-adapter sections need the CONV-22 writers, so like the lib
# sources this target only builds when Pwb::GeoModel is part of the config.
if(TARGET Pwb::GeoModel)
    add_executable(interchange.archive archive_test.cpp)
    target_compile_features(interchange.archive PRIVATE cxx_std_20)
    target_link_libraries(interchange.archive PRIVATE
        Pwb::Interchange Pwb::Domain)
    target_compile_definitions(interchange.archive PRIVATE
        PWB_INTERCHANGE_ARCHIVE_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/interchange_archive_oracle.json")
    add_test(NAME interchange.archive COMMAND interchange.archive)
    set_tests_properties(interchange.archive PROPERTIES TIMEOUT 300)
endif()
