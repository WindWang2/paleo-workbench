add_library(pwb_qgis STATIC
    # native-product closure: the runtime TU lives under qgis_runtime_entry.*
    # (was qgis_runtime.*; renamed when a toolchain-level defect on one
    # verification host silently compiled that exact path's acquire() into a
    # self-jump — see docs/development/cpp-platform/native-product-closure.md
    # §"toolchain note"). Same content, fresh path, verified clean output.
    src/qgis_runtime_entry.cpp
    src/layer_adapter.cpp
    src/map_session.cpp
    src/edit_controller.cpp
    src/layout_service.cpp
    # QGIS-NATIVE-LAYER-CONTROL: the single writer/reader of the
    # session layer-tree structure (sidecar persistence, system-group
    # skeleton, batched visibility, placements). Successor of the
    # retired V14 applier/reconcile plane.
    src/layer_tree_composer.cpp
)
add_library(Pwb::Qgis ALIAS pwb_qgis)
target_include_directories(pwb_qgis PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_qgis PUBLIC cxx_std_20)
target_link_libraries(pwb_qgis PUBLIC PwbQgis::Sdk)
# BEGIN QGIS-NATIVE-LAYER-CONTROL
# layer_tree_composer consumes the Qt-free layer-control policy
# (pwb::ui_composite::layer_groups/layer_ordering + workspace membership
# state) and executes it on the real QgsLayerTree.
target_link_libraries(pwb_qgis PUBLIC Pwb::UiComposite Pwb::Workspace)
# END QGIS-NATIVE-LAYER-CONTROL
# canvas_state_json/map_session.cpp use pwb::domain::Json unconditionally —
# the link cannot wait for the CONV_29 LayoutExport chain (linux-ninja
# configures without it and the TU fails on the missing include path).
if(TARGET Pwb::Domain)
    target_link_libraries(pwb_qgis PUBLIC Pwb::Domain)
endif()
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
