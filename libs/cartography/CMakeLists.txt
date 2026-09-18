# CPP cartography — CONV-27: Qt-free style/template/symbol/ramp registry
# ported from paleo_workbench/mapping (color_ramps, map_styles,
# scalar_style, geological_symbols, geological_style_library, qgis_style,
# geological_pipeline/templates) and the QGIS bridge payload adapter.
# Frozen against tools/oracle/generate_cartography_fixtures.py.
add_library(pwb_cartography STATIC
    src/color_ramps.cpp
    src/vector_style.cpp
    src/scalar_style.cpp
    src/numpy_math.cpp
    src/geological_symbols.cpp
    src/style_library.cpp
    src/templates.cpp
    src/qgis_adapter.cpp
    src/cartography.cpp
)
add_library(Pwb::Cartography ALIAS pwb_cartography)
target_include_directories(pwb_cartography PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_cartography PUBLIC cxx_std_20)
if(NOT TARGET Pwb::Domain)
    message(FATAL_ERROR
        "pwb_cartography requires Pwb::Domain "
        "(configure with -DPWB_BUILD_DATA=ON)")
endif()
if(NOT TARGET Pwb::MappingDocument)
    message(FATAL_ERROR
        "pwb_cartography requires Pwb::MappingDocument "
        "(configure with -DPWB_BUILD_CONV_02=ON; the template library "
        "builds on the CONV-02 composition/document models)")
endif()
target_link_libraries(pwb_cartography PUBLIC Pwb::Domain Pwb::MappingDocument)

if(BUILD_TESTING)
    add_subdirectory(cartography_tests)
endif()
