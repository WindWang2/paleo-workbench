# pwb::science algorithm SDK (interface handshake v1 owner).
# Added from libs/science_suite; not a standalone entry point.

add_library(pwb_science STATIC
    src/registry.cpp
    src/algorithms/coherence_c3.cpp
)
add_library(Pwb::Science ALIAS pwb_science)
set_target_properties(pwb_science PROPERTIES
    EXPORT_NAME Science
    OUTPUT_NAME pwb-science
    POSITION_INDEPENDENT_CODE ON
)
target_compile_features(pwb_science PUBLIC cxx_std_20)
target_include_directories(pwb_science
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
find_package(Threads REQUIRED)
target_link_libraries(pwb_science PUBLIC Threads::Threads)
if(MSVC)
    target_compile_options(pwb_science PRIVATE /W4 /permissive- /wd4251 /wd4275)
else()
    target_compile_options(pwb_science PRIVATE -Wall -Wextra -Wpedantic)
endif()
