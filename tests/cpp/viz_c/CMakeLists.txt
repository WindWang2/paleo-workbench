# VIZ-C tests (#1380/#1381 store concurrency + joint well-seismic 3D).
# Registered from the root CMakeLists BEGIN/END VIZ-C block whenever the
# application store closure is built. Each executable is one CTest entry;
# no external framework; 0 tests / all-skip never counts as pass.
set(VIZ_C_DATA_FIXTURE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../data/fixtures"
    CACHE PATH "Shared data-suite oracle fixture corpus")

function(viz_c_test target source ctest_name)
    add_executable(${target} ${source} test_main.cpp)
    target_link_libraries(${target} PRIVATE
        Pwb::Application Pwb::Data Pwb::Catalog Pwb::Project Pwb::Domain)
    target_include_directories(${target} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    target_compile_definitions(${target} PRIVATE
        VIZ_C_DATA_FIXTURE_DIR="${VIZ_C_DATA_FIXTURE_DIR}")
    if(MSVC)
        target_compile_options(${target} PRIVATE /utf-8 /W4 /permissive-)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    add_test(NAME ${ctest_name} COMMAND ${target})
    # MALLOC audit runs with the suite (glibc allocator checks).
    set_tests_properties(${ctest_name} PROPERTIES
        TIMEOUT 300 ENVIRONMENT "MALLOC_CHECK_=3")
endfunction()

viz_c_test(viz_c_store_concurrency store_concurrency_test.cpp
    viz_c.store_concurrency)
