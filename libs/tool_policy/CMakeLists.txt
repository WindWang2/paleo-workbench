add_library(pwb_tool_policy STATIC
    src/stages.cpp
    src/layer_roles.cpp
    src/tool_availability.cpp
)
add_library(Pwb::ToolPolicy ALIAS pwb_tool_policy)
target_include_directories(pwb_tool_policy PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_tool_policy PUBLIC cxx_std_20)
# Deliberately dependency-free: Qt-free policy core, unit-testable anywhere.
