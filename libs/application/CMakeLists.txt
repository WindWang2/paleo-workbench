add_library(pwb_application STATIC
    src/project_session.cpp
)
add_library(Pwb::Application ALIAS pwb_application)
target_include_directories(pwb_application PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_application PUBLIC cxx_std_20)
target_link_libraries(pwb_application PUBLIC Pwb::Qgis Pwb::ToolPolicy)

# B/C integration adapters: only when the real modules are in the build
# (fail-closed at the root); never compiled against substitutes.
if(TARGET Pwb::Data AND TARGET Pwb::Science AND TARGET Pwb::Visualization
        AND TARGET Pwb::Workflow)
    target_sources(pwb_application PRIVATE
        src/adapters/volume_payload.cpp
        src/adapters/data_store.cpp
        src/adapters/catalog_publisher.cpp
        src/algorithm_runner.cpp)
    # CONV-QGIS-PROCESSING phase 4: algorithm_runner delegates discovery and
    # execution to QgsProcessingRegistry. This directory is processed BEFORE
    # libs/qgis_processing mounts (root CMakeLists ordering), so an alias
    # TARGET probe here could never fire — the link uses the PLAIN target
    # name, resolved at generate time like the ui_wellseis precedent.
    # PRIVATE: the public algorithm_runner.hpp stays std-only; the registry
    # delegation (Qt/QGIS includes) lives in the .cpp. CMake still places
    # the archive on every consumer's link line (static-lib LINK_ONLY).
    target_link_libraries(pwb_application PRIVATE pwb_qgis_processing)
    target_link_libraries(pwb_application PUBLIC
        Pwb::Data Pwb::Science Pwb::Visualization Pwb::Workflow)
    target_compile_definitions(pwb_application PUBLIC
        PWB_WITH_DATA_INTEGRATION=1)
endif()

# BEGIN CONV-01
# Swarm task 01: Qt-free orchestration over the frozen mapping_kernel
# (extract -> interpolate -> contour -> polygonize -> GeoJSON features).
if(PWB_BUILD_CONV_01)
    target_sources(pwb_application PRIVATE src/map_pipeline_runner.cpp)
    # PUBLIC link is load-bearing: the app and the map-pipeline test compile
    # main_window.cpp themselves and need the transitive kernel link.
    target_link_libraries(pwb_application PUBLIC Pwb::MappingKernel)
endif()
# END CONV-01
