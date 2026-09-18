# check_diagnostics.cmake — ctest helper for `pwb-platform --diagnostics`.
#
# Fails unless the report exits 0 and carries the load-bearing sections:
# versions, providers, the CRS probe and the python-runtime verdict.

if(NOT DEFINED PWB_PLATFORM_EXE)
    message(FATAL_ERROR "PWB_PLATFORM_EXE required")
endif()

execute_process(
    COMMAND ${PWB_PLATFORM_EXE} --diagnostics
    OUTPUT_VARIABLE output
    ERROR_VARIABLE stderr
    RESULT_VARIABLE result
    TIMEOUT 90)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "--diagnostics exited ${result}\n${output}\n${stderr}")
endif()
foreach(required IN ITEMS
        "[versions]" "[vector providers]" "[probes]"
        "crs EPSG:4326: ok" "temp writable: ok")
    string(FIND "${output}" "${required}" position)
    if(position LESS 0)
        message(FATAL_ERROR "diagnostics report missing '${required}':\n${output}")
    endif()
endforeach()
# python runtime verdict: verified on POSIX; not-probed elsewhere. Any
# other value (leaked:...) is a product defect.
string(REGEX MATCH "python runtime: (verified|not-probed)" verdict "${output}")
if(verdict STREQUAL "")
    message(FATAL_ERROR "python runtime verdict missing:\n${output}")
endif()
message(STATUS "diagnostics report ok")
