add_library(pwb_qgis STATIC
    # native-product closure: the runtime TU lives under qgis_runtime_entry.*
    # (was qgis_runtime.*; renamed when a toolchain-level defect on one
    # verification host silently compiled that exact path's acquire() into a
    # self-jump — see docs/development/cpp-platform/native-product-closure.md
    # §"toolchain note"). Same content, fresh path, verified clean output.
    src/qgis_runtime_entry.cpp
    src/layer_adapter.cpp
    src/map_session.cpp
    src/map_project_store.cpp
    src/layer_factory.cpp
    src/edit_controller.cpp
    # BEGIN qgis-native-layout-convergence
    # QgsLayoutManager-backed persistent layout authority: slots, the single
    # PWB custom item, the shared element→native-item materializer, the
    # authority (templates + migration + persistence) and the unified
    # QgsLayoutExporter service.
    src/layout_slots.cpp
    src/layout_slot_item.cpp
    src/layout_materializer.cpp
    src/layout_authority.cpp
    src/layout_export_service.cpp
    src/layout_editor_panel.cpp
    # Q_OBJECT headers must be listed for AUTOMOC (it does not scan the
    # separate include/ tree on its own).
    include/pwb/qgis/layout_slot_item.hpp
    include/pwb/qgis/layout_editor_panel.hpp
    # END qgis-native-layout-convergence
    # QGIS-NATIVE-LAYER-CONTROL: the single writer/reader of the
    # session layer-tree structure (sidecar persistence, system-group
    # skeleton, batched visibility, placements). Successor of the
    # retired V14 applier/reconcile plane.
    src/layer_tree_composer.cpp
)
add_library(Pwb::Qgis ALIAS pwb_qgis)
# qgis-native-layout-convergence: Q_OBJECT classes (PwbLayoutSlotItem,
# LayoutEditorPanel) need moc.
set_target_properties(pwb_qgis PROPERTIES AUTOMOC ON)
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
# BEGIN qgis-native-layout-convergence
# The layout authority consumes the mapping_document kernel in its
# retained roles: geological template definitions (single declarative
# semantics source) + legacy Composition reader (migration input only —
# the composer renderer/exporter stay out of the product path).
if(TARGET Pwb::MappingDocument)
    target_link_libraries(pwb_qgis PUBLIC Pwb::MappingDocument)
endif()
# END qgis-native-layout-convergence
# BEGIN CONV-29
# Composition/Layout/Export kernel wiring: the layout authority and export
# service live in this target (Pwb::Qgis layout_*); the kernel lib joins
# the product link closure through this PUBLIC link so pwb-platform picks
# it up transitively (the retired CompositionLayoutService +
# layout_spec_exec.cpp vendored-TU chain is gone — the bridge compiles
# layout_spec_exec itself).
if(PWB_BUILD_CONV_29)
    target_link_libraries(pwb_qgis PUBLIC Pwb::LayoutExport)
endif()
# END CONV-29
# Vendored prefix path baked at build time (SDK admission owns the value).
target_compile_definitions(pwb_qgis PRIVATE
    PALEO_QGIS_PREFIX_PATH="${PALEO_QGIS_SDK_DIR}")
