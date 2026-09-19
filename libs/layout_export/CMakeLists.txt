# CONV-29 — Qt-free layout-export behavior kernel ported from
# paleo_workbench/mapping/layout_export.py (build_layout_spec, hybrid
# classification, legend mirror gates, export pixel budget, report,
# screen/export parity). Consumes the CONV-02 composition document kernel;
# frozen against the Python oracle via
# tools/oracle/generate_layout_export_fixtures.py.
add_library(pwb_layout_export STATIC
    src/layout_export.cpp)
add_library(Pwb::LayoutExport ALIAS pwb_layout_export)
target_include_directories(pwb_layout_export PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_layout_export PUBLIC cxx_std_20)
if(NOT TARGET Pwb::MappingDocument)
    message(FATAL_ERROR
        "pwb_layout_export requires Pwb::MappingDocument "
        "(configure with -DPWB_BUILD_CONV_29=ON, which implies "
        "PWB_BUILD_CONV_02 + PWB_BUILD_DATA)")
endif()
target_link_libraries(pwb_layout_export PUBLIC Pwb::MappingDocument)

if(BUILD_TESTING)
    add_subdirectory(layout_export_tests)
endif()
