# data.* CTest entries (test-plan.md §2). Added by the standalone suite in
# libs/data_suite/CMakeLists.txt. One executable per entry; no external
# test framework; 0 tests / all-skip never counts as pass.
set(PWB_DATA_FIXTURE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/fixtures"
    CACHE PATH "Oracle fixture corpus (generated, committed)")

# dumpbin ships next to cl.exe in the MSVC layout; hygiene is fail-closed.
if(MSVC)
    get_filename_component(_pwb_cxx_dir "${CMAKE_CXX_COMPILER}" DIRECTORY)
    set(PWB_DUMPBIN_EXE "${_pwb_cxx_dir}/dumpbin.exe"
        CACHE FILEPATH "dumpbin for data.build_hygiene")
    if(NOT EXISTS "${PWB_DUMPBIN_EXE}")
        message(FATAL_ERROR "data.build_hygiene needs ${PWB_DUMPBIN_EXE}")
    endif()
endif()

function(pwb_data_test target source ctest_name)
    add_executable(${target} ${source} test_main.cpp)
    target_link_libraries(${target} PRIVATE
        Pwb::Data Pwb::Catalog Pwb::Project Pwb::Workspace Pwb::Domain)
    target_include_directories(${target} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    target_compile_definitions(${target} PRIVATE
        PWB_DATA_FIXTURE_DIR="${PWB_DATA_FIXTURE_DIR}")
    if(MSVC)
        target_compile_options(${target} PRIVATE /utf-8 /W4 /permissive-)
    endif()
    add_test(NAME ${ctest_name} COMMAND ${target} ${ARGN})
    set_tests_properties(${ctest_name} PROPERTIES TIMEOUT 300)
endfunction()

pwb_data_test(data_domain_ids domain_ids_test.cpp data.domain_ids)
pwb_data_test(data_workspace_codec workspace_codec_test.cpp
    data.workspace_codec)
pwb_data_test(data_build_hygiene build_hygiene_test.cpp data.build_hygiene
    --dumpbin "${PWB_DUMPBIN_EXE}"
    "$<TARGET_FILE:data_build_hygiene>"
    "$<TARGET_FILE:pwb-inspect>"
    "$<TARGET_FILE:pwb-migrate>")
