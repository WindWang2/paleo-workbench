# Seismic attribute tests (added from libs/seismic_attributes). Every CTest
# name starts with "seismic_attributes.". The group is mandatory when
# PWB_SEISMIC_ATTRIBUTES_BUILD_TESTS=ON: missing fixtures or build deps fail
# the build — they never degrade into skipped tests.

function(pwb_seismic_attributes_test target source)
    add_executable(${target} ${source})
    target_compile_features(${target} PRIVATE cxx_std_20)
    target_include_directories(${target} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive- /wd4251 /wd4275)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    add_test(NAME ${target} COMMAND ${target})
    set_tests_properties(${target} PROPERTIES TIMEOUT 600
        ENVIRONMENT "PWB_SEISMIC_ATTRIBUTES_FIXTURE_ROOT=${CMAKE_CURRENT_SOURCE_DIR}/fixtures")
endfunction()

pwb_seismic_attributes_test(seismic_attributes.kernels attribute_kernels_test.cpp)
target_link_libraries(seismic_attributes.kernels PRIVATE Pwb::SeismicAttributes)

pwb_seismic_attributes_test(seismic_attributes.registration attributes_registration_test.cpp)
target_link_libraries(seismic_attributes.registration PRIVATE Pwb::SeismicAttributes)

pwb_seismic_attributes_test(seismic_attributes.runtime attributes_runtime_test.cpp)
target_link_libraries(seismic_attributes.runtime PRIVATE
    Pwb::SeismicAttributes
    Pwb::Workflow
)

pwb_seismic_attributes_test(seismic_attributes.perf attribute_perf_test.cpp)
target_link_libraries(seismic_attributes.perf PRIVATE Pwb::SeismicAttributes)

# S line: volume-structural kernels vs the frozen sl_* oracle fixtures.
pwb_seismic_attributes_test(seismic_attributes.sline attribute_sline_test.cpp)
target_link_libraries(seismic_attributes.sline PRIVATE Pwb::SeismicAttributes)
