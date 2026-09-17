# Integration tests — REAL B/C/platform modules in one process (protocol:
# independent validation, no substitutes). The suite only registers when
# PWB_BUILD_INTEGRATION_TESTS=ON, which the root CMake already fails loudly
# unless platform+data+science are all in the build.

# PROJ/GDAL data resolution (same rule as tests/cpp/platform: vendor tree
# first, system package fallback on Linux).
if(EXISTS "${PALEO_QGIS_SDK_DIR}/share/proj")
    set(PWB_PROJ_DATA "${PALEO_QGIS_SDK_DIR}/share/proj")
else()
    set(PWB_PROJ_DATA "/usr/share/proj")
endif()
if(EXISTS "${PALEO_QGIS_SDK_DIR}/data/gdal")
    set(PWB_GDAL_DATA "${PALEO_QGIS_SDK_DIR}/data/gdal")
elseif(EXISTS "${PALEO_QGIS_SDK_DIR}/data")
    set(PWB_GDAL_DATA "${PALEO_QGIS_SDK_DIR}/data")
else()
    set(PWB_GDAL_DATA "/usr/share/gdal")
endif()

function(pwb_add_integration_test name)
    add_executable(integration_${name} ${ARGN})
    target_compile_features(integration_${name} PRIVATE cxx_std_20)
    target_link_libraries(integration_${name} PRIVATE
        Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy
        Pwb::Data Pwb::Science Pwb::Workflow Pwb::Visualization)
    target_include_directories(integration_${name} PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/../platform)
    target_compile_definitions(integration_${name} PRIVATE
        PWB_TEST_SRC_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
        PWB_SCIENCE_FIXTURE_ROOT="${CMAKE_SOURCE_DIR}/tests/cpp/science/fixtures")
    add_test(NAME integration.${name} COMMAND integration_${name})
    set_tests_properties(integration.${name} PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
        TIMEOUT 600)
endfunction()

pwb_add_integration_test(project_chain test_project_chain.cpp)
pwb_add_integration_test(algorithm_chain test_algorithm_chain.cpp)

# Five-line chain (E kernel -> C runtime -> A publisher -> B catalog ->
# durable re-read): only when CPP-E is in this build; the suite must not
# silently stand in a fake attribute kernel for the real one.
if(PWB_BUILD_SEISMIC_ATTRIBUTES)
    pwb_add_integration_test(attribute_chain test_attribute_chain.cpp)
    target_link_libraries(integration_attribute_chain PRIVATE
        Pwb::SeismicAttributes)
    target_compile_definitions(integration_attribute_chain PRIVATE
        PWB_ATTRIBUTES_FIXTURE_ROOT="${CMAKE_SOURCE_DIR}/tests/cpp/seismic_attributes/fixtures")
endif()
