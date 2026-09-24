# qgis_processing tests — CTest names are qgis_processing.* (Wave A test
# matrix). Real QgsApplication + real registry/task manager; never a fake
# success. GUI runs offscreen; the runtime closure (QGIS vendor lib + Qt
# lib) is prepended to PATH/LD_LIBRARY_PATH exactly like the platform
# tests, so the tests exercise the real provider/plugin/CRS stack.

# PROJ data: the Windows vendor tree carries share/proj; on Linux the .so
# set resolves PROJ from the system package (/usr/share/proj).
if(EXISTS "${PALEO_QGIS_SDK_DIR}/share/proj")
    set(PWB_PROJ_DATA "${PALEO_QGIS_SDK_DIR}/share/proj")
else()
    set(PWB_PROJ_DATA "/usr/share/proj")
endif()
# GDAL data: only the real GDAL data dir (marker file probe) counts — the
# vendor output/data on Linux is QGIS resources, not GDAL's csv tree.
if(EXISTS "${PALEO_QGIS_SDK_DIR}/data/pcs.csv")
    set(PWB_GDAL_DATA "${PALEO_QGIS_SDK_DIR}/data")
elseif(EXISTS "/usr/share/gdal/pcs.csv")
    set(PWB_GDAL_DATA "/usr/share/gdal")
else()
    set(PWB_GDAL_DATA "")
endif()
if(PWB_GDAL_DATA)
    set(PWB_GDAL_DATA_ENV ";GDAL_DATA=${PWB_GDAL_DATA}")
else()
    set(PWB_GDAL_DATA_ENV "")
endif()
# GDAL raster drivers (GTiff sink/reads in the run battery): the .so set
# resolves GDAL from the deps prefix; its driver plugins must be on
# GDAL_DRIVER_PATH or raster read/write degrades (CONV-27 parity).
set(PWB_GDAL_DRIVER_PATH "")
if(EXISTS "/home/kevin/pwb-sdks/root/usr/lib/gdalplugins/gdal_PNG.so")
    set(PWB_GDAL_DRIVER_PATH "/home/kevin/pwb-sdks/root/usr/lib/gdalplugins")
elseif(EXISTS "/usr/lib/gdalplugins/gdal_PNG.so")
    set(PWB_GDAL_DRIVER_PATH "/usr/lib/gdalplugins")
endif()
if(PWB_GDAL_DRIVER_PATH)
    string(APPEND PWB_GDAL_DATA_ENV ";GDAL_DRIVER_PATH=${PWB_GDAL_DRIVER_PATH}")
endif()

function(pwb_add_qgis_processing_test name)
    add_executable(qgis_processing_${name} ${ARGN})
    set_target_properties(qgis_processing_${name} PROPERTIES AUTOMOC ON)
    target_compile_features(qgis_processing_${name} PRIVATE cxx_std_20)
    target_include_directories(qgis_processing_${name} PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    target_link_libraries(qgis_processing_${name} PRIVATE
        Pwb::QgisProcessing Pwb::Qgis Pwb::JobContracts Pwb::JobGovernance)
    add_test(NAME qgis_processing.${name} COMMAND qgis_processing_${name})
    set_tests_properties(qgis_processing.${name} PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
        TIMEOUT 300)
endfunction()

pwb_add_qgis_processing_test(provider provider_test.cpp)
pwb_add_qgis_processing_test(run algorithm_run_test.cpp)
pwb_add_qgis_processing_test(task_bridge task_bridge_test.cpp)
