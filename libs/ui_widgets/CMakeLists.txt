# UI-02 — design-system components + model/view + QGIS stack port
# (paleo_workbench/ui/components/*, ui/modelview/*, ui/qgis_stack/*).
#
# Three targets, same split as ui_shell/job_runtime:
#   pwb_ui_widgets_core — Qt-free cores (epoch switching, facies
#       patterns/pick/taxonomy, HUD sampling, QC hub, tree sync);
#   pwb_ui_widgets      — Qt Widgets shells (components + modelview);
#   pwb_ui_widgets_qgis — QGIS-coupled stack (canvas shim, display
#       canvas, stack events, mirror snapshot, QGIS widgets), built only
#       where the vendored QGIS SDK was admitted (Pwb::Qgis exists).

add_library(pwb_ui_widgets_core STATIC
    src/core/epoch_switching.cpp
    src/core/facies_patterns.cpp
    src/core/facies_pick.cpp
    src/core/facies_taxonomy.cpp
    src/core/hud_sampling.cpp
    src/core/qc_hub_core.cpp
    src/core/tree_sync.cpp
)
add_library(Pwb::UiWidgetsCore ALIAS pwb_ui_widgets_core)
target_include_directories(pwb_ui_widgets_core PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_widgets_core PUBLIC cxx_std_20)
# Qt-free cores; nlohmann comes from the same vendor dir the domain and
# platform_services libraries use (header-only, no link dependency).
if(NOT DEFINED PWB_VENDOR_DIR_DEFAULT)
    set(PWB_VENDOR_DIR_DEFAULT
        "${CMAKE_CURRENT_SOURCE_DIR}/../data_suite/third_party")
endif()
target_include_directories(pwb_ui_widgets_core SYSTEM PUBLIC
    $<BUILD_INTERFACE:${PWB_VENDOR_DIR_DEFAULT}>)
if(TARGET Pwb::Domain)
    target_link_libraries(pwb_ui_widgets_core PUBLIC Pwb::Domain)
endif()

# Qt Widgets shells: every Q_OBJECT header is listed as a source so
# AUTOMOC discovers the classes in this split include/ layout.
if(TARGET Qt6::Widgets)
    add_library(pwb_ui_widgets STATIC
        src/async_query.cpp
        src/badges.cpp
        src/buttons.cpp
        src/constraint_factor_hud.cpp
        src/dialog.cpp
        src/facies_eyedropper.cpp
        src/facies_palette_widget.cpp
        src/headers.cpp
        src/icon_factory.cpp
        src/inputs.cpp
        src/interactive_qc_hub.cpp
        src/map_chrome.cpp
        src/object_table.cpp
        src/reconcile.cpp
        src/states.cpp
        src/stratigraphic_timeline_slider.cpp
        src/toast.cpp
        src/ui_context.cpp
        src/views.cpp
        include/pwb/ui_widgets/async_query.hpp
        include/pwb/ui_widgets/badges.hpp
        include/pwb/ui_widgets/buttons.hpp
        include/pwb/ui_widgets/constraint_factor_hud.hpp
        include/pwb/ui_widgets/dialog.hpp
        include/pwb/ui_widgets/facies_eyedropper.hpp
        include/pwb/ui_widgets/facies_palette_widget.hpp
        include/pwb/ui_widgets/headers.hpp
        include/pwb/ui_widgets/inputs.hpp
        include/pwb/ui_widgets/interactive_qc_hub.hpp
        include/pwb/ui_widgets/object_table.hpp
        include/pwb/ui_widgets/states.hpp
        include/pwb/ui_widgets/stratigraphic_timeline_slider.hpp
        include/pwb/ui_widgets/toast.hpp
        include/pwb/ui_widgets/views.hpp
    )
    add_library(Pwb::UiWidgets ALIAS pwb_ui_widgets)
    set_target_properties(pwb_ui_widgets PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_widgets PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_widgets PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_widgets
        PUBLIC Pwb::UiWidgetsCore Pwb::PlatformServices Qt6::Widgets)
    # facies_palette_widget resolves the pattern asset dir relative to the
    # source root (same idiom as platform_services resource_locator).
    target_compile_definitions(pwb_ui_widgets PRIVATE
        PWB_SOURCE_DIR="${CMAKE_SOURCE_DIR}")

    # QGIS stack (canvas shim / display canvas / events / mirror /
    # widgets): only where the vendored SDK was admitted. MapSession is
    # the canvas/session authority; platform_services supplies the
    # resource locator for the facies pattern assets.
    if(TARGET Pwb::Qgis)
        add_library(pwb_ui_widgets_qgis STATIC
            src/qgis/canvas_shim.cpp
            src/qgis/display_canvas.cpp
            src/qgis/mirror_snapshot.cpp
            src/qgis/qgis_widgets.cpp
            src/qgis/stack_events.cpp
            include/pwb/ui_widgets/qgis/canvas_shim.hpp
            include/pwb/ui_widgets/qgis/display_canvas.hpp
            include/pwb/ui_widgets/qgis/qgis_widgets.hpp
            include/pwb/ui_widgets/qgis/stack_events.hpp
        )
        add_library(Pwb::UiWidgetsQgis ALIAS pwb_ui_widgets_qgis)
        set_target_properties(pwb_ui_widgets_qgis PROPERTIES AUTOMOC ON)
        target_include_directories(pwb_ui_widgets_qgis PUBLIC
            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
        target_compile_features(pwb_ui_widgets_qgis PUBLIC cxx_std_20)
        target_link_libraries(pwb_ui_widgets_qgis
            PUBLIC Pwb::UiWidgets Pwb::Qgis Pwb::PlatformServices
                   Qt6::Widgets Qt6::Xml Qt6::Svg Qt6::PrintSupport)
    endif()
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_widgets_tests)
endif()
