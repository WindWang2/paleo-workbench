# CONV-27 cartography oracle tests — same hand-rolled pattern as
# libs/mapping_kernel/mapping_kernel_tests (no framework dependency):
# fixture paths via compile-time macros, JSON diff via Pwb::Domain.
#
# The scalar test additionally includes the lib-internal numpy_math.hpp
# (the PCG64/Floyd draw seam is white-box by design: the oracle freezes the
# exact sampled arrays).

set(CARTOGRAPHY_FIXTURE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/fixtures")

foreach(test_name
        color_ramps
        vector_style
        scalar_style
        geological_symbols
        style_library
        templates
        qgis_adapter
        oracle_negative)
    add_executable(cartography.${test_name} ${test_name}_test.cpp)
    target_compile_features(cartography.${test_name} PRIVATE cxx_std_20)
    target_link_libraries(cartography.${test_name} PRIVATE
        Pwb::Cartography Pwb::Domain Pwb::MappingDocument)
    target_include_directories(cartography.${test_name} PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/../src)
    target_compile_definitions(cartography.${test_name} PRIVATE
        PWB_CARTOGRAPHY_FIXTURE_DIR="${CARTOGRAPHY_FIXTURE_DIR}"
        PWB_COLOR_RAMPS_FIXTURE="${CARTOGRAPHY_FIXTURE_DIR}/color_ramps_oracle.json"
        PWB_MAP_STYLES_FIXTURE="${CARTOGRAPHY_FIXTURE_DIR}/map_styles_oracle.json"
        PWB_SCALAR_STYLE_FIXTURE="${CARTOGRAPHY_FIXTURE_DIR}/scalar_style_oracle.json"
        PWB_GEOLOGICAL_SYMBOLS_FIXTURE="${CARTOGRAPHY_FIXTURE_DIR}/geological_symbols_oracle.json"
        PWB_STYLE_LIBRARY_FIXTURE="${CARTOGRAPHY_FIXTURE_DIR}/style_library_oracle.json"
        PWB_TEMPLATES_FIXTURE="${CARTOGRAPHY_FIXTURE_DIR}/templates_oracle.json"
        PWB_QGIS_STYLE_FIXTURE="${CARTOGRAPHY_FIXTURE_DIR}/qgis_style_oracle.json"
        PWB_FLATTEN_QGIS_FIXTURE="${CARTOGRAPHY_FIXTURE_DIR}/flatten_qgis_oracle.json")
    add_test(NAME cartography.${test_name} COMMAND cartography.${test_name})
    set_tests_properties(cartography.${test_name} PROPERTIES TIMEOUT 120)
endforeach()
