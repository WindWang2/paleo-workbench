# seismic_io tests — CTest names start with "seismic_io.". The oracle is
# the frozen tiny_sgy_real case: the same real tiny.sgy the geoviz Python
# loader read when the fixture was generated.
add_executable(seismic_io.segy_read segy_read_test.cpp)
target_compile_features(seismic_io.segy_read PRIVATE cxx_std_20)
target_link_libraries(seismic_io.segy_read PRIVATE Pwb::SeismicIo)
target_compile_definitions(seismic_io.segy_read PRIVATE
    PWB_REALDATA_DIR="${CMAKE_SOURCE_DIR}/tests/fixtures/realdata"
    PWB_ATTRIBUTE_FIXTURES="${CMAKE_SOURCE_DIR}/tests/cpp/seismic_attributes/fixtures")
add_test(NAME seismic_io.segy_read COMMAND seismic_io.segy_read)
set_tests_properties(seismic_io.segy_read PROPERTIES TIMEOUT 60)
