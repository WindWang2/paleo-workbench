if(NOT DEFINED ENGINE_BUILD_DIR OR
   NOT DEFINED CONSUMER_SOURCE_DIR OR
   NOT DEFINED TEST_ROOT)
    message(FATAL_ERROR "consumer test paths were not provided")
endif()

set(prefix_dir "${TEST_ROOT}/prefix")
set(consumer_build_dir "${TEST_ROOT}/build")
file(REMOVE_RECURSE "${TEST_ROOT}")

set(config_args)
set(ctest_config_args)
if(DEFINED TEST_CONFIG AND NOT TEST_CONFIG STREQUAL "")
    list(APPEND config_args --config "${TEST_CONFIG}")
    list(APPEND ctest_config_args -C "${TEST_CONFIG}")
endif()

execute_process(
    COMMAND
        "${CMAKE_COMMAND}" --install "${ENGINE_BUILD_DIR}"
        --prefix "${prefix_dir}" ${config_args}
    RESULT_VARIABLE install_result
    COMMAND_ECHO STDOUT
)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR "WellLogEngine installation failed")
endif()

execute_process(
    COMMAND
        "${CMAKE_COMMAND}"
        -S "${CONSUMER_SOURCE_DIR}"
        -B "${consumer_build_dir}"
        "-DCMAKE_PREFIX_PATH=${prefix_dir}"
        "-DCMAKE_CXX_COMPILER=${ENGINE_CXX_COMPILER}"
        "-DCMAKE_CXX_FLAGS=${ENGINE_CXX_FLAGS}"
        "-DCMAKE_EXE_LINKER_FLAGS=${ENGINE_EXE_LINKER_FLAGS}"
    RESULT_VARIABLE configure_result
    COMMAND_ECHO STDOUT
)
if(NOT configure_result EQUAL 0)
    message(FATAL_ERROR "external consumer configuration failed")
endif()

execute_process(
    COMMAND
        "${CMAKE_COMMAND}" --build "${consumer_build_dir}" ${config_args}
    RESULT_VARIABLE build_result
    COMMAND_ECHO STDOUT
)
if(NOT build_result EQUAL 0)
    message(FATAL_ERROR "external consumer build failed")
endif()

if(WIN32)
    set(path_separator ";")
else()
    set(path_separator ":")
endif()
set(consumer_path "${prefix_dir}/bin${path_separator}$ENV{PATH}")

execute_process(
    COMMAND
        "${CMAKE_COMMAND}" -E env
        "PATH=${consumer_path}"
        "${CMAKE_CTEST_COMMAND}"
        --test-dir "${consumer_build_dir}"
        --output-on-failure ${ctest_config_args}
    RESULT_VARIABLE test_result
    COMMAND_ECHO STDOUT
)
if(NOT test_result EQUAL 0)
    message(FATAL_ERROR "external consumer execution failed")
endif()
