# UI-14 — root-controller slice (libs/ui_controllers): Qt-free cores of
# the six paleo_workbench/ui root controllers (selection bus + view
# coordination, map actions, data lifecycle, project lifecycle +
# three-phase save worker, cross-page workflow) plus thin Qt Widgets
# shells (QObject signal surfaces, JobOwner-backed workers, stock-dialog
# binds). The integration into the application shell is a later slice —
# these targets expose the seams it binds.
#
# Gating mirrors UI-09/10/11: no per-slice option; the core target joins
# every configuration that resolved the libraries the cores bind
# (job runtime + domain + catalog + project + ui_data_core + ui_workers +
# ui_shell + workflow_runtime + prediction + tool_policy); the _qt target
# additionally needs Qt6::Widgets + Pwb::JobQt.

foreach(_required
        Pwb::JobRuntime Pwb::Domain Pwb::Catalog Pwb::Project
        Pwb::UiDataCore Pwb::UiWorkers Pwb::UiShell Pwb::WorkflowRuntime
        Pwb::Prediction Pwb::ToolPolicy Pwb::UiWorkstation)
    if(NOT TARGET ${_required})
        message(FATAL_ERROR
            "libs/ui_controllers requires ${_required} — it is only "
            "added to configurations that already resolved it")
    endif()
endforeach()

add_library(pwb_ui_controllers STATIC
    src/selection_bus.cpp
    src/view_coordination.cpp
    src/map_actions.cpp
    src/data_lifecycle.cpp
    src/project_save.cpp
    src/project_controller.cpp
    src/workflow_controller.cpp)
add_library(Pwb::UiControllers ALIAS pwb_ui_controllers)
target_include_directories(pwb_ui_controllers PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_controllers PUBLIC cxx_std_20)
# PUBLIC: the headers expose JobSpec/JobContext, domain::Json, catalog
# models, ui_data_core handles, ui_workers inputs and the recompute-plan
# types through the seam APIs.
target_link_libraries(pwb_ui_controllers PUBLIC
    Pwb::JobRuntime Pwb::Domain Pwb::Catalog Pwb::Project
    Pwb::UiDataCore Pwb::UiWorkers Pwb::UiShell Pwb::WorkflowRuntime
    Pwb::Prediction Pwb::ToolPolicy Pwb::UiWorkstation)

# Qt Widgets shells (UI-14): JobOwnerRunner over Pwb::JobQt, the
# MapActionController QObject, QtSelectionContext +
# ViewCoordinationController, and the Project/DataLifecycle/Workflow
# controller shells with stock-dialog binds.
if(TARGET Qt6::Widgets AND TARGET Pwb::JobQt)
    add_library(pwb_ui_controllers_qt STATIC
        src/qt/job_owner_runner.cpp
        src/qt/map_action_controller.cpp
        src/qt/view_coordination_controller.cpp
        src/qt/project_controller.cpp
        src/qt/data_lifecycle_controller.cpp
        src/qt/workflow_controller.cpp
        # Q_OBJECT headers must be listed as sources — AUTOMOC does not
        # scan the separate include/ tree on its own.
        include/pwb/ui_controllers/qt/job_owner_runner.hpp
        include/pwb/ui_controllers/qt/map_action_controller.hpp
        include/pwb/ui_controllers/qt/view_coordination_controller.hpp
        include/pwb/ui_controllers/qt/project_controller.hpp
        include/pwb/ui_controllers/qt/data_lifecycle_controller.hpp
        include/pwb/ui_controllers/qt/workflow_controller.hpp)
    add_library(Pwb::UiControllersQt ALIAS pwb_ui_controllers_qt)
    set_target_properties(pwb_ui_controllers_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_controllers_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_controllers_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_controllers_qt PUBLIC
        Pwb::UiControllers Pwb::JobQt Qt6::Widgets
        PRIVATE Qt6::Gui)
else()
    message(STATUS
        "UI-14: pwb_ui_controllers_qt skipped — needs Qt6::Widgets + "
        "Pwb::JobQt (PWB_BUILD_CONV_30)")
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_controllers_tests)
endif()
