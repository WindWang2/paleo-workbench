# Phase A oracle for the QGIS-native Python runtime. Only built when the
# runtime library is built (parent directory adds this unconditionally, and the
# parent is only added when PALEO_WITH_QGIS_PYTHON is ON).

add_executable(qgis_python.runtime python_runtime_test.cpp)
target_compile_features(qgis_python.runtime PRIVATE cxx_std_20)
target_link_libraries(qgis_python.runtime PRIVATE Pwb::QgisPython)
add_test(NAME qgis_python.runtime COMMAND qgis_python.runtime)
set_tests_properties(qgis_python.runtime PROPERTIES TIMEOUT 180)
