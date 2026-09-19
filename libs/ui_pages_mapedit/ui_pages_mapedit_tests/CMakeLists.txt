# UI-08 — ui_pages_mapedit tests. ctest names: ui_pages_mapedit.* —
# offscreen Qt widget/scene tests plus Qt-free helper checks (they link the
# same library target; QT_QPA_PLATFORM=offscreen everywhere).

find_package(Qt6 COMPONENTS Test)

# --- Qt-free helper tests (geometry/index/normalization) -------------------
add_executable(ui_pages_mapedit.helpers helpers_test.cpp)
target_compile_features(ui_pages_mapedit.helpers PRIVATE cxx_std_20)
target_link_libraries(ui_pages_mapedit.helpers PRIVATE
    Pwb::UiPagesMapedit Qt6::Widgets Qt6::Test)
target_include_directories(ui_pages_mapedit.helpers PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_pages_mapedit.helpers COMMAND ui_pages_mapedit.helpers)
set_tests_properties(ui_pages_mapedit.helpers PROPERTIES
    TIMEOUT 120
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen")

# --- Scene + widget parity tests -------------------------------------------
add_executable(ui_pages_mapedit.widgets widgets_test.cpp)
target_compile_features(ui_pages_mapedit.widgets PRIVATE cxx_std_20)
set_target_properties(ui_pages_mapedit.widgets PROPERTIES AUTOMOC ON)
target_link_libraries(ui_pages_mapedit.widgets PRIVATE
    Pwb::UiPagesMapedit Qt6::Widgets Qt6::Test)
target_include_directories(ui_pages_mapedit.widgets PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_pages_mapedit.widgets COMMAND ui_pages_mapedit.widgets)
set_tests_properties(ui_pages_mapedit.widgets PROPERTIES
    TIMEOUT 300
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
