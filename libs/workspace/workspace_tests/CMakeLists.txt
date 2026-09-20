# workspace.* CTest entries (V14-QGIS-CONTROL). Same conventions as
# tests/cpp/data: one executable per entry, no external framework,
# 0 tests never counts as pass.
set(PWB_WORKSPACE_FIXTURE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/fixtures"
    CACHE PATH "Layer-control oracle fixture (generated, committed)")

function(pwb_workspace_test target source ctest_name)
    add_executable(${target} ${source} test_main.cpp)
    target_link_libraries(${target} PRIVATE Pwb::Workspace Pwb::Domain)
    target_include_directories(${target} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    target_compile_definitions(${target} PRIVATE
        PWB_WORKSPACE_FIXTURE_DIR="${PWB_WORKSPACE_FIXTURE_DIR}")
    if(MSVC)
        target_compile_options(${target} PRIVATE /utf-8 /W4 /permissive-)
    endif()
    add_test(NAME ${ctest_name} COMMAND ${target})
    set_tests_properties(${ctest_name} PROPERTIES TIMEOUT 300)
endfunction()

pwb_workspace_test(workspace_layer_control_oracle oracle_replay_test.cpp
    workspace.layer_control_oracle)
pwb_workspace_test(workspace_layer_control_scale layer_control_scale_test.cpp
    workspace.layer_control_scale)
