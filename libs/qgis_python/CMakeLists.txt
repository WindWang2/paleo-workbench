# QGIS-native Python runtime (Prompt 7 — qgispython / PyQGIS / console /
# plugins). The library is only added when the vendored QGIS closure carries
# its Python support (PALEO_WITH_QGIS_PYTHON); with the option OFF the tree is
# untouched and the existing build is byte-identical.
#
# See docs/development/qgis-native-python-runtime/03-qgispython-bootstrap.md.

add_library(pwb_qgis_python STATIC
    src/python_runtime.cpp
    src/python_runner.cpp
    src/python_diagnostics.cpp
)
add_library(Pwb::QgisPython ALIAS pwb_qgis_python)

target_include_directories(pwb_qgis_python PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_qgis_python PUBLIC cxx_std_20)

# qgispython / QgsPythonUtils / QgsPythonRunner / QgsApplication all come from
# the vendored SDK; nothing here links a system QGIS.
target_link_libraries(pwb_qgis_python PUBLIC PwbQgis::Sdk)

# The vendored src/python tree is only present when the closure was imported.
if(EXISTS "${CMAKE_SOURCE_DIR}/third_party/qgis/src/python/qgspythonutils.h")
    target_include_directories(pwb_qgis_python PRIVATE
        ${CMAKE_SOURCE_DIR}/third_party/qgis/src/python)
endif()

if(TARGET Pwb::Qgis)
    target_link_libraries(pwb_qgis_python PUBLIC Pwb::Qgis)
endif()

add_subdirectory(qgis_python_tests)
