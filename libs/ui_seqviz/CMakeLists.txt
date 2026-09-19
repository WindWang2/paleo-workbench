# UI-10 — sequence/factor/visualization pages cluster: Qt-free semantic
# cores (state_language, page_tokens, sequence_state, factor_state,
# geoviz_provider, viz_page_state, correlation_state, composition_state,
# curve_ops_state, lithology_state) and the Qt Widgets shells in
# pwb_ui_seqviz_qt (built only when Qt6::Widgets is available).
#
# Worker semantics come from libs/ui_workers (UI-04) — this cluster only
# adds page state/view models and thin widget shells; engine rendering is
# injected through the GeoViz/factor/composition seams.

add_library(pwb_ui_seqviz STATIC
    src/state_language.cpp
    src/sequence_state.cpp
    src/factor_state.cpp
    src/geoviz_provider.cpp
    src/viz_page_state.cpp
    src/correlation_state.cpp
    src/composition_state.cpp
    src/curve_ops_state.cpp
    src/lithology_state.cpp
)
add_library(Pwb::UiSeqviz ALIAS pwb_ui_seqviz)
target_include_directories(pwb_ui_seqviz PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_seqviz PUBLIC cxx_std_20)

foreach(dep IN ITEMS domain ui_data_core ui_workers job_runtime
                     mapping_document well_science)
    if(NOT TARGET pwb_${dep})
        add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../${dep}
                         ${CMAKE_CURRENT_BINARY_DIR}/${dep})
    endif()
endforeach()

target_link_libraries(pwb_ui_seqviz PUBLIC
    Pwb::Domain
    Pwb::UiDataCore
    Pwb::UiWorkers
    Pwb::JobRuntime
    Pwb::MappingDocument
    Pwb::WellScience
)

# Qt Widgets shells (UI-10): sequence panels + framework page, factor
# panels + create-factor-map dialog, visualization summary/trace/workspace/
# page, correlation page, composition panel, lithology crossplot dialog,
# curve operation dialog.
if(TARGET Qt6::Widgets)
    if(NOT TARGET Pwb::UiShellQt)
        add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../ui_shell
                         ${CMAKE_CURRENT_BINARY_DIR}/ui_shell)
    endif()
    if(NOT TARGET Pwb::UiWidgets)
        add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../ui_widgets
                         ${CMAKE_CURRENT_BINARY_DIR}/ui_widgets)
    endif()
    # Pwb::JobQt (job::qtbridge::JobOwner — OwnedWorkerJob parity) comes
    # from the same job_runtime subdirectory the core already pulled in;
    # it exists whenever Qt6::Core was found there.
    if(NOT TARGET Pwb::JobQt)
        message(STATUS "UI-10: pwb_ui_seqviz_qt built without Pwb::JobQt — "
                "dialogs keep the injected-service synchronous path")
    endif()

    add_library(pwb_ui_seqviz_qt STATIC
        src/qt/sequence_panels.cpp
        src/qt/sequence_framework_page.cpp
        src/qt/factor_panels.cpp
        src/qt/viz_panels.cpp
        src/qt/dialogs.cpp
        # Q_OBJECT headers must be listed as sources — AUTOMOC does not
        # scan the separate include/ tree on its own.
        include/pwb/ui_seqviz/qt/sequence_panels.hpp
        include/pwb/ui_seqviz/qt/sequence_framework_page.hpp
        include/pwb/ui_seqviz/qt/panel_float_button.hpp
        include/pwb/ui_seqviz/qt/factor_panels.hpp
        include/pwb/ui_seqviz/qt/viz_panels.hpp
        include/pwb/ui_seqviz/qt/dialogs.hpp
    )
    add_library(Pwb::UiSeqvizQt ALIAS pwb_ui_seqviz_qt)
    set_target_properties(pwb_ui_seqviz_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_seqviz_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_seqviz_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_seqviz_qt
        PUBLIC Pwb::UiSeqviz Pwb::UiShellQt Pwb::UiWidgets Pwb::JobQt
               Qt6::Widgets
        PRIVATE Qt6::Gui)
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_seqviz_tests)
endif()
