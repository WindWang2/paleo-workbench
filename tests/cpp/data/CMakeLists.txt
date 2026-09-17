# data.* CTest entries (test-plan.md §2 + v3-contracts.md §9). Added by the
# standalone suite in libs/data_suite/CMakeLists.txt. One executable per
# entry; no external test framework; 0 tests / all-skip never counts as pass.
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
    set(PWB_HYGIENE_MODE dumpbin)
    set(PWB_HYGIENE_ARGS --dumpbin "${PWB_DUMPBIN_EXE}")
else()
    # ELF layouts audit through ldd; the banned-substring gate is the same.
    set(PWB_DUMPBIN_EXE "" CACHE FILEPATH "unused on ELF (ldd mode)")
    find_program(PWB_LDD ldd REQUIRED)
    set(PWB_HYGIENE_MODE elf)
    set(PWB_HYGIENE_ARGS --mode elf)
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

pwb_data_test(data_domain_ids domain_ids_test.cpp data.domain.ids)
pwb_data_test(data_workspace_codec workspace_codec_test.cpp
    data.workspace_codec)
pwb_data_test(data_diagnostics diagnostics_test.cpp data.diagnostics)
pwb_data_test(data_catalog_read catalog_read_test.cpp data.catalog_read)
pwb_data_test(data_project_paths project_paths_test.cpp data.project_paths)
pwb_data_test(data_project_roundtrip project_roundtrip_test.cpp
    data.project_roundtrip)
pwb_data_test(data_project_recovery project_recovery_test.cpp
    data.project_recovery)
pwb_data_test(data_catalog_write catalog_write_test.cpp data.catalog_write)
pwb_data_test(data_commit_coordinator commit_coordinator_test.cpp
    data.commit_coordinator)
pwb_data_test(data_commit_recovery commit_recovery_test.cpp
    data.commit_recovery)
pwb_data_test(data_run_lifecycle run_lifecycle_test.cpp data.run_lifecycle)
pwb_data_test(data_run_recovery run_recovery_test.cpp data.run_recovery)
pwb_data_test(data_oracle_compare oracle_compare_test.cpp
    data.oracle_compare)
pwb_data_test(data_cli_inspect cli_inspect_test.cpp data.cli_inspect
    --exe "$<TARGET_FILE:pwb-inspect>")
pwb_data_test(data_cli_migrate cli_migrate_test.cpp data.cli_migrate
    --exe "$<TARGET_FILE:pwb-migrate>")
pwb_data_test(data_consumer_loop consumer_loop_test.cpp data.consumer_loop
    --loop "$<TARGET_FILE:pwb-data-loop>"
    --inspect "$<TARGET_FILE:pwb-inspect>")

# The crash test has its own main (child mode intercepts argv before the
# case registry runs), so it cannot use the shared test_main.cpp.
add_executable(data_crash_recovery crash_recovery_test.cpp)
target_link_libraries(data_crash_recovery PRIVATE
    Pwb::Data Pwb::Catalog Pwb::Project Pwb::Workspace Pwb::Domain)
target_include_directories(data_crash_recovery PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(data_crash_recovery PRIVATE
    PWB_DATA_FIXTURE_DIR="${PWB_DATA_FIXTURE_DIR}")
if(MSVC)
    target_compile_options(data_crash_recovery PRIVATE /utf-8 /W4 /permissive-)
endif()
add_test(NAME data.crash_recovery COMMAND data_crash_recovery)
set_tests_properties(data.crash_recovery PROPERTIES TIMEOUT 300)

# The Python oracle readback is REQUIRED (v3-contracts.md §9): configure
# fails loudly when the interpreter or pydantic is missing — never skipped.
find_package(Python3 COMPONENTS Interpreter REQUIRED)
set(PWB_ORACLE_READBACK_SCRIPT
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../tools/oracle/readback_v3.py"
    CACHE FILEPATH "Read-only Python oracle readback script")
if(NOT EXISTS "${PWB_ORACLE_READBACK_SCRIPT}")
    message(FATAL_ERROR "data.oracle_readback: readback script missing: "
        "${PWB_ORACLE_READBACK_SCRIPT}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}" -c "import pydantic"
    RESULT_VARIABLE _pwb_oracle_pydantic)
if(NOT _pwb_oracle_pydantic EQUAL 0)
    message(FATAL_ERROR "data.oracle_readback needs pydantic in "
        "${Python3_EXECUTABLE} (the fixed Python oracle is a required gate)")
endif()
pwb_data_test(data_oracle_readback oracle_readback_test.cpp
    data.oracle_readback
    --loop "$<TARGET_FILE:pwb-data-loop>"
    --python "${Python3_EXECUTABLE}"
    --readback "${PWB_ORACLE_READBACK_SCRIPT}"
    --inspect "$<TARGET_FILE:pwb-inspect>")

pwb_data_test(data_build_hygiene build_hygiene_test.cpp data.build_hygiene
    ${PWB_HYGIENE_ARGS}
    "$<TARGET_FILE:data_build_hygiene>"
    "$<TARGET_FILE:pwb-inspect>"
    "$<TARGET_FILE:pwb-migrate>"
    "$<TARGET_FILE:pwb-data-loop>")
pwb_data_test(data_manifest_export manifest_export_test.cpp data.manifest_export)
