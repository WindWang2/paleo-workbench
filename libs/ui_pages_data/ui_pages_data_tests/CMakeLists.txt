add_executable(ui_pages_data.smoke smoke_test.cpp)
target_compile_features(ui_pages_data.smoke PRIVATE cxx_std_20)
target_link_libraries(ui_pages_data.smoke PRIVATE Pwb::UiPagesData)
add_test(NAME ui_pages_data.smoke COMMAND ui_pages_data.smoke)
set_tests_properties(ui_pages_data.smoke PROPERTIES TIMEOUT 120)

# 08-line closure — PreparationPage lifecycle guards (offscreen Qt).
if(TARGET pwb_ui_pages_data_qt)
    find_package(Qt6 COMPONENTS Test)
    add_executable(ui_pages_data.preparation_page preparation_page_test.cpp)
    target_compile_features(ui_pages_data.preparation_page PRIVATE cxx_std_20)
    set_target_properties(ui_pages_data.preparation_page PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_pages_data.preparation_page PRIVATE
        Pwb::UiPagesDataQt Qt6::Widgets Qt6::Test)
    add_test(NAME ui_pages_data.preparation_page
             COMMAND ui_pages_data.preparation_page)
    set_tests_properties(ui_pages_data.preparation_page PROPERTIES
        TIMEOUT 180
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endif()
