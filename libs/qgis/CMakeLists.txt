add_library(pwb_qgis STATIC
    src/qgis_runtime.cpp
    src/layer_adapter.cpp
    src/map_session.cpp
    src/edit_controller.cpp
    src/layout_service.cpp
)
add_library(Pwb::Qgis ALIAS pwb_qgis)
target_include_directories(pwb_qgis PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_qgis PUBLIC cxx_std_20)
target_link_libraries(pwb_qgis PUBLIC PwbQgis::Sdk)
# Vendored prefix path baked at build time (SDK admission owns the value).
target_compile_definitions(pwb_qgis PRIVATE
    PALEO_QGIS_PREFIX_PATH="${PALEO_QGIS_SDK_DIR}")

# BEGIN CONV-29
# Composition/Layout/Export C++ wiring: the composition export service and
# the shared wire-spec executor (single authority with the pybind bridge —
# the TU is compiled into both targets). Off by default; Pwb::LayoutExport
# becomes PUBLIC so consumers (app, platform tests) get the kernel too.
if(PWB_BUILD_CONV_29)
    target_sources(pwb_qgis PRIVATE
        src/composition_layout_service.cpp
        ${CMAKE_SOURCE_DIR}/native/qgis_render_bridge/src/layout_spec_exec.cpp)
    target_include_directories(pwb_qgis SYSTEM PRIVATE
        ${CMAKE_SOURCE_DIR}/native/qgis_render_bridge/src)
    target_link_libraries(pwb_qgis PUBLIC Pwb::LayoutExport)
endif()
# END CONV-29
