# pwb::workflow minimal task runtime (queued/running/succeeded/failed/cancelled).
# Added from libs/science_suite; not a standalone entry point.

add_library(pwb_workflow STATIC
    src/task_runtime.cpp
)
add_library(Pwb::Workflow ALIAS pwb_workflow)
set_target_properties(pwb_workflow PROPERTIES
    EXPORT_NAME Workflow
    OUTPUT_NAME pwb-workflow
    POSITION_INDEPENDENT_CODE ON
)
target_compile_features(pwb_workflow PUBLIC cxx_std_20)
target_include_directories(pwb_workflow
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
find_package(Threads REQUIRED)
target_link_libraries(pwb_workflow
    PUBLIC
        Threads::Threads
        Pwb::Science
)
if(MSVC)
    target_compile_options(pwb_workflow PRIVATE /W4 /permissive- /wd4251 /wd4275)
else()
    target_compile_options(pwb_workflow PRIVATE -Wall -Wextra -Wpedantic)
endif()
