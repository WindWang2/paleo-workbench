# CONV-02 — Qt-free MapDocument / MapCompositionDocument JSON kernel ported
# from paleo_workbench/mapping/layers.py + mapping/composer/models.py
# (full-conversion plan M6: pipeline MapDocument leaf). Frozen against the
# Python oracle via tools/oracle/generate_map_document_fixtures.py.
add_library(pwb_mapping_document STATIC
    src/map_document.cpp
    src/composition.cpp)
add_library(Pwb::MappingDocument ALIAS pwb_mapping_document)
target_include_directories(pwb_mapping_document PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_mapping_document PUBLIC cxx_std_20)
if(NOT TARGET Pwb::Domain)
    message(FATAL_ERROR
        "pwb_mapping_document requires Pwb::Domain "
        "(configure with -DPWB_BUILD_DATA=ON)")
endif()
target_link_libraries(pwb_mapping_document PUBLIC Pwb::Domain)

if(BUILD_TESTING)
    add_subdirectory(mapping_document_tests)
endif()
