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
