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
pwb_data_test(data_catalog_domain catalog_domain_test.cpp data.catalog_domain)
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

# BEGIN CONV-15
# Catalog GC / payload dedup / entity pagination oracle reconciliation
# (fixtures catalog_gc/* generated by tools/oracle/generate_catalog_gc_fixtures.py).
pwb_data_test(data_catalog_gc catalog_gc_test.cpp data.catalog_gc)
# END CONV-15

# BEGIN CONV-26
# SQL-level paged reads: replays the frozen paged_queries oracle straight
# over catalog.sqlite and cross-checks against the document path.
pwb_data_test(data_paged_sql paged_sql_test.cpp data.paged_sql)
# Ingest plan build+execute orchestration oracle reconciliation (fixtures
# ingest_plan/* generated by tools/oracle/generate_ingest_plan_fixtures.py).
pwb_data_test(data_ingest_plan ingest_plan_test.cpp data.ingest_plan)
# Save-As relocation + workspace membership mutations.
pwb_data_test(data_lifecycle_ops lifecycle_ops_test.cpp data.lifecycle_ops)
# E2E acceptance loop (create→import→runs→workspace→save→save-as→reopen→
# paginate→audit), pure C++.
pwb_data_test(data_lifecycle_e2e lifecycle_e2e_test.cpp data.lifecycle_e2e)
# Deterministic perf sanity at 120k metadata records (not a benchmark).
pwb_data_test(data_metadata_scale metadata_scale_test.cpp data.metadata_scale)
# END CONV-26

# BEGIN CONV-31B
# Catalog service/db deep-core oracle replay (fixtures catalog_service/*
# generated by tools/oracle/generate_catalog_service_fixtures.py).
pwb_data_test(data_catalog_service catalog_service_test.cpp data.catalog_service)
# END CONV-31B

# BEGIN cpp-close-01
# Line-01 closure: the CONCRETE catalog service adapter over the CONV-31b
# deep core, driven through the full production chain (project open →
# query/filter → import registration → working copy → commit → close/reopen)
# plus the failure matrix (rollback / read-only / corrupt / short-write /
# concurrent revision conflict / project switch) and the real change feed.
# The adapter TUs are compiled into the test — the same sources the
# platform app links under PWB_BUILD_CATALOG_CLOSURE.
# PWB-V14-DATA-LINEAGE: guarded — the closure test needs the ROOT source
# tree (apps/ + ui_controllers/ui_review/ui_data_core targets) and only
# configures in the integrated build; the standalone data-suite entry
# skips it instead of failing configure (01 ledger A12 follow-up).
if(TARGET Pwb::UiControllers)
pwb_data_test(data_catalog_closure catalog_closure_test.cpp
    data.catalog_closure)
target_sources(data_catalog_closure PRIVATE
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/closure_catalog_service.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/closure_catalog_install.cpp)
target_include_directories(data_catalog_closure PRIVATE
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform
    ${CMAKE_SOURCE_DIR}/libs/ui_review/include)
target_link_libraries(data_catalog_closure PRIVATE
    Pwb::UiControllers Pwb::UiDataCore)
endif()
# END cpp-close-01

# BEGIN PWB-V14-DATA-LINEAGE
# V14 domain layer: role registry + entity↔asset link ordinals/read views +
# remove/prune family; entity workspace read model (fake/throwing catalog
# seam, slot assembly, stale attribution, honest degrade); manual-edit
# provenance run assembly/completion + artifact lifecycle enforcement.
pwb_data_test(data_entity_domain_ops entity_domain_ops_test.cpp
    data.entity_domain_ops)
pwb_data_test(data_entity_workspace entity_workspace_test.cpp
    data.entity_workspace)
# Scale / structural layer over the same read model: 10k wells + 100k links
# with a throwing source (zero catalog reads, O(W+L) index ceiling), bounded
# expand-one-well point lookups, project-switch isolation, snapshot guard.
pwb_data_test(data_entity_workspace_scale entity_workspace_scale_test.cpp
    data.entity_workspace_scale)
pwb_data_test(data_manual_edit manual_edit_provenance_test.cpp
    data.manual_edit)
pwb_data_test(data_fabric_e2e data_fabric_e2e_test.cpp data.data_fabric_e2e)
# END PWB-V14-DATA-LINEAGE

