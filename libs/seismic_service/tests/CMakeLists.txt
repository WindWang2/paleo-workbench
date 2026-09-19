# seismic_service tests (CTest prefix seismic_service.). Consumes the same
# frozen IO oracle fixtures as seismic_io.tile_read, plus its own synthetic
# 32^3 / 64^3 smoke volumes.
add_executable(seismic_service.service service_test.cpp)
target_compile_features(seismic_service.service PRIVATE cxx_std_20)
target_link_libraries(seismic_service.service PRIVATE Pwb::SeismicService)
target_compile_definitions(seismic_service.service PRIVATE
    PWB_SEISMIC_IO_FIXTURE_ROOT="${CMAKE_CURRENT_LIST_DIR}/../../seismic_io/seismic_io_tests/fixtures")
if(MSVC)
    target_compile_options(seismic_service.service PRIVATE /W4)
else()
    target_compile_options(seismic_service.service PRIVATE -Wall -Wextra -Wpedantic)
endif()
add_test(NAME seismic_service.service COMMAND seismic_service.service)
set_tests_properties(seismic_service.service PROPERTIES TIMEOUT 120)
