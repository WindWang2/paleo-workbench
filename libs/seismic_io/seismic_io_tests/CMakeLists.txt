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

# S line: tile reads (windows/cancel/refusals) + bounded LRU tile cache.
add_executable(seismic_io.tile_read tile_read_test.cpp)
target_compile_features(seismic_io.tile_read PRIVATE cxx_std_20)
target_link_libraries(seismic_io.tile_read PRIVATE Pwb::SeismicIo)
target_compile_definitions(seismic_io.tile_read PRIVATE
    PWB_SEISMIC_IO_FIXTURE_ROOT="${CMAKE_CURRENT_SOURCE_DIR}/fixtures")
add_test(NAME seismic_io.tile_read COMMAND seismic_io.tile_read)
set_tests_properties(seismic_io.tile_read PROPERTIES TIMEOUT 60)

add_executable(seismic_io.tile_cache tile_cache_test.cpp)
target_compile_features(seismic_io.tile_cache PRIVATE cxx_std_20)
target_link_libraries(seismic_io.tile_cache PRIVATE Pwb::SeismicIo)
add_test(NAME seismic_io.tile_cache COMMAND seismic_io.tile_cache)
set_tests_properties(seismic_io.tile_cache PROPERTIES TIMEOUT 60)
