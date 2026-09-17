add_library(pwb_application STATIC
    src/project_session.cpp
)
add_library(Pwb::Application ALIAS pwb_application)
target_include_directories(pwb_application PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_application PUBLIC cxx_std_20)
target_link_libraries(pwb_application PUBLIC Pwb::Qgis Pwb::ToolPolicy)

# B/C integration adapters: only when the real modules are in the build
# (fail-closed at the root); never compiled against substitutes.
if(TARGET Pwb::Data AND TARGET Pwb::Science AND TARGET Pwb::Visualization)
    target_sources(pwb_application PRIVATE
        src/adapters/volume_payload.cpp
        src/adapters/data_store.cpp
        src/adapters/catalog_publisher.cpp)
    target_link_libraries(pwb_application PUBLIC
        Pwb::Data Pwb::Science Pwb::Visualization)
    target_compile_definitions(pwb_application PUBLIC
        PWB_WITH_DATA_INTEGRATION=1)
endif()
