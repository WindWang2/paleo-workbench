add_library(pwb_ui STATIC
    src/tool_actions.cpp
)
add_library(Pwb::Ui ALIAS pwb_ui)
target_include_directories(pwb_ui PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui PUBLIC cxx_std_20)
target_link_libraries(pwb_ui PUBLIC Pwb::ToolPolicy Qt6::Widgets)
