add_library(pwb_application STATIC
    src/project_session.cpp
)
add_library(Pwb::Application ALIAS pwb_application)
target_include_directories(pwb_application PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_application PUBLIC cxx_std_20)
target_link_libraries(pwb_application PUBLIC Pwb::Qgis Pwb::ToolPolicy)
