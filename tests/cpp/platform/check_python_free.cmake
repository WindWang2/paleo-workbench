# check_python_free.cmake — POSIX ctest helper: the product binary's full
# ldd closure must not resolve any python/PySide shared object. This is the
# link-time half of the python-free product contract; the in-process half
# (/proc/self/maps scan) runs inside --self-check / --diagnostics.

if(NOT DEFINED PWB_PLATFORM_EXE)
    message(FATAL_ERROR "PWB_PLATFORM_EXE required")
endif()

find_program(LDD ldd)
if(NOT LDD)
    message(FATAL_ERROR "ldd not available (POSIX-only test)")
endif()

execute_process(
    COMMAND ${LDD} ${PWB_PLATFORM_EXE}
    OUTPUT_VARIABLE output
    ERROR_VARIABLE stderr
    RESULT_VARIABLE result)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "ldd exited ${result}: ${stderr}")
endif()

string(TOLOWER "${output}" lowered)
foreach(banned IN ITEMS "python" "pyside" "shiboken")
    string(FIND "${lowered}" "${banned}" position)
    if(NOT position LESS 0)
        # Show the offending line(s), not the whole closure.
        string(REGEX MATCH "[^\n]*${banned}[^\n]*" offending "${lowered}")
        message(FATAL_ERROR
            "python runtime leaked into the link closure: ${offending}")
    endif()
endforeach()
message(STATUS "link closure python-free")
