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

if(BUILD_TESTING)
    add_subdirectory(geomodel_tests)
endif()
