# V14-THREE-STAGE-UX — stage presentation projection: Qt-free core
# (stage snapshot/layout profile/preference codec + unified surface
# state model) + a Qt Widgets controller shell. The core holds no domain
# authority (tool_policy is the stage vocabulary source); the Qt shell
# binds authority through seams only.

add_library(pwb_ui_stageflow STATIC
    src/stage_presentation.cpp
)
add_library(Pwb::UiStageflow ALIAS pwb_ui_stageflow)
target_include_directories(pwb_ui_stageflow PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_stageflow PUBLIC cxx_std_20)
target_link_libraries(pwb_ui_stageflow PUBLIC Pwb::ToolPolicy)

if(TARGET Qt6::Widgets)
    add_library(pwb_ui_stageflow_qt STATIC
        src/qt/stage_flow_controller.cpp
        # Q_OBJECT header listed as a source so AUTOMOC discovers the class
        # in this split include/ layout (repo hard convention).
        include/pwb/ui_stageflow/qt/stage_flow_controller.hpp
    )
    add_library(Pwb::UiStageflowQt ALIAS pwb_ui_stageflow_qt)
    set_target_properties(pwb_ui_stageflow_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_stageflow_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_stageflow_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_stageflow_qt
        PUBLIC Pwb::UiStageflow Qt6::Widgets)
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_stageflow_tests)
endif()
