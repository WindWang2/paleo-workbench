# UI-16 — visual-QA slice (libs/ui_visualqa): the C++ port of
# paleo_workbench/ui/visual_qa_v{6..11}.py +
# ui/prototypes/proto_dual_volume_overlay.py (non-production prototype,
# honest port — see the header notes).
#
# Layering (repo convention — ui_map/ui_shell split):
#   pwb_ui_visualqa      Qt-free cores: CheckResult/payload vocabulary,
#                        V6..V11 state/scenario registries + shot tables,
#                        the workstation/scenario snapshot contract, every
#                        pure check body, the dual-volume prototype math
#   pwb_ui_visualqa_qt   Qt Widgets shells: the VisualQaProbe seam the
#                        V6..V10 drive recipes orchestrate, the V11
#                        scenario builders (real ported widgets where they
#                        exist, honest seam-unavailable placeholders where
#                        AppShell / DataPage / MappingStageBar+Panel are
#                        unported), and the dual-volume overlay widget +
#                        host window
#
# Hard requirements (fail-closed at configure, like libs/ui_workers):
#   Pwb::Domain      ordered JSON (checks_payload sidecar)
#   Pwb::ToolPolicy  stage + tool-availability authority — the checks and
#                    the palette scenario never re-derive verdicts
foreach(_required Pwb::Domain Pwb::ToolPolicy)
    if(NOT TARGET ${_required})
        message(FATAL_ERROR
            "libs/ui_visualqa requires ${_required} — the root UI-16 "
            "block pulls it in under PWB_BUILD_PLATFORM; standalone "
            "configures must enable it explicitly")
    endif()
endforeach()

add_library(pwb_ui_visualqa STATIC
    src/qa_check.cpp
    src/qa_states.cpp
    src/qa_checks.cpp
    src/dual_volume.cpp
)
add_library(Pwb::UiVisualqa ALIAS pwb_ui_visualqa)
target_include_directories(pwb_ui_visualqa PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_visualqa PUBLIC cxx_std_20)
# PUBLIC: qa_check.hpp exposes pwb::domain::Json (checks_payload).
# PRIVATE: only qa_checks.cpp resolves stage labels for detail strings.
target_link_libraries(pwb_ui_visualqa
    PUBLIC Pwb::Domain
    PRIVATE Pwb::ToolPolicy)

if(TARGET Qt6::Widgets)
    add_library(pwb_ui_visualqa_qt STATIC
        src/qt/qa_driver.cpp
        src/qt/scenario_host.cpp
        src/qt/dual_volume_overlay.cpp
        # Q_OBJECT headers listed so AUTOMOC discovers them in this split
        # include/ layout (the seam headers carry no Q_OBJECT but ride
        # along for IDE/source-list completeness).
        include/pwb/ui_visualqa/qt/workstation_probe.hpp
        include/pwb/ui_visualqa/qt/qa_driver.hpp
        include/pwb/ui_visualqa/qt/scenario_host.hpp
        include/pwb/ui_visualqa/qt/dual_volume_overlay.hpp
    )
    add_library(Pwb::UiVisualqaQt ALIAS pwb_ui_visualqa_qt)
    set_target_properties(pwb_ui_visualqa_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_visualqa_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_visualqa_qt PUBLIC cxx_std_20)
    # PUBLIC: headers expose the Qt-free core types + QWidget subclasses.
    # PRIVATE: the real widgets the V11 builders construct (task panels,
    # seismic toolbar, inspector, task center, command palette, state
    # widgets) — consumers only see the ScenarioHandle/VisualQaProbe
    # contracts, never the panel headers.
    target_link_libraries(pwb_ui_visualqa_qt
        PUBLIC Pwb::UiVisualqa Qt6::Widgets
        PRIVATE Pwb::UiShellQt Pwb::UiWellseisQt Pwb::UiWidgets
                Pwb::UiWorkstationQt Pwb::PlatformServices Qt6::Gui)
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_visualqa_tests)
endif()
