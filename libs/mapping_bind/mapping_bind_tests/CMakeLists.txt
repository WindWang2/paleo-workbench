# mapping_bind.smoke — runs the pybind11 module against the frozen Python
# oracle (bind_oracle.json, generated from the REAL implementation by
# libs/mapping_bind/oracle/generate_fixtures.py). PYTHONPATH must point at the
# directory containing the built pwb_mapping_kernel*.so (set by the CTest
# ENVIRONMENT property).
add_test(NAME mapping_bind.smoke
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/smoke.py")
set_tests_properties(mapping_bind.smoke PROPERTIES
    ENVIRONMENT "PYTHONPATH=$<TARGET_FILE_DIR:mapping_bind_module>"
    TIMEOUT 120)
