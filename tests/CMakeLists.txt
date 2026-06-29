find_library(GTEST_LIB gtest REQUIRED)
find_library(GTEST_MAIN_LIB gtest_main REQUIRED)
find_path(GTEST_INCLUDE_DIR gtest/gtest.h)

add_executable(test_config test_config.cc)
target_include_directories(test_config PRIVATE ${GTEST_INCLUDE_DIR} ../src)
target_link_libraries(test_config PRIVATE wsburrow_lib ${GTEST_LIB} ${GTEST_MAIN_LIB} pthread)
add_test(NAME test_config COMMAND test_config)

add_executable(test_jwt test_jwt.cc)
target_include_directories(test_jwt PRIVATE ${GTEST_INCLUDE_DIR} ../src)
target_link_libraries(test_jwt PRIVATE wsburrow_lib ${GTEST_LIB} ${GTEST_MAIN_LIB} pthread)
add_test(NAME test_jwt COMMAND test_jwt)

find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_FOUND)
    add_test(NAME test_integration
        COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test_integration.py)
    set_tests_properties(test_integration PROPERTIES TIMEOUT 200)
endif()
