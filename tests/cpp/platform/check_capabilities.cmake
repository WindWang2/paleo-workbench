# check_capabilities.cmake — ctest helper for `pwb-platform --capabilities`.
#
# Fails unless (a) the command exits 0, (b) every capability id listed in
# PWB_EXPECTED_HARD_CAPS is reported as `linked runtime-ok`, and (c) no
# capability reported `absent` also appears in the expected list (drift
# between the configure-time closure and the binary's table).

if(NOT DEFINED PWB_PLATFORM_EXE OR NOT DEFINED PWB_EXPECTED_HARD_CAPS)
    message(FATAL_ERROR "PWB_PLATFORM_EXE and PWB_EXPECTED_HARD_CAPS required")
endif()

execute_process(
    COMMAND ${PWB_PLATFORM_EXE} --capabilities
    OUTPUT_VARIABLE output
    ERROR_VARIABLE stderr
    RESULT_VARIABLE result
    TIMEOUT 90)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "--capabilities exited ${result}\n${output}\n${stderr}")
endif()

# PWB_EXPECTED_HARD_CAPS arrives as a plain semicolon list; IN LISTS splits
# it natively (separate_arguments NATIVE_COMMAND would keep it as ONE
# element because the mode splits on whitespace, not semicolons).
set(failed)
foreach(id IN LISTS PWB_EXPECTED_HARD_CAPS)
    # capability <id> linked runtime-ok ...
    string(REGEX MATCH "capability ${id} linked runtime-ok" matched "${output}")
    if(matched STREQUAL "")
        list(APPEND failed "${id}")
    endif()
endforeach()
if(failed)
    list(JOIN failed ", " joined)
    message(FATAL_ERROR
        "capability matrix drift: missing/linked-but-degraded [${joined}]\n"
        "${output}")
endif()
message(STATUS "capability matrix ok: [${PWB_EXPECTED_HARD_CAPS}]")
