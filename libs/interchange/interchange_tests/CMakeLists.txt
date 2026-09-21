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

# CPP-CLOSE-10 — delivery/batch/dependency-audit/closure services.
# dependency_audit + delivery need only the catalog seams (always on);
# closure rides on the native model-adapter service and the provider plugin
# runtime (same gating as its lib sources).
add_executable(interchange.dependency_audit dependency_audit_test.cpp)
target_compile_features(interchange.dependency_audit PRIVATE cxx_std_20)
target_link_libraries(interchange.dependency_audit PRIVATE
    Pwb::Interchange Pwb::Domain)
add_test(NAME interchange.dependency_audit COMMAND interchange.dependency_audit)
set_tests_properties(interchange.dependency_audit PROPERTIES TIMEOUT 120)

add_executable(interchange.delivery delivery_test.cpp)
target_compile_features(interchange.delivery PRIVATE cxx_std_20)
target_link_libraries(interchange.delivery PRIVATE
    Pwb::Interchange Pwb::Domain)

# resources/exporters.py oracle replay (converter table + Qt-free converters).
# The test reaches into src/ for the internal xlsx grid reader.
add_executable(interchange.exporters exporters_test.cpp)
target_compile_features(interchange.exporters PRIVATE cxx_std_20)
target_link_libraries(interchange.exporters PRIVATE
    Pwb::Interchange Pwb::Domain Pwb::Ingest Pwb::SeismicIo)
target_include_directories(interchange.exporters PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../src)
target_compile_definitions(interchange.exporters PRIVATE
    PWB_EXPORTERS_ORACLE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/exporters_oracle.json"
    PWB_TINY_SEGY="${CMAKE_SOURCE_DIR}/tests/fixtures/realdata/tiny.sgy")
add_test(NAME interchange.exporters COMMAND interchange.exporters)
set_tests_properties(interchange.exporters PROPERTIES TIMEOUT 120)
add_test(NAME interchange.delivery COMMAND interchange.delivery)
set_tests_properties(interchange.delivery PROPERTIES TIMEOUT 300)

if(TARGET Pwb::GeoModel AND TARGET Pwb::Providers)
    add_executable(interchange.closure closure_test.cpp)
    target_compile_features(interchange.closure PRIVATE cxx_std_20)
    target_link_libraries(interchange.closure PRIVATE
        Pwb::Interchange Pwb::Domain)
    add_test(NAME interchange.closure COMMAND interchange.closure)
    set_tests_properties(interchange.closure PROPERTIES TIMEOUT 300)
endif()
