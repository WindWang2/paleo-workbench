# CONV-23 — workflow/contracts pure contract layer: pydantic-lite models,
# the 14 generated module declarations (modules_data.inc), registry +
# consistency validation, metadata-only readiness evaluation and the two
# deterministic markdown reports. Qt-free, Python-free; links Pwb::Domain
# for ordered JSON. Frozen against workflow_contract_oracle.json.

add_library(pwb_workflow_contracts STATIC
    src/models.cpp
    src/registry.cpp
    src/readiness.cpp
    src/report.cpp
)
add_library(Pwb::WorkflowContracts ALIAS pwb_workflow_contracts)
set_target_properties(pwb_workflow_contracts PROPERTIES
    EXPORT_NAME WorkflowContracts
    OUTPUT_NAME pwb-workflow-contracts
    POSITION_INDEPENDENT_CODE ON
)
target_compile_features(pwb_workflow_contracts PUBLIC cxx_std_20)
target_include_directories(pwb_workflow_contracts PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
# PUBLIC: the contract headers expose pwb::domain::Json types.
target_link_libraries(pwb_workflow_contracts PUBLIC Pwb::Domain)

if(BUILD_TESTING)
    add_subdirectory(workflow_contracts_tests)
endif()
